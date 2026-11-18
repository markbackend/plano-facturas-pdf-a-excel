import json
from decimal import Decimal

import httpx
import pytest

from facturas.extractor_ia import ErrorIA, ExtractorIA, extraer_json, factura_desde_ia
from facturas.simulador import datos_factura_escaneada, respuesta_anthropic, transporte_ia_simulada
from facturas.validaciones import validar


def _ia(transport, **kwargs) -> ExtractorIA:
    esperas: list[float] = []
    ia = ExtractorIA(api_key="clave-de-prueba", modelo="modelo-x", transport=transport, espera=esperas.append, **kwargs)
    ia.esperas = esperas
    return ia


def test_envia_pdf_y_valida_respuesta(set_ejemplo):
    carpeta, _ = set_ejemplo
    pedidos: list[httpx.Request] = []
    ia = _ia(transporte_ia_simulada(registro=pedidos))
    factura = ia.extraer(carpeta / "factura_escaneada.pdf")

    assert factura.origen == "ia"
    assert factura.numero_completo == "C-00001-00000088"
    assert factura.total == Decimal("150000.00")
    assert validar(factura) == []

    pedido = pedidos[0]
    assert str(pedido.url) == "https://api.anthropic.com/v1/messages"
    assert pedido.headers["x-api-key"] == "clave-de-prueba"
    assert pedido.headers["anthropic-version"] == "2023-06-01"
    cuerpo = json.loads(pedido.content)
    assert cuerpo["model"] == "modelo-x"
    bloque = cuerpo["messages"][0]["content"][0]
    assert bloque["type"] == "document" and bloque["source"]["media_type"] == "application/pdf"


def test_modelo_por_defecto():
    assert ExtractorIA(api_key="x").modelo == "claude-haiku-5-5"


def test_sin_clave_no_esta_habilitado(set_ejemplo):
    carpeta, _ = set_ejemplo
    ia = ExtractorIA(api_key="")
    assert not ia.habilitado
    with pytest.raises(ErrorIA, match="no configurada"):
        ia.extraer(carpeta / "factura_escaneada.pdf")


def test_reintenta_si_la_api_esta_sobrecargada(set_ejemplo):
    carpeta, _ = set_ejemplo
    respuestas = [
        httpx.Response(529, json={"error": "overloaded"}),
        httpx.Response(429, json={"error": "rate_limit"}),
        httpx.Response(200, json=respuesta_anthropic(json.dumps(datos_factura_escaneada()))),
    ]
    ia = _ia(httpx.MockTransport(lambda r: respuestas.pop(0)))
    factura = ia.extraer(carpeta / "factura_escaneada.pdf")
    assert factura.numero == "00000088"
    assert ia.esperas == [1, 2]


def test_se_rinde_despues_de_los_reintentos(set_ejemplo):
    carpeta, _ = set_ejemplo
    ia = _ia(httpx.MockTransport(lambda r: httpx.Response(503, text="caido")), reintentos=2)
    with pytest.raises(ErrorIA, match="2 intentos"):
        ia.extraer(carpeta / "factura_escaneada.pdf")


def test_error_401_no_reintenta(set_ejemplo):
    carpeta, _ = set_ejemplo
    llamadas = []

    def manejar(request):
        llamadas.append(request)
        return httpx.Response(401, text="clave inválida")

    ia = _ia(httpx.MockTransport(manejar))
    with pytest.raises(ErrorIA, match="401"):
        ia.extraer(carpeta / "factura_escaneada.pdf")
    assert len(llamadas) == 1


def test_error_de_conexion_se_reintenta(set_ejemplo):
    carpeta, _ = set_ejemplo

    def manejar(request):
        raise httpx.ConnectError("sin red", request=request)

    ia = _ia(httpx.MockTransport(manejar), reintentos=3)
    with pytest.raises(ErrorIA, match="conexión"):
        ia.extraer(carpeta / "factura_escaneada.pdf")
    assert ia.esperas == [1, 2]


def test_respuesta_cortada(set_ejemplo):
    carpeta, _ = set_ejemplo
    transporte = httpx.MockTransport(
        lambda r: httpx.Response(200, json=respuesta_anthropic('{"tipo": "A", ', stop_reason="max_tokens"))
    )
    with pytest.raises(ErrorIA, match="cortada"):
        _ia(transporte).extraer(carpeta / "factura_escaneada.pdf")


def test_extraer_json_tolera_bloque_de_codigo():
    assert extraer_json('Acá está:\n```json\n{"tipo": "B"}\n```') == {"tipo": "B"}
    with pytest.raises(ErrorIA):
        extraer_json("no sé")
    with pytest.raises(ErrorIA):
        extraer_json("{tipo: B}")


def test_factura_desde_ia_normaliza():
    f = factura_desde_ia(
        {
            "tipo": "a",
            "punto_venta": "3",
            "numero": 1234,
            "fecha": "15/10/2026",
            "cuit_emisor": "30-71234567-1",
            "total": "95.570,00",
            "iva_21": 11550,
            "cae": None,
        }
    )
    assert (f.tipo, f.punto_venta, f.numero) == ("A", "00003", "00001234")
    assert f.cuit_emisor == "30712345671"
    assert f.total == Decimal("95570.00") and f.iva_21 == Decimal("11550.00")
    assert f.cae == ""


@pytest.mark.parametrize(
    "datos",
    [{"tipo": "Z"}, {"total": "mucho"}, {"fecha": "ayer"}, {"numero": "123456789012"}],
)
def test_factura_desde_ia_rechaza_datos_raros(datos):
    with pytest.raises(ErrorIA):
        factura_desde_ia(datos)
