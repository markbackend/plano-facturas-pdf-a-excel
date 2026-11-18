"""Controles sobre una factura ya extraída: campos obligatorios, CUIT, sumas, CAE."""

from __future__ import annotations

from decimal import Decimal

from . import cuit as cuit_util
from .modelo import Factura

CAMPOS_OBLIGATORIOS = {
    "tipo": "tipo (A/B/C)",
    "punto_venta": "punto de venta",
    "numero": "número",
    "fecha": "fecha",
    "cuit_emisor": "CUIT emisor",
    "total": "total",
}


def campos_faltantes(f: Factura) -> list[str]:
    """Campos imprescindibles que no se pudieron leer (si falta alguno, se prueba con IA)."""
    return [nombre for campo, nombre in CAMPOS_OBLIGATORIOS.items() if not getattr(f, campo)]


def validar(f: Factura, tolerancia: Decimal = Decimal("0.05")) -> list[str]:
    """Devuelve la lista de problemas. Lista vacía = factura OK."""
    problemas: list[str] = []

    faltan = campos_faltantes(f)
    if faltan:
        problemas.append("Faltan datos: " + ", ".join(faltan))

    if f.cuit_emisor and not cuit_util.es_valido(f.cuit_emisor):
        problemas.append(f"CUIT emisor inválido (dígito verificador): {cuit_util.formatear(f.cuit_emisor)}")
    if f.cuit_receptor and not cuit_util.es_valido(f.cuit_receptor):
        problemas.append(f"CUIT receptor inválido (dígito verificador): {cuit_util.formatear(f.cuit_receptor)}")
    if f.tipo == "A" and not f.cuit_receptor:
        problemas.append("Factura A sin CUIT del receptor")

    if f.tipo == "A" and f.neto_gravado > 0 and f.iva_total == 0:
        problemas.append("Factura A con neto gravado pero sin IVA discriminado")
    if f.tipo in ("B", "C") and f.iva_total > 0:
        problemas.append(f"Factura {f.tipo} con IVA discriminado (revisar tipo)")

    if f.total is not None:
        suma = f.neto_gravado + f.no_gravado + f.exento + f.iva_total + f.percepciones
        diferencia = (f.total - suma).copy_abs()
        if diferencia > tolerancia:
            problemas.append(
                f"La suma no da: neto + impuestos = {suma:.2f} pero el total es {f.total:.2f} "
                f"(diferencia {diferencia:.2f})"
            )
        if f.total <= 0 and f.comprobante == "FACTURA":
            problemas.append("Total cero o negativo")

    if not f.cae:
        problemas.append("Falta el CAE")
    elif len(f.cae) != 14 or not f.cae.isdigit():
        problemas.append(f"CAE con formato inválido: {f.cae}")
    if f.cae and not f.vencimiento_cae:
        problemas.append("Falta la fecha de vencimiento del CAE")
    if f.fecha and f.vencimiento_cae and f.vencimiento_cae < f.fecha:
        problemas.append("El vencimiento del CAE es anterior a la fecha de emisión")

    return problemas
