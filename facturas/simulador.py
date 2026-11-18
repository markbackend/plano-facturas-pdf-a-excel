"""Transportes httpx falsos para la demo y las pruebas: simulan la API de Anthropic y un ERP.

No hacen ninguna conexión a internet.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx

from .ejemplos import FACTURA_C, calcular, variante


def _serializable(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def respuesta_anthropic(texto: str, stop_reason: str = "end_turn") -> dict:
    """Arma una respuesta con el formato de la API de Mensajes."""
    return {
        "id": "msg_simulado",
        "type": "message",
        "role": "assistant",
        "model": "simulado",
        "content": [{"type": "text", "text": texto}],
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def datos_factura_escaneada() -> dict:
    """Lo que 'leería' la IA de la factura escaneada del set de ejemplo."""
    valores = calcular(variante(FACTURA_C, numero=88))
    datos = {k: _serializable(v) for k, v in valores.items()}
    datos.update({"comprobante": "FACTURA", "codigo": "011", "no_gravado": 0, "exento": 0, "iva_otros": 0})
    return datos


def transporte_ia_simulada(datos: dict | None = None, registro: list | None = None) -> httpx.MockTransport:
    """Simula la API de Anthropic: siempre devuelve `datos` como JSON (por defecto, la factura escaneada)."""
    datos = datos or datos_factura_escaneada()

    def manejar(request: httpx.Request) -> httpx.Response:
        if registro is not None:
            registro.append(request)
        if not request.headers.get("x-api-key"):
            return httpx.Response(401, json={"type": "error", "error": {"type": "authentication_error"}})
        return httpx.Response(200, json=respuesta_anthropic(json.dumps(datos, ensure_ascii=False)))

    return httpx.MockTransport(manejar)


def transporte_erp_simulado(recibidas: list) -> httpx.MockTransport:
    """Simula un ERP que acepta todo y guarda lo recibido en `recibidas`."""

    def manejar(request: httpx.Request) -> httpx.Response:
        recibidas.append(json.loads(request.content))
        return httpx.Response(201, json={"ok": True, "id": len(recibidas)})

    return httpx.MockTransport(manejar)
