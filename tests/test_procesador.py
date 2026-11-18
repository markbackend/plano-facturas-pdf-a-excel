import json
import shutil

import httpx

from facturas.extractor_ia import ExtractorIA
from facturas.procesador import Procesador, Registro
from facturas.simulador import transporte_erp_simulado, transporte_ia_simulada
from facturas.webhook import EnviadorWebhook


def _por_archivo(resultado):
    return {f.archivo: f for f in resultado.nuevas}


def test_procesa_carpeta_sin_ia(entrada, config):
    resultado = Procesador(config).procesar_carpeta(entrada)
    f = _por_archivo(resultado)
    assert len(f) == 6
    assert f["factura_A_el_sol.pdf"].estado == "ok"
    assert f["factura_B_los_andes.pdf"].estado == "ok"
    assert f["factura_C_perez.pdf"].estado == "ok"
    assert f["factura_A_error_suma.pdf"].estado == "revisar"
    escaneada = f["factura_escaneada.pdf"]
    assert escaneada.estado == "revisar"
    assert any("IA no configurada" in o for o in escaneada.observaciones)
    assert f["archivo_roto.pdf"].estado == "error"

    # Movidos: los leídos a procesadas, el roto a errores
    assert not list(entrada.glob("*.pdf"))
    assert (entrada / "errores" / "archivo_roto.pdf").exists()
    assert len(list((entrada / "procesadas").glob("*.pdf"))) == 5


def test_con_ia_la_escaneada_queda_ok(entrada, config):
    ia = ExtractorIA(api_key="x", transport=transporte_ia_simulada(), espera=lambda s: None)
    resultado = Procesador(config, ia=ia).procesar_carpeta(entrada)
    escaneada = _por_archivo(resultado)["factura_escaneada.pdf"]
    assert escaneada.estado == "ok" and escaneada.origen == "ia"
    assert escaneada.numero_completo == "C-00001-00000088"


def test_si_la_ia_falla_queda_para_revisar(entrada, config):
    ia = ExtractorIA(
        api_key="x",
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="error")),
        reintentos=1,
    )
    resultado = Procesador(config, ia=ia).procesar_carpeta(entrada)
    escaneada = _por_archivo(resultado)["factura_escaneada.pdf"]
    assert escaneada.estado == "revisar"
    assert any("la IA falló" in o for o in escaneada.observaciones)


def test_no_repite_archivos_ya_procesados(entrada, config):
    procesador = Procesador(config)
    procesador.procesar_carpeta(entrada)
    # Vuelve a aparecer la misma factura con otro nombre
    shutil.copy(entrada / "procesadas" / "factura_B_los_andes.pdf", entrada / "otra_vez.pdf")
    segunda = Procesador(config).procesar_carpeta(entrada)  # registro leído de disco
    assert segunda.nuevas == []
    assert segunda.repetidas == ["otra_vez.pdf"]
    assert (entrada / "procesadas" / "otra_vez.pdf").exists()

    registro = json.loads(config.registro_path.read_text(encoding="utf-8"))
    assert len(registro) == 6


def test_forzar_reprocesa(entrada, config):
    Procesador(config).procesar_carpeta(entrada, mover=False)
    segunda = Procesador(config).procesar_carpeta(entrada, mover=False, forzar=True)
    assert len(segunda.nuevas) == 6
    assert len(Registro(config.registro_path).facturas()) == 6


def test_detecta_mismo_comprobante_en_otro_pdf(entrada, config, tmp_path):
    from facturas.ejemplos import FACTURA_C, crear_factura_pdf, variante

    Procesador(config).procesar_carpeta(entrada)
    # Mismo comprobante, PDF distinto (otro hash): por ejemplo, reimpreso
    crear_factura_pdf(entrada / "reimpresa.pdf", variante(FACTURA_C, copias=["ORIGINAL", "DUPLICADO"]))
    resultado = Procesador(config).procesar_carpeta(entrada)
    f = resultado.nuevas[0]
    assert f.estado == "revisar"
    assert any("Posible duplicado" in o for o in f.observaciones)


def test_sin_mover_deja_los_archivos(entrada, config):
    Procesador(config).procesar_carpeta(entrada, mover=False)
    assert len(list(entrada.glob("*.pdf"))) == 6


def test_webhook_envia_solo_las_ok(entrada, config):
    recibidas: list = []
    webhook = EnviadorWebhook("http://erp.local/api", transport=transporte_erp_simulado(recibidas))
    resultado = Procesador(config, webhook=webhook).procesar_carpeta(entrada)
    assert len(recibidas) == 3
    assert {r["numero_completo"] for r in recibidas} == {"A-00003-00001234", "B-00007-00045678", "C-00001-00000087"}
    assert all(f.enviado for f in resultado.nuevas if f.estado == "ok")


def test_vigilar_procesa_y_llama_al_callback(entrada, config):
    lotes = []
    esperas = []
    Procesador(config).vigilar(entrada, intervalo=5, al_procesar=lotes.append, max_ciclos=2, espera=esperas.append)
    assert len(lotes) == 1 and len(lotes[0].nuevas) == 6  # el segundo ciclo no encuentra nada nuevo
    assert esperas == [5]


def test_registro_corrupto_se_respalda(config):
    config.registro_path.write_text("{no es json", encoding="utf-8")
    registro = Registro(config.registro_path)
    assert registro.facturas() == []
    assert config.registro_path.with_suffix(".corrupto.json").exists()
