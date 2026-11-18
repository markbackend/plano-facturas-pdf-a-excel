"""Extracción por reglas (pdfplumber + expresiones regulares) de facturas electrónicas AFIP."""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from pathlib import Path

import pdfplumber

from . import cuit as cuit_util
from .importes import parse_fecha, parse_importe
from .modelo import CODIGOS_AFIP, Factura

log = logging.getLogger(__name__)


class ErrorLectura(Exception):
    """El archivo no se pudo abrir como PDF."""


# Páginas que son copias (AFIP genera ORIGINAL / DUPLICADO / TRIPLICADO en el mismo PDF)
RE_COPIA = re.compile(r"^\s*(DUPLICADO|TRIPLICADO|CUADRUPLICADO)\s*$", re.M | re.I)

FLAGS = re.I
# Solo espacios horizontales: el importe tiene que estar en la misma línea que la etiqueta
IMPORTE = r"[ \t]*:?[ \t]*\$?[ \t]*(\(?-?\d[\d.,]*\)?)"
FECHA = r"(\d{2}[/-]\d{2}[/-]\d{4})"

RE_CODIGO = re.compile(r"C[OÓ]D(?:IGO)?\.?\s*(?:N[°ºo]\.?)?\s*:?\s*0*(\d{1,3})\b", FLAGS)
RE_LETRA_FACTURA = re.compile(r"\b(?:FACTURA|NOTA\s+DE\s+CR[EÉ]DITO|NOTA\s+DE\s+D[EÉ]BITO)\s+([ABCM])\b", FLAGS)
RE_LETRA_SOLA = re.compile(r"^\s*([ABCM])\s*$", re.M)
RE_COMPROBANTE = re.compile(r"\b(FACTURA|NOTA\s+DE\s+CR[EÉ]DITO|NOTA\s+DE\s+D[EÉ]BITO)\b", FLAGS)

RE_NUMERO = [
    # "Punto de Venta: 00003 Comp. Nro: 00001234"
    re.compile(
        r"Punto\s+de\s+Venta\s*:?\s*(\d{1,5})\s+Comp(?:robante)?\.?\s*N(?:ro|[°º]|úmero|umero)\.?\s*:?\s*(\d{1,8})",
        FLAGS,
    ),
    # "Punto de Venta: Comp. Nro: 00003 00001234" (columnas mezcladas al extraer)
    re.compile(
        r"Punto\s+de\s+Venta\s*:?\s*Comp(?:robante)?\.?\s*N(?:ro|[°º]|úmero|umero)\.?\s*:?\s*(\d{1,5})\s+(\d{1,8})",
        FLAGS,
    ),
    # "N° 0003-00001234"
    re.compile(r"N(?:ro|[°º])\.?\s*:?\s*(\d{4,5})\s*-\s*(\d{8})\b", FLAGS),
]
RE_FECHA_EMISION = re.compile(r"Fecha\s+(?:de\s+)?Emisi[oó]n\s*:?\s*" + FECHA, FLAGS)
RE_CUIT = re.compile(r"C\.?U\.?I\.?T\.?\s*(?:N[°º]\.?)?\s*:?\s*(\d{2}-?\d{8}-?\d)\b", FLAGS)
RE_RAZON_RECEPTOR = re.compile(
    r"(?:Apellido\s+y\s+Nombre\s*/\s*Raz[oó]n\s+Social|Se[ñn]or(?:es)?|Cliente)\s*:\s*(.+)", FLAGS
)
RE_RAZON = re.compile(r"Raz[oó]n\s+Social\s*:\s*(.+)", FLAGS)
RE_CORTE = re.compile(
    r"\s+(?:Fecha\s+de|C\.?U\.?I\.?T|Domicilio|Punto\s+de\s+Venta|Comp\.?\s*Nro|Condici[oó]n|"
    r"Ingresos\s+Brutos|DNI|Apellido\s+y\s+Nombre)\b.*$",
    FLAGS,
)
RE_CAE = re.compile(r"\bC\.?A\.?E\.?\s*(?:N[°ºo]\.?)?\s*:?\s*(\d{14})\b", FLAGS)
RE_VTO_CAE = re.compile(
    r"(?:Fecha\s+de\s+)?V(?:to|encimiento)\.?\s*(?:de(?:l)?\s+)?C\.?A\.?E\.?\s*:?\s*" + FECHA, FLAGS
)

ETIQUETAS_IMPORTE = {
    "neto_gravado": [r"(?:Importe\s+)?Neto\s+Gravado", r"Subtotal"],
    "no_gravado": [r"(?:Importe\s+)?No\s+Gravado"],
    "exento": [r"(?:Importe\s+)?Exento"],
    "iva_27": [r"IVA\s*27(?:[.,]0+)?\s*%"],
    "iva_21": [r"IVA\s*21(?:[.,]0+)?\s*%"],
    "iva_10_5": [r"IVA\s*10[.,]5\s*%"],
    "iva_otros": [r"IVA\s*(?:2[.,]5|5)(?:[.,]0+)?\s*%"],
    "total": [r"Importe\s+Total", r"\bTOTAL"],
}
RE_OTROS_TRIBUTOS = re.compile(r"Importe\s+Otros\s+Tributos" + IMPORTE, FLAGS)
RE_PERCEPCION = re.compile(r"Percepci[oó]n[^\n$:]*" + IMPORTE, FLAGS)


def leer_texto_pdf(ruta: str | Path) -> str:
    """Devuelve el texto del PDF (sin las páginas DUPLICADO/TRIPLICADO). Puede ser '' si es escaneado."""
    try:
        with pdfplumber.open(str(ruta)) as pdf:
            textos = [(pagina.extract_text() or "") for pagina in pdf.pages]
    except Exception as exc:  # pdfplumber/pdfminer lanzan varios tipos distintos
        raise ErrorLectura(f"No se pudo abrir el PDF: {type(exc).__name__}: {exc}") from exc
    if not textos:
        raise ErrorLectura("El PDF no tiene páginas")
    originales = [t for t in textos if not RE_COPIA.search(t)]
    return "\n".join(originales or textos)


def _ultimo_importe(texto: str, etiquetas: list[str]) -> Decimal | None:
    """Busca la última aparición de cada etiqueta (el bloque de totales suele estar al final)."""
    for etiqueta in etiquetas:
        coincidencias = re.findall(etiqueta + IMPORTE, texto, FLAGS)
        for crudo in reversed(coincidencias):
            valor = parse_importe(crudo)
            if valor is not None:
                return valor
    return None


def _limpiar_razon(valor: str) -> str:
    return RE_CORTE.sub("", valor).strip(" :-\t")


def extraer_de_texto(texto: str) -> Factura:
    """Aplica las reglas sobre el texto. No valida: solo completa lo que encuentra."""
    f = Factura()

    # Tipo y código de comprobante
    m = RE_CODIGO.search(texto)
    if m and int(m.group(1)) in CODIGOS_AFIP:
        codigo = int(m.group(1))
        f.comprobante, f.tipo = CODIGOS_AFIP[codigo]
        f.codigo = f"{codigo:03d}"
    else:
        m = RE_LETRA_FACTURA.search(texto) or RE_LETRA_SOLA.search(texto)
        if m:
            f.tipo = m.group(1).upper()
        m = RE_COMPROBANTE.search(texto)
        if m:
            f.comprobante = re.sub(r"\s+", " ", m.group(1).upper()).replace("É", "E")

    # Punto de venta y número
    for patron in RE_NUMERO:
        m = patron.search(texto)
        if m:
            f.punto_venta = m.group(1).zfill(5)
            f.numero = m.group(2).zfill(8)
            break

    m = RE_FECHA_EMISION.search(texto)
    if m:
        f.fecha = parse_fecha(m.group(1))

    # CUIT: el primero que aparece es el del emisor, el siguiente distinto es el del receptor
    cuits: list[str] = []
    for crudo in RE_CUIT.findall(texto):
        numero = cuit_util.normalizar(crudo)
        if numero not in cuits:
            cuits.append(numero)
    if cuits:
        f.cuit_emisor = cuits[0]
    if len(cuits) > 1:
        f.cuit_receptor = cuits[1]

    # Razón social
    m = RE_RAZON_RECEPTOR.search(texto)
    if m:
        f.razon_social_receptor = _limpiar_razon(m.group(1))
    for linea in texto.splitlines():
        if re.search(r"Apellido\s+y\s+Nombre", linea, FLAGS):
            continue
        m = RE_RAZON.search(linea)
        if m:
            f.razon_social_emisor = _limpiar_razon(m.group(1))
            break

    # Importes
    for campo, etiquetas in ETIQUETAS_IMPORTE.items():
        valor = _ultimo_importe(texto, etiquetas)
        if valor is not None:
            setattr(f, campo, valor)

    m = RE_OTROS_TRIBUTOS.findall(texto)
    if m:
        f.percepciones = parse_importe(m[-1]) or Decimal("0.00")
    else:
        f.percepciones = sum(
            (parse_importe(v) or Decimal("0.00") for v in RE_PERCEPCION.findall(texto)), Decimal("0.00")
        )

    # CAE
    m = RE_CAE.search(texto)
    if m:
        f.cae = m.group(1)
    m = RE_VTO_CAE.search(texto)
    if m:
        f.vencimiento_cae = parse_fecha(m.group(1))

    log.debug("Reglas extrajeron %s", f.numero_completo or "(sin número)")
    return f


def extraer_pdf(ruta: str | Path) -> tuple[Factura, str]:
    """Lee el PDF y aplica las reglas. Devuelve (factura, texto)."""
    texto = leer_texto_pdf(ruta)
    return extraer_de_texto(texto) if texto.strip() else Factura(), texto
