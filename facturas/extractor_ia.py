"""Respaldo con IA: manda el PDF a la API de Anthropic (Claude) por httpx y valida el JSON que vuelve.

Solo se usa para los PDF que las reglas no entienden (escaneados o con formato raro).
Sin ANTHROPIC_API_KEY no se llama a nada y la factura queda para revisar.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Callable

import httpx

from . import cuit as cuit_util
from .importes import parse_fecha, parse_importe
from .modelo import CAMPOS_IMPORTE, CODIGOS_AFIP, Factura

log = logging.getLogger(__name__)

VERSION_API = "2023-06-01"
MAX_BYTES_PDF = 30 * 1024 * 1024
ESTADOS_REINTENTABLES = {408, 409, 429, 500, 502, 503, 504, 529}

SISTEMA = (
    "Sos un extractor de datos de facturas electrónicas argentinas (AFIP). "
    "Respondés SOLO con un objeto JSON válido, sin texto antes ni después y sin bloques de código. "
    "Si un dato no figura en el documento, usá null. No inventes datos."
)

INSTRUCCION = """Extraé estos campos de la factura adjunta y devolvé un JSON con exactamente estas claves:
{
  "comprobante": "FACTURA" | "NOTA DE CREDITO" | "NOTA DE DEBITO",
  "tipo": "A" | "B" | "C" | "M",
  "codigo": "código AFIP de 3 dígitos, ej. 001",
  "punto_venta": "5 dígitos",
  "numero": "8 dígitos",
  "fecha": "AAAA-MM-DD (fecha de emisión)",
  "cuit_emisor": "11 dígitos sin guiones",
  "razon_social_emisor": "texto",
  "cuit_receptor": "11 dígitos sin guiones o null",
  "razon_social_receptor": "texto o null",
  "neto_gravado": número (en B y C: el subtotal),
  "no_gravado": número,
  "exento": número,
  "iva_21": número,
  "iva_10_5": número,
  "iva_27": número,
  "iva_otros": número (IVA 5% y 2,5%),
  "percepciones": número (importe otros tributos / percepciones),
  "total": número,
  "cae": "14 dígitos",
  "vencimiento_cae": "AAAA-MM-DD"
}
Los importes van como número con punto decimal (ej. 1234.56), sin símbolo $ ni separador de miles.
Si el PDF tiene ORIGINAL, DUPLICADO y TRIPLICADO, usá solo una copia."""


class ErrorIA(Exception):
    """La IA no respondió o devolvió algo que no se pudo validar."""


def extraer_json(texto: str) -> dict:
    """Saca el objeto JSON de la respuesta (tolera ```json ... ``` y texto alrededor)."""
    limpio = re.sub(r"```(?:json)?", "", texto).strip()
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ErrorIA("La respuesta de la IA no contiene un objeto JSON")
    try:
        datos = json.loads(limpio[inicio : fin + 1])
    except json.JSONDecodeError as exc:
        raise ErrorIA(f"JSON inválido en la respuesta de la IA: {exc}") from exc
    if not isinstance(datos, dict):
        raise ErrorIA("La IA no devolvió un objeto JSON")
    return datos


def _texto(valor) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def factura_desde_ia(datos: dict) -> Factura:
    """Valida y normaliza el JSON de la IA. Lanza ErrorIA si los tipos no tienen sentido."""
    f = Factura(origen="ia")

    tipo = _texto(datos.get("tipo")).upper()
    if tipo and tipo not in ("A", "B", "C", "M"):
        raise ErrorIA(f"Tipo de factura inválido devuelto por la IA: {tipo!r}")
    f.tipo = tipo

    codigo = re.sub(r"\D", "", _texto(datos.get("codigo")))
    if codigo:
        f.codigo = codigo.zfill(3)
        if int(codigo) in CODIGOS_AFIP and not f.tipo:
            f.tipo = CODIGOS_AFIP[int(codigo)][1]
    comprobante = _texto(datos.get("comprobante")).upper().replace("É", "E")
    f.comprobante = comprobante or ("FACTURA" if f.tipo else "")

    pv = re.sub(r"\D", "", _texto(datos.get("punto_venta")))
    numero = re.sub(r"\D", "", _texto(datos.get("numero")))
    if len(pv) > 5 or len(numero) > 8:
        raise ErrorIA(f"Punto de venta o número con demasiados dígitos: {pv}-{numero}")
    f.punto_venta = pv.zfill(5) if pv else ""
    f.numero = numero.zfill(8) if numero else ""

    for campo in ("fecha", "vencimiento_cae"):
        crudo = datos.get(campo)
        valor = parse_fecha(crudo) if crudo else None
        if crudo and valor is None:
            raise ErrorIA(f"Fecha inválida en {campo}: {crudo!r}")
        setattr(f, campo, valor)

    f.cuit_emisor = cuit_util.normalizar(datos.get("cuit_emisor"))
    f.cuit_receptor = cuit_util.normalizar(datos.get("cuit_receptor"))
    f.razon_social_emisor = _texto(datos.get("razon_social_emisor"))
    f.razon_social_receptor = _texto(datos.get("razon_social_receptor"))
    f.cae = re.sub(r"\D", "", _texto(datos.get("cae")))

    for campo in CAMPOS_IMPORTE:
        crudo = datos.get(campo)
        if crudo is None or crudo == "":
            continue
        valor = parse_importe(crudo)
        if valor is None:
            raise ErrorIA(f"Importe inválido en {campo}: {crudo!r}")
        setattr(f, campo, valor)
    return f


class ExtractorIA:
    """Cliente mínimo de la API de Mensajes de Anthropic."""

    def __init__(
        self,
        api_key: str,
        modelo: str = "claude-haiku-5-5",
        url_base: str = "https://api.anthropic.com",
        timeout: float = 60.0,
        max_tokens: int = 1500,
        reintentos: int = 3,
        transport: httpx.BaseTransport | None = None,
        espera: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key
        self.modelo = modelo
        self.url = url_base.rstrip("/") + "/v1/messages"
        self.max_tokens = max_tokens
        self.reintentos = max(1, reintentos)
        self.espera = espera
        self._cliente = httpx.Client(timeout=timeout, transport=transport)

    @classmethod
    def desde_config(cls, config, transport: httpx.BaseTransport | None = None) -> "ExtractorIA":
        return cls(
            api_key=config.anthropic_api_key if config.ia_habilitada else "",
            modelo=config.anthropic_modelo,
            url_base=config.anthropic_url,
            timeout=config.ia_timeout,
            max_tokens=config.ia_max_tokens,
            reintentos=config.ia_reintentos,
            transport=transport,
        )

    @property
    def habilitado(self) -> bool:
        return bool(self.api_key)

    def _post(self, cuerpo: dict) -> dict:
        encabezados = {
            "x-api-key": self.api_key,
            "anthropic-version": VERSION_API,
            "content-type": "application/json",
        }
        ultimo_error = ""
        for intento in range(1, self.reintentos + 1):
            try:
                resp = self._cliente.post(self.url, json=cuerpo, headers=encabezados)
            except httpx.TransportError as exc:
                ultimo_error = f"error de conexión: {exc}"
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise ErrorIA("La API devolvió una respuesta que no es JSON") from exc
                ultimo_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in ESTADOS_REINTENTABLES:
                    raise ErrorIA(ultimo_error)
            if intento < self.reintentos:
                demora = 2 ** (intento - 1)
                log.warning("IA: intento %d/%d falló (%s). Reintento en %ss", intento, self.reintentos, ultimo_error, demora)
                self.espera(demora)
        raise ErrorIA(f"La API no respondió después de {self.reintentos} intentos ({ultimo_error})")

    def extraer(self, ruta_pdf: str | Path, texto_pdf: str = "") -> Factura:
        if not self.habilitado:
            raise ErrorIA("IA no configurada (falta ANTHROPIC_API_KEY)")
        ruta = Path(ruta_pdf)
        contenido_pdf = ruta.read_bytes()
        if len(contenido_pdf) > MAX_BYTES_PDF:
            raise ErrorIA(f"El PDF pesa {len(contenido_pdf) // 1024 // 1024} MB, el máximo es 30 MB")

        instruccion = INSTRUCCION
        if texto_pdf.strip():
            instruccion += "\n\nTexto extraído del PDF (puede estar desordenado):\n" + texto_pdf[:6000]
        cuerpo = {
            "model": self.modelo,
            "max_tokens": self.max_tokens,
            "system": SISTEMA,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": base64.b64encode(contenido_pdf).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": instruccion},
                    ],
                }
            ],
        }
        log.info("IA: enviando %s al modelo %s", ruta.name, self.modelo)
        respuesta = self._post(cuerpo)
        if respuesta.get("stop_reason") == "max_tokens":
            raise ErrorIA("La respuesta de la IA quedó cortada (subir IA_MAX_TOKENS)")
        texto = "".join(b.get("text", "") for b in respuesta.get("content", []) if b.get("type") == "text")
        if not texto.strip():
            raise ErrorIA("La IA devolvió una respuesta vacía")
        return factura_desde_ia(extraer_json(texto))

    def cerrar(self) -> None:
        self._cliente.close()
