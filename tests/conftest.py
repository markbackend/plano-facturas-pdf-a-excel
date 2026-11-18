import shutil
from pathlib import Path

import pytest

from facturas.config import Config
from facturas.ejemplos import generar_set


@pytest.fixture(scope="session")
def set_ejemplo(tmp_path_factory) -> tuple[Path, dict]:
    """Genera una sola vez los PDF de ejemplo (A, B, C, error de suma, escaneada y rota)."""
    carpeta = tmp_path_factory.mktemp("ejemplos")
    esperados = generar_set(carpeta)
    return carpeta, esperados


@pytest.fixture
def entrada(set_ejemplo, tmp_path) -> Path:
    """Copia el set de ejemplo a una carpeta nueva para cada prueba (porque se mueven los archivos)."""
    origen, _ = set_ejemplo
    destino = tmp_path / "entrada"
    destino.mkdir()
    for pdf in origen.glob("*.pdf"):
        shutil.copy(pdf, destino / pdf.name)
    return destino


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(registro_path=tmp_path / "registro.json")


@pytest.fixture(autouse=True)
def sin_variables_reales(monkeypatch):
    """Las pruebas nunca usan claves reales aunque estén en el entorno."""
    for nombre in ("ANTHROPIC_API_KEY", "WEBHOOK_URL", "WEBHOOK_TOKEN"):
        monkeypatch.delenv(nombre, raising=False)
