"""Sistema web de gestión de ingresos y gastos.

Ejecutar con:  python app.py
"""
import csv
import glob
import io
import logging
import os
import re
import secrets
import socket
import tempfile
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta

from flask import (
    Flask, Response, abort, flash, g, redirect, render_template, request,
    send_file, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import database
from database import get_db
from utilidades import (
    ICONOS, MESES, MESES_CORTOS, PERIODOS, fecha_corta, fin_de_mes,
    formato_dinero, importe_para_formulario, parse_fecha, parse_importe,
    rango_periodo, semanas_del_mes, sumar_meses,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TIPOS = {"ingreso": "Ingreso", "gasto": "Gasto"}
TIPOS_CATEGORIA = {"ingreso": "Solo ingresos", "gasto": "Solo gastos", "ambos": "Ingresos y gastos"}
POR_PAGINA = 50
RUTAS_PUBLICAS = {"login", "configuracion_inicial", "static"}
log = logging.getLogger(__name__)


def create_app(config=None):
    app = Flask(__name__)
    datos = os.path.join(BASE_DIR, "datos")
    app.config.update(
        DATOS_DIR=datos,
        DATABASE=os.path.join(datos, "finanzas.db"),
        COPIAS_DIR=os.path.join(datos, "copias"),
        COPIAS_AUTOMATICAS=30,
        CSRF=True,
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    if config:
        app.config.update(config)

    os.makedirs(app.config["DATOS_DIR"], exist_ok=True)
    os.makedirs(app.config["COPIAS_DIR"], exist_ok=True)
    app.secret_key = app.config.get("SECRET_KEY") or cargar_clave_secreta(app.config["DATOS_DIR"])
    database.init_db(app.config["DATABASE"])
    app.teardown_appcontext(database.close_db)

    registrar_plantillas(app)
    registrar_rutas(app)
    return app


def cargar_clave_secreta(carpeta):
    ruta = os.path.join(carpeta, "clave_secreta.txt")
    if not os.path.exists(ruta):
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(ruta, encoding="utf-8") as f:
        return f.read().strip()


# ====================================================================== plantillas

def registrar_plantillas(app):
    def dinero(centimos, signo=False):
        a = g.get("ajustes") or database.AJUSTES_POR_DEFECTO
        return formato_dinero(centimos, a["simbolo"], a["separadores"], signo)

    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(32)
        return session["_csrf"]

    def url_con(**cambios):
        """URL actual con algunos parámetros cambiados (para paginación)."""
        args = request.args.to_dict()
        args.update({k: v for k, v in cambios.items()})
        return url_for(request.endpoint, **{k: v for k, v in args.items() if v not in (None, "")})

    def estatico(nombre):
        """URL de un archivo estático con versión, para que el navegador cargue siempre la última."""
        try:
            version = int(os.path.getmtime(os.path.join(app.static_folder, nombre)))
        except OSError:
            version = 0
        return url_for("static", filename=nombre, v=version)

    app.jinja_env.globals["estatico"] = estatico
    app.jinja_env.filters["dinero"] = dinero
    app.jinja_env.filters["fecha"] = fecha_corta
    app.jinja_env.globals.update(
        ICONOS=ICONOS, MESES=MESES, MESES_CORTOS=MESES_CORTOS, TIPOS=TIPOS,
        TIPOS_CATEGORIA=TIPOS_CATEGORIA, PERIODOS=PERIODOS,
        csrf_token=csrf_token, url_con=url_con,
    )

    @app.context_processor
    def contexto():
        return {"ajustes": g.get("ajustes") or database.AJUSTES_POR_DEFECTO, "hoy": date.today()}


# ====================================================================== consultas

def sumas(where="1=1", params=()):
    fila = get_db().execute(
        f"""SELECT COALESCE(SUM(CASE WHEN m.tipo = 'ingreso' THEN m.importe_cent END), 0) AS ingresos,
                   COALESCE(SUM(CASE WHEN m.tipo = 'gasto' THEN m.importe_cent END), 0) AS gastos,
                   COUNT(*) AS cantidad
            FROM movimientos m WHERE {where}""",
        params,
    ).fetchone()
    return {
        "ingresos": fila["ingresos"],
        "gastos": fila["gastos"],
        "saldo": fila["ingresos"] - fila["gastos"],
        "cantidad": fila["cantidad"],
    }


def sumas_rango(desde, hasta):
    return sumas("m.fecha BETWEEN ? AND ?", (desde.isoformat(), hasta.isoformat()))


def por_categoria(desde, hasta):
    """Totales por categoría y tipo dentro de un rango de fechas."""
    filas = get_db().execute(
        """SELECT c.id, c.nombre, c.color, m.tipo, SUM(m.importe_cent) AS total, COUNT(*) AS cantidad
           FROM movimientos m JOIN categorias c ON c.id = m.categoria_id
           WHERE m.fecha BETWEEN ? AND ?
           GROUP BY c.id, m.tipo ORDER BY total DESC""",
        (desde.isoformat(), hasta.isoformat()),
    ).fetchall()
    resultado = {"ingreso": [], "gasto": []}
    for f in filas:
        resultado[f["tipo"]].append(dict(f))
    for tipo, lista in resultado.items():
        total = sum(f["total"] for f in lista) or 1
        for f in lista:
            f["porcentaje"] = round(f["total"] * 100 / total, 1)
    return resultado


def categorias(tipo=None):
    sql = "SELECT * FROM categorias"
    params = ()
    if tipo:
        sql += " WHERE tipo IN (?, 'ambos')"
        params = (tipo,)
    return get_db().execute(sql + " ORDER BY nombre COLLATE NOCASE", params).fetchall()


def obtener_movimiento(mov_id):
    fila = get_db().execute("SELECT * FROM movimientos WHERE id = ?", (mov_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def obtener_categoria(cat_id):
    fila = get_db().execute("SELECT * FROM categorias WHERE id = ?", (cat_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def leer_filtros(args):
    """Interpreta los filtros de la lista de movimientos.

    Devuelve (filtros para la plantilla, condición SQL, parámetros).
    """
    periodo = args.get("periodo", "todo")
    if periodo not in dict(PERIODOS):
        periodo = "todo"
    desde = hasta = None
    if periodo == "personalizado":
        desde, hasta = parse_fecha(args.get("desde")), parse_fecha(args.get("hasta"))
        if desde and hasta and desde > hasta:
            desde, hasta = hasta, desde
    else:
        desde, hasta = rango_periodo(periodo)

    tipo = args.get("tipo", "")
    tipo = tipo if tipo in TIPOS else ""
    categoria = args.get("categoria", "")
    categoria = int(categoria) if categoria.isdigit() else ""
    texto = (args.get("q") or "").strip()[:100]

    where, params = [], []
    if desde:
        where.append("m.fecha >= ?")
        params.append(desde.isoformat())
    if hasta:
        where.append("m.fecha <= ?")
        params.append(hasta.isoformat())
    if tipo:
        where.append("m.tipo = ?")
        params.append(tipo)
    if categoria:
        where.append("m.categoria_id = ?")
        params.append(categoria)
    if texto:
        escapado = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("m.descripcion LIKE ? ESCAPE '\\'")
        params.append(f"%{escapado}%")

    filtros = {
        "periodo": periodo, "desde": desde, "hasta": hasta,
        "tipo": tipo, "categoria": categoria, "q": texto,
        "activos": bool(where),
    }
    return filtros, " AND ".join(where) or "1=1", params


def leer_form_movimiento(form):
    datos, errores = {}, {}
    tipo = form.get("tipo")
    if tipo not in TIPOS:
        errores["tipo"] = "Elige si es un ingreso o un gasto."
    datos["tipo"] = tipo

    datos["importe_texto"] = (form.get("importe") or "").strip()
    try:
        datos["importe_cent"] = parse_importe(datos["importe_texto"], g.ajustes["separadores"])
    except ValueError as e:
        errores["importe"] = str(e)

    datos["fecha_texto"] = form.get("fecha", "")
    fecha = parse_fecha(datos["fecha_texto"])
    if not fecha or not (1900 <= fecha.year <= 2200):
        errores["fecha"] = "Introduce una fecha válida."
    else:
        datos["fecha"] = fecha.isoformat()

    cat = form.get("categoria_id", "")
    fila = get_db().execute(
        "SELECT * FROM categorias WHERE id = ?", (int(cat) if cat.isdigit() else -1,)
    ).fetchone()
    if fila is None:
        errores["categoria_id"] = "Elige una categoría."
    elif tipo in TIPOS and fila["tipo"] not in (tipo, "ambos"):
        errores["categoria_id"] = f"La categoría «{fila['nombre']}» no admite {TIPOS[tipo].lower()}s."
    datos["categoria_id"] = fila["id"] if fila else None

    datos["descripcion"] = " ".join((form.get("descripcion") or "").split())[:200]
    return datos, errores


def destino_seguro(url, por_defecto):
    """Evita redirecciones a otros sitios."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return por_defecto


# ====================================================================== copias de seguridad

def copia_automatica(app):
    """Una copia diaria de la base de datos; se conservan las más recientes."""
    hoy = date.today().isoformat()
    if app.config.get("_ULTIMA_COPIA") == hoy:
        return
    try:
        carpeta = app.config["COPIAS_DIR"]
        destino = os.path.join(carpeta, f"auto-{hoy}.db")
        if not os.path.exists(destino):
            database.copiar(app.config["DATABASE"], destino)
        copias = sorted(glob.glob(os.path.join(carpeta, "auto-*.db")))
        for vieja in copias[: -app.config["COPIAS_AUTOMATICAS"]]:
            os.remove(vieja)
        app.config["_ULTIMA_COPIA"] = hoy
    except OSError:
        log.exception("No se pudo crear la copia automática")


def listar_copias(carpeta):
    copias = []
    for ruta in sorted(glob.glob(os.path.join(carpeta, "*.db")), key=os.path.getmtime, reverse=True):
        info = os.stat(ruta)
        copias.append({
            "nombre": os.path.basename(ruta),
            "tamano_kb": max(1, round(info.st_size / 1024)),
            "fecha": datetime.fromtimestamp(info.st_mtime),
        })
    return copias


# ====================================================================== rutas

def registrar_rutas(app):

    @app.before_request
    def antes_de_cada_peticion():
        if request.endpoint == "static":
            return None
        if app.config["CSRF"] and request.method == "POST":
            enviado = request.form.get("_csrf", "")
            if not enviado or not secrets.compare_digest(enviado, session.get("_csrf", "")):
                return render_template(
                    "error.html", codigo=400,
                    mensaje="La sesión expiró o el formulario ya no es válido. Vuelve atrás e inténtalo de nuevo.",
                ), 400
        g.ajustes = database.leer_ajustes()
        copia_automatica(app)
        if request.endpoint in RUTAS_PUBLICAS:
            return None
        if not g.ajustes.get("password_hash"):
            return redirect(url_for("configuracion_inicial"))
        if not session.get("autenticado"):
            return redirect(url_for("login", next=request.full_path))
        return None

    @app.after_request
    def cabeceras(respuesta):
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        return respuesta

    @app.errorhandler(404)
    def no_encontrado(_e):
        return render_template("error.html", codigo=404, mensaje="La página que buscas no existe."), 404

    @app.errorhandler(413)
    def demasiado_grande(_e):
        flash("El archivo es demasiado grande.", "error")
        return redirect(url_for("ajustes"))

    # ------------------------------------------------------------ acceso

    @app.route("/configuracion-inicial", methods=["GET", "POST"])
    def configuracion_inicial():
        if g.ajustes.get("password_hash"):
            return redirect(url_for("login"))
        errores = {}
        if request.method == "POST":
            nombre = " ".join(request.form.get("nombre_negocio", "").split())[:60]
            clave = request.form.get("password", "")
            if not nombre:
                errores["nombre_negocio"] = "Escribe el nombre de tu negocio."
            if len(clave) < 6:
                errores["password"] = "La contraseña debe tener al menos 6 caracteres."
            elif clave != request.form.get("password2", ""):
                errores["password2"] = "Las contraseñas no coinciden."
            if not errores:
                database.guardar_ajuste("nombre_negocio", nombre)
                database.guardar_ajuste("password_hash", generate_password_hash(clave))
                session.clear()
                session["autenticado"] = True
                session.permanent = True
                flash("¡Todo listo! Ya puedes registrar tus movimientos.", "ok")
                return redirect(url_for("resumen"))
        return render_template("configuracion_inicial.html", errores=errores, form=request.form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not g.ajustes.get("password_hash"):
            return redirect(url_for("configuracion_inicial"))
        error_login = None
        if request.method == "POST":
            if check_password_hash(g.ajustes["password_hash"], request.form.get("password", "")):
                session.clear()
                session["autenticado"] = True
                session.permanent = bool(request.form.get("recordar"))
                return redirect(destino_seguro(request.args.get("next"), url_for("resumen")))
            time.sleep(1)  # frena los intentos repetidos
            error_login = "Contraseña incorrecta."
        return render_template("login.html", error_login=error_login)

    @app.route("/salir", methods=["POST"])
    def salir():
        session.clear()
        flash("Has cerrado la sesión.", "ok")
        return redirect(url_for("login"))

    # ------------------------------------------------------------ resumen

    @app.route("/")
    def resumen():
        hoy = date.today()
        inicio_mes = hoy.replace(day=1)
        inicio_semana = hoy - timedelta(days=hoy.weekday())

        meses = []
        for i in range(5, -1, -1):
            inicio = sumar_meses(inicio_mes, -i)
            s = sumas_rango(inicio, fin_de_mes(inicio))
            s["etiqueta"] = f"{MESES_CORTOS[inicio.month - 1]}"
            s["mes"] = inicio.strftime("%Y-%m")
            meses.append(s)
        maximo = max([max(m["ingresos"], m["gastos"]) for m in meses] + [1])

        recientes = get_db().execute(
            """SELECT m.*, c.nombre AS categoria, c.color FROM movimientos m
               JOIN categorias c ON c.id = m.categoria_id
               ORDER BY m.fecha DESC, m.id DESC LIMIT 8"""
        ).fetchall()

        return render_template(
            "resumen.html",
            total=sumas(),
            mes=sumas_rango(inicio_mes, fin_de_mes(inicio_mes)),
            semana=sumas_rango(inicio_semana, inicio_semana + timedelta(days=6)),
            meses=meses,
            maximo=maximo,
            recientes=recientes,
            gastos_mes=por_categoria(inicio_mes, fin_de_mes(inicio_mes))["gasto"][:5],
            nombre_mes=MESES[hoy.month - 1],
        )

    # ------------------------------------------------------------ movimientos

    @app.route("/movimientos")
    def movimientos():
        filtros, where, params = leer_filtros(request.args)
        totales = sumas(where, params)
        paginas = max(1, -(-totales["cantidad"] // POR_PAGINA))
        pagina = min(max(request.args.get("pagina", 1, type=int), 1), paginas)
        filas = get_db().execute(
            f"""SELECT m.*, c.nombre AS categoria, c.color FROM movimientos m
                JOIN categorias c ON c.id = m.categoria_id
                WHERE {where} ORDER BY m.fecha DESC, m.id DESC LIMIT ? OFFSET ?""",
            (*params, POR_PAGINA, (pagina - 1) * POR_PAGINA),
        ).fetchall()
        return render_template(
            "movimientos.html", movimientos=filas, filtros=filtros, totales=totales,
            pagina=pagina, paginas=paginas, categorias=categorias(),
        )

    @app.route("/movimientos/exportar")
    def exportar_movimientos():
        _filtros, where, params = leer_filtros(request.args)
        filas = get_db().execute(
            f"""SELECT m.fecha, m.tipo, c.nombre AS categoria, m.descripcion, m.importe_cent
                FROM movimientos m JOIN categorias c ON c.id = m.categoria_id
                WHERE {where} ORDER BY m.fecha, m.id""",
            params,
        ).fetchall()
        formato = g.ajustes["separadores"]
        delimitador = ";" if formato == "punto_coma" else ","
        salida = io.StringIO()
        escritor = csv.writer(salida, delimiter=delimitador)
        escritor.writerow(["Fecha", "Tipo", "Categoría", "Descripción", "Importe"])
        for f in filas:
            importe = importe_para_formulario(f["importe_cent"], formato)
            if f["tipo"] == "gasto":
                importe = "-" + importe
            escritor.writerow([fecha_corta(f["fecha"]), TIPOS[f["tipo"]], f["categoria"], f["descripcion"], importe])
        nombre = f"movimientos-{date.today().isoformat()}.csv"
        return Response(
            "﻿" + salida.getvalue(),  # BOM para que Excel muestre bien los acentos
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={nombre}"},
        )

    def guardar_movimiento(mov=None):
        volver = destino_seguro(request.values.get("next"), url_for("movimientos"))
        if request.method == "POST":
            datos, errores = leer_form_movimiento(request.form)
            if not errores:
                db = get_db()
                valores = (datos["tipo"], datos["importe_cent"], datos["fecha"],
                           datos["categoria_id"], datos["descripcion"])
                with db:
                    if mov is None:
                        db.execute(
                            """INSERT INTO movimientos (tipo, importe_cent, fecha, categoria_id, descripcion)
                               VALUES (?, ?, ?, ?, ?)""", valores)
                    else:
                        db.execute(
                            """UPDATE movimientos SET tipo = ?, importe_cent = ?, fecha = ?, categoria_id = ?,
                               descripcion = ?, actualizado_en = datetime('now', 'localtime') WHERE id = ?""",
                            (*valores, mov["id"]))
                texto = f"{TIPOS[datos['tipo']]} de {formato_dinero(datos['importe_cent'], g.ajustes['simbolo'], g.ajustes['separadores'])}"
                flash(f"{texto} {'guardado' if mov is None else 'actualizado'} correctamente.", "ok")
                if mov is None and request.form.get("accion") == "otro":
                    return redirect(url_for("nuevo_movimiento", tipo=datos["tipo"], fecha=datos["fecha"], next=volver))
                return redirect(volver)
            valores_form = {
                "tipo": datos["tipo"], "importe": datos["importe_texto"], "fecha": datos["fecha_texto"],
                "categoria_id": datos["categoria_id"], "descripcion": datos["descripcion"],
            }
            estado = 400
        else:
            errores, estado = {}, 200
            if mov is None:
                tipo = request.args.get("tipo")
                fecha = parse_fecha(request.args.get("fecha")) or date.today()
                valores_form = {"tipo": tipo if tipo in TIPOS else "ingreso", "importe": "",
                                "fecha": fecha.isoformat(), "categoria_id": None, "descripcion": ""}
            else:
                valores_form = {
                    "tipo": mov["tipo"],
                    "importe": importe_para_formulario(mov["importe_cent"], g.ajustes["separadores"]),
                    "fecha": mov["fecha"], "categoria_id": mov["categoria_id"], "descripcion": mov["descripcion"],
                }
        return render_template(
            "movimiento_form.html", mov=mov, v=valores_form, errores=errores,
            categorias=categorias(), volver=volver,
        ), estado

    @app.route("/movimientos/nuevo", methods=["GET", "POST"])
    def nuevo_movimiento():
        return guardar_movimiento()

    @app.route("/movimientos/<int:mov_id>/editar", methods=["GET", "POST"])
    def editar_movimiento(mov_id):
        return guardar_movimiento(obtener_movimiento(mov_id))

    @app.route("/movimientos/<int:mov_id>/eliminar", methods=["POST"])
    def eliminar_movimiento(mov_id):
        obtener_movimiento(mov_id)
        db = get_db()
        with db:
            db.execute("DELETE FROM movimientos WHERE id = ?", (mov_id,))
        flash("Movimiento eliminado.", "ok")
        return redirect(destino_seguro(request.form.get("next"), url_for("movimientos")))

    # ------------------------------------------------------------ categorías

    def leer_form_categoria(form, actual=None):
        nombre = " ".join(form.get("nombre", "").split())[:40]
        tipo = form.get("tipo", "")
        color = form.get("color") or (actual["color"] if actual else "#64748b")
        errores = {}
        if not nombre:
            errores["nombre"] = "Escribe un nombre."
        else:
            repetida = get_db().execute(
                "SELECT id FROM categorias WHERE nombre = ? COLLATE NOCASE AND id != ?",
                (nombre, actual["id"] if actual else -1),
            ).fetchone()
            if repetida:
                errores["nombre"] = "Ya existe una categoría con ese nombre."
        if tipo not in TIPOS_CATEGORIA:
            errores["tipo"] = "Elige un tipo."
        elif actual and tipo != "ambos":
            otro = "gasto" if tipo == "ingreso" else "ingreso"
            usados = get_db().execute(
                "SELECT COUNT(*) FROM movimientos WHERE categoria_id = ? AND tipo = ?", (actual["id"], otro)
            ).fetchone()[0]
            if usados:
                errores["tipo"] = f"Tiene {usados} {TIPOS[otro].lower()}(s) registrados; no se puede limitar a {TIPOS[tipo].lower()}s."
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#64748b"
        return {"nombre": nombre, "tipo": tipo, "color": color}, errores

    def pagina_categorias(editando=None, v=None, errores=None, estado=200):
        filas = get_db().execute(
            """SELECT c.*, COUNT(m.id) AS cantidad,
                      COALESCE(SUM(CASE WHEN m.tipo = 'ingreso' THEN m.importe_cent END), 0) AS ingresos,
                      COALESCE(SUM(CASE WHEN m.tipo = 'gasto' THEN m.importe_cent END), 0) AS gastos
               FROM categorias c LEFT JOIN movimientos m ON m.categoria_id = c.id
               GROUP BY c.id ORDER BY c.nombre COLLATE NOCASE"""
        ).fetchall()
        if v is None:
            v = dict(editando) if editando else {"nombre": "", "tipo": "ambos", "color": "#4f46e5"}
        return render_template(
            "categorias.html", categorias=filas, editando=editando, v=v, errores=errores or {},
        ), estado

    @app.route("/categorias", methods=["GET", "POST"])
    def categorias_view():
        if request.method == "POST":
            datos, errores = leer_form_categoria(request.form)
            if errores:
                return pagina_categorias(v=datos, errores=errores, estado=400)
            db = get_db()
            with db:
                db.execute("INSERT INTO categorias (nombre, tipo, color) VALUES (?, ?, ?)",
                           (datos["nombre"], datos["tipo"], datos["color"]))
            flash(f"Categoría «{datos['nombre']}» creada.", "ok")
            return redirect(url_for("categorias_view"))
        return pagina_categorias()

    @app.route("/categorias/<int:cat_id>/editar", methods=["GET", "POST"])
    def editar_categoria(cat_id):
        cat = obtener_categoria(cat_id)
        if request.method == "POST":
            datos, errores = leer_form_categoria(request.form, cat)
            if errores:
                return pagina_categorias(editando=cat, v=datos, errores=errores, estado=400)
            db = get_db()
            with db:
                db.execute("UPDATE categorias SET nombre = ?, tipo = ?, color = ? WHERE id = ?",
                           (datos["nombre"], datos["tipo"], datos["color"], cat_id))
            flash(f"Categoría «{datos['nombre']}» actualizada.", "ok")
            return redirect(url_for("categorias_view"))
        return pagina_categorias(editando=cat)

    @app.route("/categorias/<int:cat_id>/eliminar", methods=["GET", "POST"])
    def eliminar_categoria(cat_id):
        cat = obtener_categoria(cat_id)
        db = get_db()
        cantidad = db.execute("SELECT COUNT(*) FROM movimientos WHERE categoria_id = ?", (cat_id,)).fetchone()[0]
        tipos_usados = {f[0] for f in db.execute(
            "SELECT DISTINCT tipo FROM movimientos WHERE categoria_id = ?", (cat_id,))}
        # Categorías que pueden recibir todos los movimientos de esta.
        destinos = [c for c in categorias() if c["id"] != cat_id
                    and (c["tipo"] == "ambos" or tipos_usados <= {c["tipo"]})]
        if request.method == "POST":
            if cantidad:
                destino = request.form.get("mover_a", "")
                if not destino.isdigit() or int(destino) not in {c["id"] for c in destinos}:
                    flash("Elige a qué categoría mover los movimientos.", "error")
                    return redirect(url_for("eliminar_categoria", cat_id=cat_id))
                with db:
                    db.execute("UPDATE movimientos SET categoria_id = ? WHERE categoria_id = ?", (int(destino), cat_id))
                    db.execute("DELETE FROM categorias WHERE id = ?", (cat_id,))
            else:
                with db:
                    db.execute("DELETE FROM categorias WHERE id = ?", (cat_id,))
            flash(f"Categoría «{cat['nombre']}» eliminada.", "ok")
            return redirect(url_for("categorias_view"))
        if not cantidad:
            return redirect(url_for("categorias_view"))
        return render_template("categoria_eliminar.html", cat=cat, cantidad=cantidad, destinos=destinos)

    # ------------------------------------------------------------ informes

    @app.route("/informes")
    def informes():
        hoy = date.today()
        vista = request.args.get("vista", "mensual")
        anios = [int(f[0]) for f in get_db().execute(
            "SELECT DISTINCT substr(fecha, 1, 4) FROM movimientos ORDER BY 1")]
        anios = sorted(set(anios) | {hoy.year})

        if vista == "semanal":
            texto = request.args.get("mes", "")
            try:
                inicio = datetime.strptime(texto, "%Y-%m").date()
            except ValueError:
                inicio = hoy.replace(day=1)
            fin = fin_de_mes(inicio)
            diarios = get_db().execute(
                """SELECT fecha, tipo, SUM(importe_cent) AS total FROM movimientos
                   WHERE fecha BETWEEN ? AND ? GROUP BY fecha, tipo""",
                (inicio.isoformat(), fin.isoformat()),
            ).fetchall()
            filas = []
            for n, (desde, hasta) in enumerate(semanas_del_mes(inicio.year, inicio.month), 1):
                ing = sum(d["total"] for d in diarios if d["tipo"] == "ingreso" and desde.isoformat() <= d["fecha"] <= hasta.isoformat())
                gas = sum(d["total"] for d in diarios if d["tipo"] == "gasto" and desde.isoformat() <= d["fecha"] <= hasta.isoformat())
                filas.append({
                    "etiqueta": f"Semana {n}", "detalle": f"{desde:%d/%m} – {hasta:%d/%m}",
                    "corta": f"S{n}", "desde": desde, "hasta": hasta,
                    "ingresos": ing, "gastos": gas, "saldo": ing - gas,
                    "actual": desde <= hoy <= hasta,
                })
            titulo = f"{MESES[inicio.month - 1]} {inicio.year}"
            anterior = {"vista": "semanal", "mes": sumar_meses(inicio, -1).strftime("%Y-%m")}
            siguiente = {"vista": "semanal", "mes": sumar_meses(inicio, 1).strftime("%Y-%m")}
            seleccion = inicio.strftime("%Y-%m")
        else:
            vista = "mensual"
            anio = request.args.get("anio", hoy.year, type=int)
            anio = min(max(anio, 1900), 2200)
            inicio, fin = date(anio, 1, 1), date(anio, 12, 31)
            mensuales = get_db().execute(
                """SELECT CAST(substr(fecha, 6, 2) AS INTEGER) AS mes, tipo, SUM(importe_cent) AS total
                   FROM movimientos WHERE fecha BETWEEN ? AND ? GROUP BY mes, tipo""",
                (inicio.isoformat(), fin.isoformat()),
            ).fetchall()
            filas = []
            for mes in range(1, 13):
                ing = sum(m["total"] for m in mensuales if m["mes"] == mes and m["tipo"] == "ingreso")
                gas = sum(m["total"] for m in mensuales if m["mes"] == mes and m["tipo"] == "gasto")
                desde = date(anio, mes, 1)
                filas.append({
                    "etiqueta": MESES[mes - 1], "detalle": "", "corta": MESES_CORTOS[mes - 1],
                    "desde": desde, "hasta": fin_de_mes(desde),
                    "ingresos": ing, "gastos": gas, "saldo": ing - gas,
                    "actual": anio == hoy.year and mes == hoy.month,
                    "mes": desde.strftime("%Y-%m"),
                })
            titulo = str(anio)
            anterior = {"vista": "mensual", "anio": anio - 1}
            siguiente = {"vista": "mensual", "anio": anio + 1}
            seleccion = anio

        total = {
            "ingresos": sum(f["ingresos"] for f in filas),
            "gastos": sum(f["gastos"] for f in filas),
        }
        total["saldo"] = total["ingresos"] - total["gastos"]
        con_datos = [f for f in filas if f["ingresos"] or f["gastos"]]
        total["promedio_ingresos"] = total["ingresos"] // len(con_datos) if con_datos else 0
        total["promedio_gastos"] = total["gastos"] // len(con_datos) if con_datos else 0
        mejor = max(con_datos, key=lambda f: f["saldo"]) if con_datos else None
        maximo = max([max(f["ingresos"], f["gastos"]) for f in filas] + [1])

        return render_template(
            "informes.html", vista=vista, filas=filas, total=total, maximo=maximo, mejor=mejor,
            titulo=titulo, anterior=anterior, siguiente=siguiente, seleccion=seleccion, anios=anios,
            desde=inicio, hasta=fin, categorias_periodo=por_categoria(inicio, fin),
        )

    # ------------------------------------------------------------ ajustes

    @app.route("/ajustes", methods=["GET", "POST"])
    def ajustes():
        errores = {}
        if request.method == "POST":
            nombre = " ".join(request.form.get("nombre_negocio", "").split())[:60]
            simbolo = request.form.get("simbolo", "").strip()[:5]
            formato = request.form.get("separadores", "")
            if not nombre:
                errores["nombre_negocio"] = "Escribe el nombre de tu negocio."
            if formato not in ("coma_punto", "punto_coma"):
                errores["separadores"] = "Elige un formato."
            if not errores:
                database.guardar_ajuste("nombre_negocio", nombre)
                database.guardar_ajuste("simbolo", simbolo)
                database.guardar_ajuste("separadores", formato)
                flash("Ajustes guardados.", "ok")
                return redirect(url_for("ajustes"))
        return render_template(
            "ajustes.html", errores=errores, copias=listar_copias(app.config["COPIAS_DIR"]),
            estadisticas=sumas(),
        ), (400 if errores else 200)

    @app.route("/ajustes/contrasena", methods=["POST"])
    def cambiar_contrasena():
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        if not check_password_hash(g.ajustes["password_hash"], actual):
            flash("La contraseña actual no es correcta.", "error")
        elif len(nueva) < 6:
            flash("La nueva contraseña debe tener al menos 6 caracteres.", "error")
        elif nueva != request.form.get("nueva2", ""):
            flash("Las contraseñas nuevas no coinciden.", "error")
        else:
            database.guardar_ajuste("password_hash", generate_password_hash(nueva))
            flash("Contraseña actualizada.", "ok")
        return redirect(url_for("ajustes") + "#seguridad")

    @app.route("/ajustes/copia")
    def descargar_copia():
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            database.copiar(app.config["DATABASE"], tmp)
            with open(tmp, "rb") as f:
                contenido = f.read()
        finally:
            os.remove(tmp)
        nombre = f"copia-finanzas-{datetime.now():%Y-%m-%d-%H%M}.db"
        return send_file(io.BytesIO(contenido), as_attachment=True, download_name=nombre,
                         mimetype="application/octet-stream")

    @app.route("/ajustes/copias/<nombre>")
    def descargar_copia_guardada(nombre):
        if not re.fullmatch(r"[\w.-]+\.db", nombre):
            abort(404)
        ruta = os.path.join(app.config["COPIAS_DIR"], nombre)
        if not os.path.isfile(ruta):
            abort(404)
        with open(ruta, "rb") as f:
            contenido = f.read()
        return send_file(io.BytesIO(contenido), as_attachment=True, download_name=nombre,
                         mimetype="application/octet-stream")

    @app.route("/ajustes/restaurar", methods=["POST"])
    def restaurar_copia():
        archivo = request.files.get("archivo")
        if not archivo or not archivo.filename:
            flash("Selecciona el archivo de la copia de seguridad.", "error")
            return redirect(url_for("ajustes") + "#copias")
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            archivo.save(tmp)
            error = database.validar_copia(tmp)
            if error:
                flash(error, "error")
                return redirect(url_for("ajustes") + "#copias")
            # Antes de reemplazar, se guarda una copia del estado actual.
            previa = os.path.join(app.config["COPIAS_DIR"], f"antes-de-restaurar-{datetime.now():%Y-%m-%d-%H%M%S}.db")
            database.copiar(app.config["DATABASE"], previa)
            clave = g.ajustes["password_hash"]
            database.close_db()
            database.copiar(tmp, app.config["DATABASE"])
            database.init_db(app.config["DATABASE"])
            database.guardar_ajuste("password_hash", clave)  # se mantiene la contraseña actual
        finally:
            os.remove(tmp)
        flash("Copia de seguridad restaurada correctamente. Se guardó una copia del estado anterior.", "ok")
        return redirect(url_for("resumen"))


# ====================================================================== arranque

def ip_local():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None



# Create the Flask app at the top level so Vercel can detect it
app = create_app()


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    puerto = int(os.environ.get("PORT", "5000"))
    local = f"http://localhost:{puerto}"

    print("\n  ==============================================")
    print("   Gestión de Ingresos y Gastos")
    print("  ==============================================")
    print(f"   En este equipo:          {local}")

    ip = ip_local()
    if ip and host == "0.0.0.0":
        print(f"   Desde el móvil o tableta: http://{ip}:{puerto}")
        print("   (conectados a la misma red Wi-Fi)")

    print("\n   No cierres esta ventana mientras uses el sistema.")
    print("  ==============================================\n")

    if os.environ.get("ABRIR_NAVEGADOR", "1") == "1":
        threading.Timer(
            1.5, webbrowser.open, args=(local,)
        ).start()

    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=puerto)
    else:
        serve(app, host=host, port=puerto, threads=8)


if __name__ == "__main__":
    main()



