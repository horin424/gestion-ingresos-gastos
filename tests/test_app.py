"""Pruebas automáticas. Ejecutar con:  python -m pytest"""
import io
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from utilidades import formato_dinero, parse_importe, rango_periodo, semanas_del_mes  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "CSRF": False,
        "SECRET_KEY": "pruebas",
        "DATOS_DIR": str(tmp_path),
        "DATABASE": str(tmp_path / "finanzas.db"),
        "COPIAS_DIR": str(tmp_path / "copias"),
    })


@pytest.fixture
def client(app):
    c = app.test_client()
    c.post("/configuracion-inicial", data={"nombre_negocio": "Tienda", "password": "secreta1", "password2": "secreta1"})
    return c


def categoria_id(client, nombre):
    with client.application.app_context():
        from database import get_db
        return get_db().execute("SELECT id FROM categorias WHERE nombre = ?", (nombre,)).fetchone()[0]


def nuevo(client, tipo, importe, fecha, categoria, descripcion=""):
    return client.post("/movimientos/nuevo", data={
        "tipo": tipo, "importe": importe, "fecha": fecha,
        "categoria_id": categoria_id(client, categoria), "descripcion": descripcion,
    })


# ------------------------------------------------------------------ utilidades

@pytest.mark.parametrize("texto, formato, esperado", [
    ("100", "coma_punto", 10000),
    ("0.10", "coma_punto", 10),
    ("1,234.56", "coma_punto", 123456),
    ("1,500", "coma_punto", 150000),
    ("12,5", "coma_punto", 1250),
    ("$ 99.99", "coma_punto", 9999),
    ("1.234,56", "punto_coma", 123456),
    ("1.500", "punto_coma", 150000),
    ("12,50", "punto_coma", 1250),
    ("0.1", "coma_punto", 10),
])
def test_parse_importe(texto, formato, esperado):
    assert parse_importe(texto, formato) == esperado


@pytest.mark.parametrize("texto", ["", "abc", "-5", "0", "1.234", "1.2.3,4.5", "1.999", "9999999999"])
def test_parse_importe_invalido(texto):
    if texto in ("1.234", "1.999"):
        # Con formato 1,234.56 un punto es decimal: 3 decimales no son válidos.
        with pytest.raises(ValueError):
            parse_importe(texto, "coma_punto")
        return
    with pytest.raises(ValueError):
        parse_importe(texto)


def test_formato_dinero():
    assert formato_dinero(123456) == "$1,234.56"
    assert formato_dinero(-5, "€", "punto_coma") == "-€0,05"
    assert formato_dinero(100000000, "$") == "$1,000,000.00"
    assert formato_dinero(500, signo=True) == "+$5.00"


def test_sumas_exactas_sin_errores_de_redondeo():
    # 0.1 + 0.2 en coma flotante da 0.30000000000000004; en céntimos es exacto.
    assert parse_importe("0.1") + parse_importe("0.2") == parse_importe("0.3")


def test_semanas_cubren_todo_el_mes():
    semanas = semanas_del_mes(2026, 10)
    assert semanas[0][0] == date(2026, 10, 1)
    assert semanas[-1][1] == date(2026, 10, 31)
    for (_, fin), (inicio, _) in zip(semanas, semanas[1:]):
        assert inicio == fin + timedelta(days=1)
    assert all(s[0].weekday() == 0 for s in semanas[1:])


def test_rango_periodo():
    hoy = date(2026, 10, 15)  # jueves
    assert rango_periodo("semana", hoy) == (date(2026, 10, 12), date(2026, 10, 18))
    assert rango_periodo("mes", hoy) == (date(2026, 10, 1), date(2026, 10, 31))
    assert rango_periodo("mes_anterior", date(2026, 1, 10)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert rango_periodo("todo", hoy) == (None, None)


# ------------------------------------------------------------------ acceso

def test_requiere_configuracion_y_login(app):
    c = app.test_client()
    assert c.get("/").headers["Location"].endswith("/configuracion-inicial")
    c.post("/configuracion-inicial", data={"nombre_negocio": "X", "password": "secreta1", "password2": "secreta1"})
    c.post("/salir")
    assert "/login" in c.get("/movimientos").headers["Location"]
    assert "field-error" not in c.get("/login").get_data(as_text=True)
    mala = c.post("/login", data={"password": "mala"})
    assert mala.status_code == 200 and "Contraseña incorrecta" in mala.get_data(as_text=True)
    assert c.post("/login", data={"password": "secreta1"}).status_code == 302
    assert c.get("/").status_code == 200


def test_csrf_bloquea_formularios_sin_token(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "x", "DATOS_DIR": str(tmp_path),
                      "DATABASE": str(tmp_path / "f.db"), "COPIAS_DIR": str(tmp_path / "c")})
    c = app.test_client()
    r = c.post("/configuracion-inicial", data={"nombre_negocio": "X", "password": "secreta1", "password2": "secreta1"})
    assert r.status_code == 400


def test_redireccion_externa_bloqueada(client):
    client.post("/salir")
    r = client.post("/login?next=//sitio-malicioso.com", data={"password": "secreta1"})
    assert r.headers["Location"] == "/"


# ------------------------------------------------------------------ movimientos

def test_crear_editar_eliminar(client):
    hoy = date.today().isoformat()
    r = nuevo(client, "ingreso", "1500.50", hoy, "Ventas", "Venta mostrador")
    assert r.status_code == 302
    pagina = client.get("/movimientos").get_data(as_text=True)
    assert "Venta mostrador" in pagina and "$1,500.50" in pagina

    with client.application.app_context():
        from database import get_db
        mov_id = get_db().execute("SELECT id FROM movimientos").fetchone()[0]

    r = client.post(f"/movimientos/{mov_id}/editar", data={
        "tipo": "ingreso", "importe": "2000", "fecha": hoy,
        "categoria_id": categoria_id(client, "Ventas"), "descripcion": "Corregido",
    })
    assert r.status_code == 302
    pagina = client.get("/movimientos").get_data(as_text=True)
    assert "Corregido" in pagina and "$2,000.00" in pagina

    assert client.post(f"/movimientos/{mov_id}/eliminar").status_code == 302
    assert "Corregido" not in client.get("/movimientos").get_data(as_text=True)
    assert client.post("/movimientos/9999/eliminar").status_code == 404


def test_validaciones_del_formulario(client):
    hoy = date.today().isoformat()
    assert nuevo(client, "ingreso", "-10", hoy, "Ventas").status_code == 400
    assert nuevo(client, "ingreso", "10", "fecha-mala", "Ventas").status_code == 400
    # "Compras" solo admite gastos.
    r = nuevo(client, "ingreso", "10", hoy, "Compras")
    assert r.status_code == 400 and "no admite" in r.get_data(as_text=True)
    assert client.get("/movimientos").get_data(as_text=True).count('class="mov-row"') == 0


def test_resumen_calcula_saldo(client):
    hoy = date.today().isoformat()
    nuevo(client, "ingreso", "1000", hoy, "Ventas")
    nuevo(client, "ingreso", "250.25", hoy, "Servicios")
    nuevo(client, "gasto", "300.10", hoy, "Compras")
    nuevo(client, "gasto", "49.90", "2020-01-15", "Transporte")
    pagina = client.get("/").get_data(as_text=True)
    assert "$1,250.25" in pagina   # ingresos
    assert "$350.00" in pagina     # gastos
    assert "$900.25" in pagina     # saldo


def test_filtros(client):
    nuevo(client, "ingreso", "100", "2026-03-10", "Ventas", "marzo")
    nuevo(client, "gasto", "40", "2026-03-20", "Transporte", "taxi")
    nuevo(client, "gasto", "60", "2026-04-05", "Compras", "abril")

    def filas(**params):
        return client.get("/movimientos", query_string=params).get_data(as_text=True).count('class="mov-row"')

    assert filas() == 3
    assert filas(periodo="personalizado", desde="2026-03-01", hasta="2026-03-31") == 2
    assert filas(tipo="gasto") == 2
    assert filas(categoria=categoria_id(client, "Transporte")) == 1
    assert filas(q="tax") == 1
    assert filas(q="%") == 0
    # Fechas invertidas se corrigen automáticamente.
    assert filas(periodo="personalizado", desde="2026-03-31", hasta="2026-03-01") == 2


def test_informes(client):
    nuevo(client, "ingreso", "1000", "2025-10-01", "Ventas")   # miércoles, semana 1
    nuevo(client, "gasto", "200", "2025-10-06", "Compras")     # lunes, semana 2
    nuevo(client, "ingreso", "500", "2025-11-03", "Ventas")
    mensual = client.get("/informes?vista=mensual&anio=2025").get_data(as_text=True)
    assert "$1,500.00" in mensual and "$200.00" in mensual and "+$1,300.00" in mensual
    semanal = client.get("/informes?vista=semanal&mes=2025-10").get_data(as_text=True)
    assert "Octubre 2025" in semanal
    assert "01/10 – 05/10" in semanal and "06/10 – 12/10" in semanal
    assert "+$800.00" in semanal
    assert client.get("/informes?vista=semanal&mes=basura").status_code == 200
    assert client.get("/informes?anio=abc").status_code == 200


def test_exportar_csv(client):
    nuevo(client, "gasto", "12.5", "2026-05-01", "Compras", "Papel, tinta")
    r = client.get("/movimientos/exportar")
    texto = r.data.decode("utf-8-sig")
    assert r.mimetype == "text/csv"
    assert '"Papel, tinta"' in texto and "-12.50" in texto


# ------------------------------------------------------------------ categorías

def test_categorias(client):
    assert client.post("/categorias", data={"nombre": "Alquiler", "tipo": "gasto", "color": "#9333ea"}).status_code == 302
    assert client.post("/categorias", data={"nombre": "alquiler", "tipo": "gasto"}).status_code == 400  # duplicada
    nuevo(client, "gasto", "800", "2026-01-01", "Alquiler")
    alquiler = categoria_id(client, "Alquiler")
    # No se puede limitar a ingresos si ya tiene gastos.
    assert client.post(f"/categorias/{alquiler}/editar", data={"nombre": "Alquiler", "tipo": "ingreso"}).status_code == 400
    # Eliminar moviendo los movimientos a otra categoría.
    otros = categoria_id(client, "Otros")
    assert client.post(f"/categorias/{alquiler}/eliminar", data={"mover_a": otros}).status_code == 302
    with client.application.app_context():
        from database import get_db
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM categorias WHERE nombre = 'Alquiler'").fetchone()[0] == 0
        assert db.execute("SELECT categoria_id FROM movimientos").fetchone()[0] == otros


# ------------------------------------------------------------------ copias de seguridad

def test_copia_y_restauracion(client, app):
    nuevo(client, "ingreso", "777", "2026-02-02", "Ventas", "antes de la copia")
    copia = client.get("/ajustes/copia")
    assert copia.status_code == 200 and copia.data[:16] == b"SQLite format 3\x00"

    nuevo(client, "ingreso", "1", "2026-02-03", "Ventas", "después de la copia")
    client.post("/ajustes/contrasena", data={"actual": "secreta1", "nueva": "nueva123", "nueva2": "nueva123"})

    r = client.post("/ajustes/restaurar", data={"archivo": (io.BytesIO(copia.data), "copia.db")},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    pagina = client.get("/movimientos").get_data(as_text=True)
    assert "antes de la copia" in pagina and "después de la copia" not in pagina
    # La contraseña actual se conserva tras restaurar.
    client.post("/salir")
    assert client.post("/login", data={"password": "nueva123"}).status_code == 302
    # Se guardó el estado anterior.
    assert any(n.startswith("antes-de-restaurar") for n in os.listdir(app.config["COPIAS_DIR"]))


def test_restaurar_archivo_invalido(client):
    nuevo(client, "ingreso", "5", "2026-02-02", "Ventas", "dato seguro")
    r = client.post("/ajustes/restaurar", data={"archivo": (io.BytesIO(b"no soy una base de datos"), "x.db")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "no es una copia de seguridad válida" in r.get_data(as_text=True)
    assert "dato seguro" in client.get("/movimientos").get_data(as_text=True)


def test_copia_automatica_diaria(client, app):
    client.get("/")
    assert f"auto-{date.today().isoformat()}.db" in os.listdir(app.config["COPIAS_DIR"])


def test_todas_las_paginas_cargan(client):
    nuevo(client, "ingreso", "10", date.today().isoformat(), "Ventas")
    for url in ["/", "/movimientos", "/movimientos/nuevo", "/movimientos/1/editar", "/categorias",
                f"/categorias/{categoria_id(client, 'Ventas')}/editar", "/informes", "/informes?vista=semanal",
                "/ajustes", "/movimientos?periodo=semana", "/movimientos?periodo=mes_anterior"]:
        assert client.get(url).status_code == 200, url
    assert client.get("/no-existe").status_code == 404
