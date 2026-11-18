"""Exportación a Excel (hojas Facturas, Revisar y Resumen), CSV y JSON."""

from __future__ import annotations

import csv
import json
import logging
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import cuit as cuit_util
from .modelo import ESTADO_OK, Factura

log = logging.getLogger(__name__)

# (clave, título, tipo de dato: texto | fecha | importe | cuit)
COLUMNAS = [
    ("archivo", "Archivo", "texto"),
    ("comprobante", "Comprobante", "texto"),
    ("tipo", "Tipo", "texto"),
    ("punto_venta", "Punto de venta", "texto"),
    ("numero", "Número", "texto"),
    ("fecha", "Fecha", "fecha"),
    ("cuit_emisor", "CUIT emisor", "cuit"),
    ("razon_social_emisor", "Razón social emisor", "texto"),
    ("cuit_receptor", "CUIT receptor", "cuit"),
    ("razon_social_receptor", "Razón social receptor", "texto"),
    ("neto_gravado", "Neto gravado", "importe"),
    ("no_gravado", "No gravado", "importe"),
    ("exento", "Exento", "importe"),
    ("iva_21", "IVA 21%", "importe"),
    ("iva_10_5", "IVA 10,5%", "importe"),
    ("iva_27", "IVA 27%", "importe"),
    ("iva_otros", "IVA otros", "importe"),
    ("percepciones", "Percepciones", "importe"),
    ("total", "Total", "importe"),
    ("cae", "CAE", "texto"),
    ("vencimiento_cae", "Vto. CAE", "fecha"),
    ("origen", "Origen", "texto"),
]
COLUMNAS_REVISAR = [("estado", "Estado", "texto"), ("observaciones", "Observaciones", "texto")] + COLUMNAS

FORMATO_IMPORTE = "#,##0.00"
FORMATO_FECHA = "DD/MM/YYYY"


def _valor_celda(factura: Factura, clave: str, tipo: str):
    valor = getattr(factura, clave)
    if clave == "observaciones":
        return " | ".join(valor)
    if tipo == "importe":
        return float(valor) if isinstance(valor, Decimal) else valor
    if tipo == "cuit":
        return cuit_util.formatear(valor) if valor else ""
    return valor


def _escribir_hoja(hoja, facturas: list[Factura], columnas) -> None:
    encabezado = Font(bold=True, color="FFFFFF")
    relleno = PatternFill("solid", fgColor="1F4E78")
    hoja.append([titulo for _, titulo, _ in columnas])
    for celda in hoja[1]:
        celda.font, celda.fill = encabezado, relleno
        celda.alignment = Alignment(vertical="center")
    for factura in facturas:
        hoja.append([_valor_celda(factura, clave, tipo) for clave, _, tipo in columnas])

    for indice, (clave, titulo, tipo) in enumerate(columnas, start=1):
        letra = get_column_letter(indice)
        for celda in hoja[letra][1:]:
            if tipo == "importe":
                celda.number_format = FORMATO_IMPORTE
            elif tipo == "fecha":
                celda.number_format = FORMATO_FECHA
        ancho = max([len(titulo)] + [len(str(c.value or "")) for c in hoja[letra][1:]])
        hoja.column_dimensions[letra].width = min(max(ancho + 2, 10), 60)
    hoja.freeze_panes = "A2"
    if facturas:
        hoja.auto_filter.ref = hoja.dimensions


def exportar_excel(facturas: list[Factura], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ok = [f for f in facturas if f.estado == ESTADO_OK]
    dudosas = [f for f in facturas if f.estado != ESTADO_OK]

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Facturas"
    _escribir_hoja(hoja, ok, COLUMNAS)
    _escribir_hoja(libro.create_sheet("Revisar"), dudosas, COLUMNAS_REVISAR)

    resumen = libro.create_sheet("Resumen")
    resumen.append(["Concepto", "Valor"])
    for celda in resumen[1]:
        celda.font = Font(bold=True)
    filas = [
        ("Facturas OK", len(ok)),
        ("Para revisar / con error", len(dudosas)),
        ("Neto gravado (OK)", float(sum((f.neto_gravado for f in ok), Decimal(0)))),
        ("IVA total (OK)", float(sum((f.iva_total for f in ok), Decimal(0)))),
        ("Percepciones (OK)", float(sum((f.percepciones for f in ok), Decimal(0)))),
        ("Total facturado (OK)", float(sum((f.total or Decimal(0) for f in ok), Decimal(0)))),
    ]
    for fila in filas:
        resumen.append(list(fila))
    for celda in resumen["B"][3:]:
        celda.number_format = FORMATO_IMPORTE
    resumen.column_dimensions["A"].width = 28
    resumen.column_dimensions["B"].width = 18

    libro.save(ruta)
    log.info("Excel guardado: %s (%d OK, %d para revisar)", ruta, len(ok), len(dudosas))
    return ruta


def exportar_csv(facturas: list[Factura], ruta: str | Path, separador: str = ";") -> Path:
    """CSV con todas las facturas (incluye estado y observaciones). UTF-8 con BOM para que Excel lo abra bien."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo, delimiter=separador)
        escritor.writerow([clave for clave, _, _ in COLUMNAS_REVISAR])
        for f in facturas:
            fila = []
            for clave, _, tipo in COLUMNAS_REVISAR:
                valor = _valor_celda(f, clave, tipo)
                if hasattr(valor, "isoformat"):
                    valor = valor.isoformat()
                elif isinstance(valor, float):
                    valor = f"{valor:.2f}"
                fila.append("" if valor is None else valor)
            escritor.writerow(fila)
    log.info("CSV guardado: %s", ruta)
    return ruta


def exportar_json(facturas: list[Factura], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps([f.a_dict() for f in facturas], ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("JSON guardado: %s", ruta)
    return ruta
