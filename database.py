"""Acceso a la base de datos SQLite.

Los importes se guardan como números enteros en céntimos (``importe_cent``)
para que las sumas sean exactas y no haya errores de redondeo.
"""
import sqlite3

from flask import current_app, g

ESQUEMA = """
CREATE TABLE IF NOT EXISTS categorias (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    tipo    TEXT    NOT NULL CHECK (tipo IN ('ingreso', 'gasto', 'ambos')),
    color   TEXT    NOT NULL DEFAULT '#64748b'
);

CREATE TABLE IF NOT EXISTS movimientos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo           TEXT    NOT NULL CHECK (tipo IN ('ingreso', 'gasto')),
    importe_cent   INTEGER NOT NULL CHECK (importe_cent > 0),
    fecha          TEXT    NOT NULL,
    categoria_id   INTEGER NOT NULL REFERENCES categorias (id) ON DELETE RESTRICT,
    descripcion    TEXT    NOT NULL DEFAULT '',
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    actualizado_en TEXT
);

CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos (fecha);
CREATE INDEX IF NOT EXISTS idx_movimientos_categoria ON movimientos (categoria_id);

CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""

CATEGORIAS_INICIALES = [
    ("Ventas", "ingreso", "#059669"),
    ("Servicios", "ambos", "#0891b2"),
    ("Compras", "gasto", "#dc2626"),
    ("Transporte", "gasto", "#d97706"),
    ("Otros", "ambos", "#64748b"),
]

AJUSTES_POR_DEFECTO = {
    "nombre_negocio": "Mi Negocio",
    "simbolo": "$",
    "separadores": "coma_punto",
}

TABLAS_REQUERIDAS = {
    "movimientos": {"id", "tipo", "importe_cent", "fecha", "categoria_id", "descripcion"},
    "categorias": {"id", "nombre", "tipo", "color"},
    "ajustes": {"clave", "valor"},
}


def conectar(ruta):
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(ruta):
    """Crea las tablas si no existen y carga los datos iniciales la primera vez."""
    conn = conectar(ruta)
    try:
        with conn:
            conn.executescript(ESQUEMA)
            inicializada = conn.execute(
                "SELECT 1 FROM ajustes WHERE clave = 'inicializada'"
            ).fetchone()
            if not inicializada:
                conn.executemany(
                    "INSERT OR IGNORE INTO categorias (nombre, tipo, color) VALUES (?, ?, ?)",
                    CATEGORIAS_INICIALES,
                )
                for clave, valor in AJUSTES_POR_DEFECTO.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO ajustes (clave, valor) VALUES (?, ?)",
                        (clave, valor),
                    )
                conn.execute("INSERT INTO ajustes (clave, valor) VALUES ('inicializada', '1')")
    finally:
        conn.close()


def leer_ajustes():
    filas = get_db().execute("SELECT clave, valor FROM ajustes").fetchall()
    ajustes = dict(AJUSTES_POR_DEFECTO)
    ajustes.update({f["clave"]: f["valor"] for f in filas})
    return ajustes


def guardar_ajuste(clave, valor, db=None):
    db = db or get_db()
    with db:
        db.execute(
            "INSERT INTO ajustes (clave, valor) VALUES (?, ?) "
            "ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor",
            (clave, valor),
        )


def copiar(origen, destino):
    """Copia una base de datos de forma segura (aunque esté en uso)."""
    src = sqlite3.connect(origen)
    dst = sqlite3.connect(destino)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def validar_copia(ruta):
    """Comprueba que un archivo sea una copia válida de este sistema.

    Devuelve un mensaje de error o ``None`` si todo es correcto.
    """
    try:
        with open(ruta, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                return "El archivo no es una copia de seguridad válida."
        conn = sqlite3.connect(ruta)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "La copia de seguridad está dañada."
            for tabla, columnas in TABLAS_REQUERIDAS.items():
                existentes = {c[1] for c in conn.execute(f"PRAGMA table_info({tabla})")}
                if not columnas <= existentes:
                    return "El archivo no pertenece a este sistema."
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return "El archivo no es una copia de seguridad válida."
    return None
