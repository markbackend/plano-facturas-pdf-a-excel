import csv
import json
from datetime import date

import httpx
from openpyxl import load_workbook

from facturas.exportar import exportar_csv, exportar_excel, exportar_json
from facturas.modelo import Factura
from facturas.procesador import Procesador
from facturas.webhook import EnviadorWebhook


def _facturas(entrada, config):
    return Procesador(config).procesar_carpeta(entrada, mover=False).nuevas


def test_excel_tiene_hojas_facturas_revisar_y_resumen(entrada, config, tmp_path):
    ruta = exportar_excel(_facturas(entrada, config), tmp_path / "salida.xlsx")
    libro = load_workbook(ruta)
    assert libro.sheetnames == ["Facturas", "Revisar", "Resumen"]

    hoja = libro["Facturas"]
    encabezado = [c.value for c in hoja[1]]
    assert "CUIT emisor" in encabezado and "Total" in encabezado
    filas = list(hoja.iter_rows(min_row=2, values_only=True))
    assert len(filas) == 3
    fila_a = next(f for f in filas if f[0] == "factura_A_el_sol.pdf")
    assert fila_a[encabezado.index("Total")] == 95570.0
    assert fila_a[encabezado.index("CUIT emisor")] == "30-71234567-1"
    assert fila_a[encabezado.index("Fecha")].date() == date(2026, 10, 15)

    revisar = list(libro["Revisar"].iter_rows(min_row=2, values_only=True))
    assert len(revisar) == 3  # error de suma, escaneada sin IA, archivo roto
    assert {r[0] for r in revisar} == {"revisar", "error"}
    assert all(r[1] for r in revisar)  # todas con observaciones

    resumen = dict(libro["Resumen"].iter_rows(min_row=2, values_only=True))
    assert resumen["Facturas OK"] == 3
    assert resumen["Total facturado (OK)"] == 95570.0 + 99500.0 + 150000.0


def test_csv_y_json(entrada, config, tmp_path):
    facturas = _facturas(entrada, config)
    ruta_csv = exportar_csv(facturas, tmp_path / "f.csv")
    with open(ruta_csv, encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert len(filas) == 6
    fila_b = next(f for f in filas if f["archivo"] == "factura_B_los_andes.pdf")
    assert fila_b["total"] == "99500.00" and fila_b["fecha"] == "2026-10-20" and fila_b["estado"] == "ok"

    datos = json.loads(exportar_json(facturas, tmp_path / "f.json").read_text(encoding="utf-8"))
    assert len(datos) == 6
    assert {d["estado"] for d in datos} == {"ok", "revisar", "error"}
    roundtrip = Factura.desde_dict(next(d for d in datos if d["archivo"] == "factura_A_el_sol.pdf"))
    assert roundtrip.iva_total == 14070


def _factura() -> Factura:
    return Factura(archivo="f.pdf", hash="abc123", tipo="A", punto_venta="00001", numero="00000001")


def test_webhook_reintenta_y_manda_token():
    pedidos = []
    respuestas = [httpx.Response(503), httpx.Response(500), httpx.Response(200, json={"ok": True})]

    def manejar(request):
        pedidos.append(request)
        return respuestas.pop(0)

    esperas = []
    webhook = EnviadorWebhook("http://erp.local/api", token="t0k3n", transport=httpx.MockTransport(manejar), espera=esperas.append)
    assert webhook.enviar(_factura()) is True
    assert len(pedidos) == 3 and esperas == [1.0, 2.0]
    assert pedidos[0].headers["Authorization"] == "Bearer t0k3n"
    assert pedidos[0].headers["Idempotency-Key"] == "abc123"
    assert json.loads(pedidos[0].content)["numero_completo"] == "A-00001-00000001"


def test_webhook_se_rinde():
    webhook = EnviadorWebhook(
        "http://erp.local/api", reintentos=3, transport=httpx.MockTransport(lambda r: httpx.Response(502)), espera=lambda s: None
    )
    assert webhook.enviar(_factura()) is False


def test_webhook_no_reintenta_un_400():
    pedidos = []

    def manejar(request):
        pedidos.append(request)
        return httpx.Response(400, text="falta campo")

    webhook = EnviadorWebhook("http://erp.local/api", transport=httpx.MockTransport(manejar), espera=lambda s: None)
    assert webhook.enviar(_factura()) is False
    assert len(pedidos) == 1


def test_webhook_error_de_conexion():
    def manejar(request):
        raise httpx.ConnectError("sin red", request=request)

    webhook = EnviadorWebhook("http://erp.local/api", reintentos=2, transport=httpx.MockTransport(manejar), espera=lambda s: None)
    assert webhook.enviar(_factura()) is False
