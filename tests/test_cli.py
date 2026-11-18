import json

from openpyxl import load_workbook

from facturas.cli import main
from facturas.config import Config


def test_cli_procesar(entrada, tmp_path, capsys):
    excel = tmp_path / "salida.xlsx"
    salida_json = tmp_path / "salida.json"
    codigo = main(
        [
            "--env", str(tmp_path / "no-existe.env"),
            "procesar", str(entrada),
            "--excel", str(excel),
            "--json", str(salida_json),
            "--registro", str(tmp_path / "registro.json"),
        ]
    )
    assert codigo == 0
    assert load_workbook(excel).sheetnames == ["Facturas", "Revisar", "Resumen"]
    assert len(json.loads(salida_json.read_text(encoding="utf-8"))) == 6
    salida = capsys.readouterr().out
    assert "3 ok" in salida and "A-00003-00001234" in salida


def test_cli_procesar_carpeta_inexistente(tmp_path):
    codigo = main(["--env", "x.env", "procesar", str(tmp_path / "no-esta"), "--registro", str(tmp_path / "r.json")])
    assert codigo == 2


def test_cli_demo(tmp_path, capsys):
    carpeta = tmp_path / "demo"
    assert main(["--env", "x.env", "demo", "--carpeta", str(carpeta)]) == 0
    salida = capsys.readouterr().out
    assert "4 ok, 1 para revisar, 1 con error" in salida
    assert "recibió 4 facturas" in salida
    assert "0 nuevas" in salida and "1 ya procesadas" in salida
    assert (carpeta / "salida" / "facturas.xlsx").exists()
    # Se puede volver a correr (borra y recrea su carpeta)
    assert main(["--env", "x.env", "demo", "--carpeta", str(carpeta)]) == 0


def test_cli_demo_no_borra_carpetas_ajenas(tmp_path):
    carpeta = tmp_path / "mis_cosas"
    carpeta.mkdir()
    (carpeta / "importante.txt").write_text("no borrar")
    assert main(["--env", "x.env", "demo", "--carpeta", str(carpeta)]) == 2
    assert (carpeta / "importante.txt").exists()


def test_cli_cuit(capsys):
    assert main(["--env", "x.env", "cuit", "30712345671"]) == 0
    assert main(["--env", "x.env", "cuit", "30712345672"]) == 1
    assert "INVÁLIDO" in capsys.readouterr().out


def test_config_desde_entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_MODELO", "otro-modelo")
    monkeypatch.setenv("TOLERANCIA_SUMA", "1.5")
    monkeypatch.setenv("IA_HABILITADA", "no")
    config = Config.desde_entorno(tmp_path / "no-existe.env")
    assert config.anthropic_modelo == "otro-modelo"
    assert str(config.tolerancia_suma) == "1.5"
    assert config.ia_habilitada is False
    assert Config.desde_entorno(None).anthropic_modelo == "otro-modelo"
