"""Envío de facturas a una API/ERP por webhook (POST JSON con reintentos)."""

from __future__ import annotations

import logging
import time
from typing import Callable

import httpx

from .modelo import Factura

log = logging.getLogger(__name__)

ESTADOS_REINTENTABLES = {408, 425, 429, 500, 502, 503, 504}


class EnviadorWebhook:
    def __init__(
        self,
        url: str,
        token: str = "",
        reintentos: int = 3,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        espera: Callable[[float], None] = time.sleep,
        demora_base: float = 1.0,
    ):
        self.url = url
        self.token = token
        self.reintentos = max(1, reintentos)
        self.espera = espera
        self.demora_base = demora_base
        self._cliente = httpx.Client(timeout=timeout, transport=transport)

    @classmethod
    def desde_config(cls, config, transport: httpx.BaseTransport | None = None) -> "EnviadorWebhook | None":
        if not config.webhook_url:
            return None
        return cls(
            url=config.webhook_url,
            token=config.webhook_token,
            reintentos=config.webhook_reintentos,
            timeout=config.webhook_timeout,
            transport=transport,
        )

    def enviar(self, factura: Factura) -> bool:
        """Devuelve True si el ERP respondió 2xx. Nunca lanza excepción (se loguea el error)."""
        encabezados = {"Content-Type": "application/json", "Idempotency-Key": factura.hash or factura.clave}
        if self.token:
            encabezados["Authorization"] = f"Bearer {self.token}"
        for intento in range(1, self.reintentos + 1):
            try:
                resp = self._cliente.post(self.url, json=factura.a_dict(), headers=encabezados)
            except httpx.TransportError as exc:
                motivo = f"error de conexión: {exc}"
            else:
                if 200 <= resp.status_code < 300:
                    log.info("Webhook: %s enviada (HTTP %d)", factura.numero_completo or factura.archivo, resp.status_code)
                    return True
                motivo = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if resp.status_code not in ESTADOS_REINTENTABLES:
                    log.error("Webhook: el ERP rechazó %s (%s). No se reintenta.", factura.archivo, motivo)
                    return False
            if intento < self.reintentos:
                demora = self.demora_base * 2 ** (intento - 1)
                log.warning("Webhook: intento %d/%d falló (%s). Reintento en %ss", intento, self.reintentos, motivo, demora)
                self.espera(demora)
        log.error("Webhook: no se pudo enviar %s después de %d intentos", factura.archivo, self.reintentos)
        return False

    def cerrar(self) -> None:
        self._cliente.close()
