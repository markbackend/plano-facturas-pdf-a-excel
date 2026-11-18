"""Procesa una carpeta de PDF: extrae, valida, evita repetidos (hash), mueve y registra."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import Config
from .extractor_ia import ErrorIA, ExtractorIA
from .extractor_reglas import ErrorLectura, extraer_pdf
from .modelo import ESTADO_ERROR, ESTADO_OK, ESTADO_REVISAR, Factura
from .validaciones import campos_faltantes, validar
from .webhook import EnviadorWebhook

log = logging.getLogger(__name__)


def hash_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


class Registro:
    """Facturas ya procesadas, indexadas por hash del archivo. Se guarda en un JSON."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        self._datos: dict[str, dict] = {}
        if self.ruta.exists():
            try:
                self._datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                respaldo = self.ruta.with_suffix(".corrupto.json")
                log.error("Registro ilegible (%s). Se renombra a %s y se empieza de cero.", exc, respaldo)
                self.ruta.replace(respaldo)

    def contiene(self, hash_: str) -> bool:
        return hash_ in self._datos

    def agregar(self, factura: Factura) -> None:
        self._datos[factura.hash] = factura.a_dict()
        self.guardar()

    def buscar_clave(self, clave: str, excepto_hash: str = "") -> Factura | None:
        if not clave:
            return None
        for hash_, datos in self._datos.items():
            if hash_ != excepto_hash and datos.get("estado") != ESTADO_ERROR:
                if Factura.desde_dict(datos).clave == clave:
                    return Factura.desde_dict(datos)
        return None

    def facturas(self) -> list[Factura]:
        return [Factura.desde_dict(d) for d in self._datos.values()]

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(self._datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporal, self.ruta)  # escritura atómica


@dataclass
class ResultadoLote:
    nuevas: list[Factura] = field(default_factory=list)
    repetidas: list[str] = field(default_factory=list)

    def contar(self, estado: str) -> int:
        return sum(1 for f in self.nuevas if f.estado == estado)

    def resumen(self) -> str:
        return (
            f"{len(self.nuevas)} nuevas ({self.contar(ESTADO_OK)} ok, {self.contar(ESTADO_REVISAR)} para revisar, "
            f"{self.contar(ESTADO_ERROR)} con error), {len(self.repetidas)} ya procesadas"
        )


def mover_sin_pisar(origen: Path, carpeta: Path) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / origen.name
    n = 1
    while destino.exists():
        destino = carpeta / f"{origen.stem}_{n}{origen.suffix}"
        n += 1
    shutil.move(str(origen), str(destino))
    return destino


class Procesador:
    def __init__(
        self,
        config: Config,
        ia: ExtractorIA | None = None,
        webhook: EnviadorWebhook | None = None,
        registro: Registro | None = None,
    ):
        self.config = config
        self.ia = ia
        self.webhook = webhook
        self.registro = registro or Registro(config.registro_path)

    # ------------------------------------------------------------------ un archivo
    def procesar_archivo(self, ruta: str | Path, hash_: str | None = None) -> Factura:
        ruta = Path(ruta)
        hash_ = hash_ or hash_archivo(ruta)
        try:
            factura, texto = extraer_pdf(ruta)
        except ErrorLectura as exc:
            log.error("%s: %s", ruta.name, exc)
            return self._completar(Factura(estado=ESTADO_ERROR, observaciones=[str(exc)]), ruta, hash_)

        motivo = ""
        if not texto.strip():
            motivo = "el PDF no tiene texto (¿escaneado?)"
        elif faltan := campos_faltantes(factura):
            motivo = "las reglas no encontraron: " + ", ".join(faltan)

        problemas_extra: list[str] = []
        avisos: list[str] = []
        if motivo:
            if self.ia and self.ia.habilitado:
                try:
                    factura = self.ia.extraer(ruta, texto)
                    avisos.append(f"Extraída con IA porque {motivo}")
                except ErrorIA as exc:
                    log.warning("%s: la IA falló: %s", ruta.name, exc)
                    problemas_extra.append(f"No se pudo leer: {motivo}; la IA falló: {exc}")
            else:
                problemas_extra.append(f"No se pudo leer: {motivo}; IA no configurada (falta ANTHROPIC_API_KEY)")

        problemas = problemas_extra + validar(factura, self.config.tolerancia_suma)
        duplicada = self.registro.buscar_clave(factura.clave, excepto_hash=hash_)
        if duplicada:
            problemas.append(f"Posible duplicado: el comprobante ya se cargó desde {duplicada.archivo}")

        factura.observaciones = avisos + problemas
        factura.estado = ESTADO_REVISAR if problemas else ESTADO_OK
        return self._completar(factura, ruta, hash_)

    @staticmethod
    def _completar(factura: Factura, ruta: Path, hash_: str) -> Factura:
        factura.archivo = ruta.name
        factura.hash = hash_
        factura.procesado_el = datetime.now().isoformat(timespec="seconds")
        return factura

    # ------------------------------------------------------------------ carpeta
    def procesar_carpeta(
        self,
        entrada: str | Path,
        mover: bool = True,
        forzar: bool = False,
        solo_estables: bool = False,
    ) -> ResultadoLote:
        entrada = Path(entrada)
        if not entrada.is_dir():
            raise FileNotFoundError(f"No existe la carpeta de entrada: {entrada}")
        procesadas = self.config.carpeta_procesadas or entrada / "procesadas"
        errores = self.config.carpeta_errores or entrada / "errores"

        resultado = ResultadoLote()
        archivos = sorted(p for p in entrada.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
        for ruta in archivos:
            if solo_estables and time.time() - ruta.stat().st_mtime < 2:
                log.debug("%s todavía se está copiando, queda para el próximo ciclo", ruta.name)
                continue
            try:
                hash_ = hash_archivo(ruta)
            except OSError as exc:
                log.warning("No se pudo leer %s (¿abierto por otro programa?): %s", ruta.name, exc)
                continue

            if self.registro.contiene(hash_) and not forzar:
                log.info("%s ya se procesó antes (mismo contenido), se saltea", ruta.name)
                resultado.repetidas.append(ruta.name)
                if mover:
                    mover_sin_pisar(ruta, procesadas)
                continue

            factura = self.procesar_archivo(ruta, hash_)
            if self.webhook and (
                factura.estado == ESTADO_OK
                or (factura.estado == ESTADO_REVISAR and self.config.webhook_enviar_revisar)
            ):
                factura.enviado = self.webhook.enviar(factura)
            self.registro.agregar(factura)
            resultado.nuevas.append(factura)
            log.info(
                "%s -> %s %s%s",
                ruta.name,
                factura.estado.upper(),
                factura.numero_completo or "",
                f" ({'; '.join(factura.observaciones)})" if factura.observaciones else "",
            )
            if mover:
                mover_sin_pisar(ruta, errores if factura.estado == ESTADO_ERROR else procesadas)

        log.info("Lote terminado: %s", resultado.resumen())
        return resultado

    def vigilar(
        self,
        entrada: str | Path,
        intervalo: float,
        al_procesar: Callable[[ResultadoLote], None] | None = None,
        max_ciclos: int | None = None,
        espera: Callable[[float], None] = time.sleep,
    ) -> None:
        """Revisa la carpeta cada `intervalo` segundos. Ctrl+C para cortar."""
        log.info("Vigilando %s cada %ss (Ctrl+C para salir)", entrada, intervalo)
        ciclo = 0
        try:
            while max_ciclos is None or ciclo < max_ciclos:
                ciclo += 1
                resultado = self.procesar_carpeta(entrada, solo_estables=max_ciclos is None)
                if resultado.nuevas and al_procesar:
                    al_procesar(resultado)
                if max_ciclos is None or ciclo < max_ciclos:
                    espera(intervalo)
        except KeyboardInterrupt:
            log.info("Vigilancia detenida por el usuario")
