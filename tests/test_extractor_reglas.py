from decimal import Decimal

import pytest

from facturas.ejemplos import FACTURA_A, FACTURA_B, crear_factura_pdf, variante
from facturas.extractor_reglas import ErrorLectura, extraer_de_texto, extraer_pdf, leer_texto_pdf
from facturas.validaciones import campos_faltantes, validar

CAMPOS = [
    "tipo",
    "punto_venta",
    "numero",
    "fecha",
    "cuit_emisor",
    "razon_social_emisor",
    "cuit_receptor",
    "razon_social_receptor",
    "neto_gravado",
    "iva_21",
    "iva_10_5",
    "iva_27",
    "percepciones",
    "total",
    "cae",
    "vencimiento_cae",
]


@pytest.mark.parametrize(
    "archivo", ["factura_A_el_sol.pdf", "factura_B_los_andes.pdf", "factura_C_perez.pdf", "factura_A_error_suma.pdf"]
)
def test_extrae_todos_los_campos(set_ejemplo, archivo):
    carpeta, esperados = set_ejemplo
    factura, _ = extraer_pdf(carpeta / archivo)
    esperado = esperados[archivo]
    for campo in CAMPOS:
        assert getattr(factura, campo) == esperado[campo], campo


def test_factura_a_valida_y_sin_contar_copias(set_ejemplo):
    carpeta, _ = set_ejemplo
    texto = leer_texto_pdf(carpeta / "factura_A_el_sol.pdf")
    # El PDF tiene ORIGINAL, DUPLICADO y TRIPLICADO: solo se usa el original
    assert "DUPLICADO" not in texto and texto.count("Importe Total") == 1
    factura = extraer_de_texto(texto)
    assert factura.comprobante == "FACTURA" and factura.codigo == "001"
    assert factura.iva_21 == Decimal("11550.00") and factura.iva_10_5 == Decimal("2520.00")
    assert factura.percepciones == Decimal("2500.00")
    assert validar(factura) == []


@pytest.mark.parametrize("archivo", ["factura_B_los_andes.pdf", "factura_C_perez.pdf"])
def test_b_y_c_validas(set_ejemplo, archivo):
    carpeta, _ = set_ejemplo
    factura, _ = extraer_pdf(carpeta / archivo)
    assert factura.iva_total == 0
    assert validar(factura) == []


def test_error_de_suma_se_detecta(set_ejemplo):
    carpeta, _ = set_ejemplo
    factura, _ = extraer_pdf(carpeta / "factura_A_error_suma.pdf")
    problemas = validar(factura)
    assert len(problemas) == 1 and "La suma no da" in problemas[0] and "1000.00" in problemas[0]


def test_escaneada_no_tiene_texto(set_ejemplo):
    carpeta, _ = set_ejemplo
    factura, texto = extraer_pdf(carpeta / "factura_escaneada.pdf")
    assert texto.strip() == ""
    assert "total" in campos_faltantes(factura)


def test_archivo_roto_lanza_error_de_lectura(set_ejemplo):
    carpeta, _ = set_ejemplo
    with pytest.raises(ErrorLectura):
        leer_texto_pdf(carpeta / "archivo_roto.pdf")


def test_cuit_emisor_invalido(tmp_path):
    datos = variante(FACTURA_A, emisor={**FACTURA_A["emisor"], "cuit": "30712345672"}, copias=["ORIGINAL"])
    crear_factura_pdf(tmp_path / "f.pdf", datos)
    factura, _ = extraer_pdf(tmp_path / "f.pdf")
    assert any("CUIT emisor inválido" in p for p in validar(factura))


def test_numero_con_columnas_mezcladas(tmp_path):
    datos = variante(FACTURA_B, formato_numero="mezclado")
    crear_factura_pdf(tmp_path / "f.pdf", datos)
    factura, _ = extraer_pdf(tmp_path / "f.pdf")
    assert (factura.punto_venta, factura.numero) == ("00007", "00045678")


def test_texto_con_formatos_alternativos():
    texto = """FACTURA B
N° 0004-00000123
Fecha Emisión: 01/02/2026
Razón Social: KIOSCO LA ESQUINA Domicilio: Calle 1
C.U.I.T.: 30-71234567-1
Señores: CONSUMIDOR FINAL
Subtotal: $ 1.210,00
Percepción IIBB: $ 10,00
Percepción IVA: $ 5,00
TOTAL: $ 1.225,00
CAE: 76123456789012 Vencimiento CAE: 11/02/2026"""
    f = extraer_de_texto(texto)
    assert (f.tipo, f.punto_venta, f.numero) == ("B", "00004", "00000123")
    assert f.razon_social_emisor == "KIOSCO LA ESQUINA"
    assert f.razon_social_receptor == "CONSUMIDOR FINAL"
    assert f.percepciones == Decimal("15.00") and f.total == Decimal("1225.00")
    assert validar(f) == []
