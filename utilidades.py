"""Funciones auxiliares: importes, fechas y períodos."""
import re
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

PERIODOS = [
    ("todo", "Todo"),
    ("hoy", "Hoy"),
    ("semana", "Esta semana"),
    ("semana_anterior", "Semana anterior"),
    ("mes", "Este mes"),
    ("mes_anterior", "Mes anterior"),
    ("anio", "Este año"),
    ("personalizado", "Personalizado"),
]

IMPORTE_MAXIMO = Decimal("999999999.99")


# ---------------------------------------------------------------- importes

def separadores(formato):
    """Devuelve (separador de miles, separador decimal)."""
    return (".", ",") if formato == "punto_coma" else (",", ".")


def parse_importe(texto, formato="coma_punto"):
    """Convierte un texto como ``1,234.50`` o ``1.234,50`` a céntimos (int).

    Lanza ``ValueError`` con un mensaje claro si el importe no es válido.
    """
    t = re.sub(r"[^\d,.\-]", "", (texto or "").strip())
    if not t or not any(c.isdigit() for c in t):
        raise ValueError("Introduce un importe.")
    if "-" in t:
        raise ValueError("El importe debe ser mayor que cero.")

    miles, decimal = separadores(formato)
    if "," in t and "." in t:
        # El último separador que aparece es el decimal.
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t or "." in t:
        sep = "," if "," in t else "."
        grupos = t.split(sep)
        es_miles = len(grupos) > 1 and all(len(gr) == 3 for gr in grupos[1:]) and grupos[0] != ""
        if sep == miles and es_miles:
            t = t.replace(sep, "")
        elif len(grupos) == 2:
            t = t.replace(sep, ".")
        elif es_miles:
            t = t.replace(sep, "")
        else:
            raise ValueError("El formato del importe no es válido.")

    try:
        valor = Decimal(t)
    except InvalidOperation:
        raise ValueError("El formato del importe no es válido.") from None
    if valor <= 0:
        raise ValueError("El importe debe ser mayor que cero.")
    if valor.as_tuple().exponent < -2 and valor != valor.quantize(Decimal("0.01")):
        raise ValueError("El importe solo puede tener 2 decimales.")
    if valor > IMPORTE_MAXIMO:
        raise ValueError("El importe es demasiado grande.")
    return int((valor * 100).to_integral_value())


def formato_dinero(centimos, simbolo="$", formato="coma_punto", signo=False):
    centimos = int(centimos or 0)
    miles, decimal = separadores(formato)
    entero, dec = divmod(abs(centimos), 100)
    numero = f"{entero:,}".replace(",", miles) + f"{decimal}{dec:02d}"
    prefijo = "-" if centimos < 0 else ("+" if signo and centimos > 0 else "")
    return f"{prefijo}{simbolo}{numero}"


def importe_para_formulario(centimos, formato="coma_punto"):
    """Importe en texto editable, sin separador de miles (p. ej. ``1234.50``)."""
    _, decimal = separadores(formato)
    entero, dec = divmod(int(centimos), 100)
    return f"{entero}{decimal}{dec:02d}"


# ---------------------------------------------------------------- fechas

def parse_fecha(texto):
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def fecha_corta(valor):
    """``2026-10-13`` → ``13/10/2026``."""
    d = parse_fecha(valor) if isinstance(valor, str) else valor
    return d.strftime("%d/%m/%Y") if d else ""


def fin_de_mes(d):
    return d.replace(day=monthrange(d.year, d.month)[1])


def sumar_meses(d, meses):
    total = d.year * 12 + (d.month - 1) + meses
    return date(total // 12, total % 12 + 1, 1)


def rango_periodo(periodo, hoy=None):
    """Devuelve (desde, hasta) para un período predefinido, o (None, None)."""
    hoy = hoy or date.today()
    if periodo == "hoy":
        return hoy, hoy
    if periodo == "semana":
        inicio = hoy - timedelta(days=hoy.weekday())
        return inicio, inicio + timedelta(days=6)
    if periodo == "semana_anterior":
        inicio = hoy - timedelta(days=hoy.weekday() + 7)
        return inicio, inicio + timedelta(days=6)
    if periodo == "mes":
        inicio = hoy.replace(day=1)
        return inicio, fin_de_mes(inicio)
    if periodo == "mes_anterior":
        inicio = sumar_meses(hoy.replace(day=1), -1)
        return inicio, fin_de_mes(inicio)
    if periodo == "anio":
        return date(hoy.year, 1, 1), date(hoy.year, 12, 31)
    return None, None


def semanas_del_mes(anio, mes):
    """Semanas (lunes a domingo) de un mes, recortadas a los límites del mes.

    Así la suma de las semanas coincide exactamente con el total del mes.
    """
    inicio = date(anio, mes, 1)
    fin = fin_de_mes(inicio)
    semanas = []
    actual = inicio
    while actual <= fin:
        fin_semana = min(actual + timedelta(days=6 - actual.weekday()), fin)
        semanas.append((actual, fin_semana))
        actual = fin_semana + timedelta(days=1)
    return semanas


# ---------------------------------------------------------------- iconos SVG

ICONOS = {
    "inicio": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
    "lista": '<path d="M9 6h12M9 12h12M9 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    "grafico": '<path d="M3 3v18h18"/><path d="M8 17v-5"/><path d="M13 17V8"/><path d="M18 17v-9"/>',
    "etiqueta": '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
    "ajustes": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "salir": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "mas": '<path d="M12 5v14M5 12h14"/>',
    "ingreso": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "gasto": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "cartera": '<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3"/><path d="M21 8h-6a3 3 0 0 0 0 6h6z"/><path d="M15.5 11h.01"/>',
    "editar": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "eliminar": '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    "buscar": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "descargar": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
    "subir": '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/>',
    "imprimir": '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6z"/>',
    "anterior": '<path d="m15 18-6-6 6-6"/>',
    "siguiente": '<path d="m9 18 6-6-6-6"/>',
    "menu": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "cerrar": '<path d="M18 6 6 18M6 6l12 12"/>',
    "filtro": '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    "escudo": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "candado": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "calendario": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "alerta": '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>',
    "archivo": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
}
