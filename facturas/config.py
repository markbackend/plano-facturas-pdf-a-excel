"""Configuración leída de variables de entorno (y de un archivo .env si existe)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv es opcional
    load_dotenv = None


def _bool(valor: str | None, defecto: bool) -> bool:
    if valor is None or valor.strip() == "":
        return defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


@dataclass
class Config:
    anthropic_api_key: str = ""
    anthropic_modelo: str = "claude-haiku-5-5"
    anthropic_url: str = "https://api.anthropic.com"
    ia_habilitada: bool = True
    ia_timeout: float = 60.0
    ia_max_tokens: int = 1500
    ia_reintentos: int = 3
    registro_path: Path = Path("datos/registro.json")
    carpeta_procesadas: Path | None = None  # por defecto: <entrada>/procesadas
    carpeta_errores: Path | None = None  # por defecto: <entrada>/errores
    tolerancia_suma: Decimal = Decimal("0.05")
    webhook_url: str = ""
    webhook_token: str = ""
    webhook_reintentos: int = 3
    webhook_timeout: float = 15.0
    webhook_enviar_revisar: bool = False
    csv_separador: str = ";"
    intervalo_vigilar: float = 10.0
    log_nivel: str = "INFO"

    @classmethod
    def desde_entorno(cls, archivo_env: str | Path | None = ".env") -> "Config":
        if load_dotenv and archivo_env and Path(archivo_env).exists():
            load_dotenv(archivo_env, override=False)
        e = os.environ.get

        def ruta(nombre: str) -> Path | None:
            valor = e(nombre, "").strip()
            return Path(valor) if valor else None

        return cls(
            anthropic_api_key=e("ANTHROPIC_API_KEY", "").strip(),
            anthropic_modelo=e("ANTHROPIC_MODELO", "").strip() or cls.anthropic_modelo,
            anthropic_url=(e("ANTHROPIC_URL", "").strip() or cls.anthropic_url).rstrip("/"),
            ia_habilitada=_bool(e("IA_HABILITADA"), True),
            ia_timeout=float(e("IA_TIMEOUT", "60")),
            ia_max_tokens=int(e("IA_MAX_TOKENS", "1500")),
            ia_reintentos=int(e("IA_REINTENTOS", "3")),
            registro_path=ruta("REGISTRO_PATH") or cls.registro_path,
            carpeta_procesadas=ruta("CARPETA_PROCESADAS"),
            carpeta_errores=ruta("CARPETA_ERRORES"),
            tolerancia_suma=Decimal(e("TOLERANCIA_SUMA", "0.05")),
            webhook_url=e("WEBHOOK_URL", "").strip(),
            webhook_token=e("WEBHOOK_TOKEN", "").strip(),
            webhook_reintentos=int(e("WEBHOOK_REINTENTOS", "3")),
            webhook_timeout=float(e("WEBHOOK_TIMEOUT", "15")),
            webhook_enviar_revisar=_bool(e("WEBHOOK_ENVIAR_REVISAR"), False),
            csv_separador=e("CSV_SEPARADOR", ";") or ";",
            intervalo_vigilar=float(e("INTERVALO_VIGILAR", "10")),
            log_nivel=(e("LOG_NIVEL", "INFO") or "INFO").upper(),
        )
