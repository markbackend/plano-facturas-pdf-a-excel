from datetime import date
from decimal import Decimal

import pytest

from facturas import cuit
from facturas.importes import formatear_importe, parse_fecha, parse_importe


@pytest.mark.parametrize("numero", ["30712345671", "30-71234567-1", "20-12345678-6", "27331234562", "33701112224"])
def test_cuit_validos(numero):
    assert cuit.es_valido(numero)


@pytest.mark.parametrize("numero", ["30712345672", "3071234567", "", None, "abc", "30-71234567-0"])
def test_cuit_invalidos(numero):
    assert not cuit.es_valido(numero)


def test_cuit_formatear_y_armar():
    assert cuit.formatear("30712345671") == "30-71234567-1"
    assert cuit.armar("30", "71234567") == "30712345671"


def test_digito_verificador_11_da_cero():
    # Busca un cuerpo cuyo resto dé 11 -> dígito 0
    for cuerpo in range(10000000, 10000200):
        base = f"20{cuerpo}"
        if cuit.digito_verificador(base) == 0:
            assert cuit.es_valido(base + "0")
            return
    pytest.fail("no se encontró ejemplo")


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("$ 1.234.567,89", Decimal("1234567.89")),
        ("1234567.89", Decimal("1234567.89")),
        ("1,234,567.89", Decimal("1234567.89")),
        ("1.500", Decimal("1500.00")),
        ("15.5", Decimal("15.50")),
        ("0,00", Decimal("0.00")),
        ("-2.500,00", Decimal("-2500.00")),
        ("(100,00)", Decimal("-100.00")),
        (1500, Decimal("1500.00")),
        (99.9, Decimal("99.90")),
    ],
)
def test_parse_importe(texto, esperado):
    assert parse_importe(texto) == esperado


@pytest.mark.parametrize("texto", ["", "abc", "1,2,3", None, "$"])
def test_parse_importe_invalido(texto):
    assert parse_importe(texto) is None


def test_formatear_importe():
    assert formatear_importe(Decimal("1234567.5")) == "1.234.567,50"
    assert formatear_importe(Decimal("-10")) == "-10,00"


def test_parse_fecha():
    assert parse_fecha("15/10/2026") == date(2026, 10, 15)
    assert parse_fecha("2026-10-15") == date(2026, 10, 15)
    assert parse_fecha("32/13/2026") is None
