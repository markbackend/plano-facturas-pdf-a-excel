"""Validación de CUIT/CUIL argentinos (dígito verificador módulo 11)."""

from __future__ import annotations

import re

PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def normalizar(cuit: str | int | None) -> str:
    """Deja solo los dígitos: '30-71234567-1' -> '30712345671'."""
    if cuit is None:
        return ""
    return re.sub(r"\D", "", str(cuit))


def digito_verificador(primeros_diez: str) -> int | None:
    """Calcula el dígito verificador. Devuelve None si el resultado es 10 (combinación inválida)."""
    if len(primeros_diez) != 10 or not primeros_diez.isdigit():
        raise ValueError(f"Se esperaban 10 dígitos, llegó: {primeros_diez!r}")
    suma = sum(int(d) * p for d, p in zip(primeros_diez, PESOS))
    resto = 11 - (suma % 11)
    if resto == 11:
        return 0
    if resto == 10:
        return None
    return resto


def es_valido(cuit: str | int | None) -> bool:
    """True si tiene 11 dígitos y el dígito verificador es correcto."""
    numero = normalizar(cuit)
    if len(numero) != 11:
        return False
    dv = digito_verificador(numero[:10])
    return dv is not None and dv == int(numero[10])


def formatear(cuit: str | int | None) -> str:
    """'30712345671' -> '30-71234567-1' (si no tiene 11 dígitos lo devuelve tal cual)."""
    numero = normalizar(cuit)
    if len(numero) != 11:
        return numero
    return f"{numero[:2]}-{numero[2:10]}-{numero[10]}"


def armar(prefijo: str, cuerpo: str) -> str:
    """Arma un CUIT válido a partir del prefijo (20, 27, 30...) y los 8 dígitos del medio."""
    base = f"{prefijo}{cuerpo}"
    dv = digito_verificador(base)
    if dv is None:
        raise ValueError(f"La combinación {prefijo}-{cuerpo} no admite dígito verificador válido")
    return f"{base}{dv}"
