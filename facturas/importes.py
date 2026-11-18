"""Conversión de importes y fechas en formato argentino."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CENTAVOS = Decimal("0.01")


def parse_importe(valor: str | int | float | Decimal | None) -> Decimal | None:
    """Convierte '$ 1.234.567,89', '1234567.89', '1.500' o 1500 a Decimal con 2 decimales.

    Reglas: si hay punto y coma, el último que aparece es el separador decimal. Si solo hay coma,
    es decimal (formato argentino). Si solo hay puntos y forman grupos de 3 ('1.500'), son miles.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor)).quantize(CENTAVOS)

    texto = str(valor).strip().replace("$", "").replace(" ", "").replace(" ", "")
    negativo = False
    if texto.startswith("(") and texto.endswith(")"):
        negativo, texto = True, texto[1:-1]
    if texto.startswith("-"):
        negativo, texto = True, texto[1:]
    if not texto or not re.fullmatch(r"[\d.,]+", texto) or not re.search(r"\d", texto):
        return None

    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        if texto.count(",") > 1:
            return None
        texto = texto.replace(",", ".")
    elif "." in texto:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
            texto = texto.replace(".", "")
        elif texto.count(".") > 1:
            return None

    try:
        numero = Decimal(texto).quantize(CENTAVOS)
    except InvalidOperation:
        return None
    return -numero if negativo else numero


def formatear_importe(valor: Decimal | int | float) -> str:
    """Decimal('1234.5') -> '1.234,50' (formato argentino)."""
    numero = Decimal(str(valor)).quantize(CENTAVOS)
    signo = "-" if numero < 0 else ""
    entero, decimales = f"{abs(numero):.2f}".split(".")
    con_miles = f"{int(entero):,}".replace(",", ".")
    return f"{signo}{con_miles},{decimales}"


def parse_fecha(valor: str | date | None) -> date | None:
    """Acepta 'dd/mm/aaaa', 'dd-mm-aaaa', 'aaaa-mm-dd' o un date."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None
