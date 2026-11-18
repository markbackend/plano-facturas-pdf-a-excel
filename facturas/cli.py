"""Línea de comandos: python -m facturas procesar entrada/ --excel salida.xlsx"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from dataclasses import replace
from pathlib import Path

from . import cuit as cuit_util
from .config import Config
from .ejemplos import generar_set
from .exportar import exportar_csv, exportar_excel, exportar_json
from .extractor_ia import ExtractorIA
from .modelo import Factura
from .procesador import Procesador, ResultadoLote
from .simulador import transporte_erp_simulado, transporte_ia_simulada
from .webhook import EnviadorWebhook

log = logging.getLogger("facturas")


def configurar_logs(nivel: str) -> None:
    logging.basicConfig(
        level=getattr(logging, nivel.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)


def exportar_todo(facturas: list[Factura], args, config: Config) -> None:
    if args.excel:
        exportar_excel(facturas, args.excel)
    if args.csv:
        exportar_csv(facturas, args.csv, config.csv_separador)
    if args.json:
        exportar_json(facturas, args.json)


def imprimir_tabla(facturas: list[Factura]) -> None:
    print()
    print(f"{'Archivo':<28} {'Estado':<8} {'Comprobante':<18} {'CUIT emisor':<14} {'Total':>14}  Observaciones")
    print("-" * 110)
    for f in facturas:
        total = f"{f.total:,.2f}".translate(str.maketrans(",.", ".,")) if f.total is not None else "-"  # formato argentino
        obs = "; ".join(f.observaciones)
        print(f"{f.archivo[:28]:<28} {f.estado:<8} {f.numero_completo:<18} {f.cuit_emisor:<14} {total:>14}  {obs[:80]}")
    print()


def cmd_procesar(args, config: Config) -> int:
    if args.registro:
        config = replace(config, registro_path=Path(args.registro))
    if not (args.excel or args.csv or args.json):
        args.excel = "salida/facturas.xlsx"
    ia = None if args.sin_ia else ExtractorIA.desde_config(config)
    if ia and not ia.habilitado:
        log.info("IA desactivada (sin ANTHROPIC_API_KEY): los PDF que no entiendan las reglas quedan para revisar")
    procesador = Procesador(config, ia=ia, webhook=EnviadorWebhook.desde_config(config))

    def exportar(resultado: ResultadoLote) -> None:
        facturas = resultado.nuevas if args.solo_nuevas else procesador.registro.facturas()
        exportar_todo(facturas, args, config)

    try:
        if args.vigilar:
            procesador.vigilar(args.entrada, args.intervalo or config.intervalo_vigilar, al_procesar=exportar)
            return 0
        resultado = procesador.procesar_carpeta(args.entrada, mover=not args.sin_mover, forzar=args.forzar)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 2
    exportar(resultado)
    imprimir_tabla(resultado.nuevas)
    print(resultado.resumen())
    return 0


def cmd_demo(args, config: Config) -> int:
    carpeta = Path(args.carpeta)
    marca = carpeta / ".demo-facturas"
    if carpeta.exists():
        if not marca.exists() and any(carpeta.iterdir()):
            log.error("La carpeta %s ya existe y no es de la demo. Elegí otra con --carpeta.", carpeta)
            return 2
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    marca.write_text("carpeta generada por 'python -m facturas demo', se puede borrar\n", encoding="utf-8")

    entrada = carpeta / "entrada"
    generar_set(entrada)
    print(f"Se generaron facturas de ejemplo en {entrada}")

    config = replace(
        config,
        registro_path=carpeta / "registro.json",
        carpeta_procesadas=None,
        carpeta_errores=None,
        webhook_url="http://erp-simulado.local/facturas",
    )
    if config.anthropic_api_key and args.ia_real:
        ia = ExtractorIA.desde_config(config)
        print(f"IA real: modelo {config.anthropic_modelo}")
    else:
        ia = ExtractorIA(api_key="clave-simulada", transport=transporte_ia_simulada())
        print("IA SIMULADA (sin internet): responde con datos fijos para la factura escaneada")
    recibidas: list[dict] = []
    webhook = EnviadorWebhook(config.webhook_url, transport=transporte_erp_simulado(recibidas))

    procesador = Procesador(config, ia=ia, webhook=webhook)
    resultado = procesador.procesar_carpeta(entrada)
    for f in resultado.nuevas:
        if f.origen == "ia" and not args.ia_real:
            f.observaciones.append("(demo: IA simulada)")

    salida = carpeta / "salida"
    exportar_excel(resultado.nuevas, salida / "facturas.xlsx")
    exportar_csv(resultado.nuevas, salida / "facturas.csv", config.csv_separador)
    exportar_json(resultado.nuevas, salida / "facturas.json")

    imprimir_tabla(resultado.nuevas)
    print(resultado.resumen())
    print(f"ERP simulado: recibió {len(recibidas)} facturas por webhook")
    print(f"Salidas: {salida / 'facturas.xlsx'}, facturas.csv y facturas.json")
    print(f"PDF movidos a {entrada / 'procesadas'} y {entrada / 'errores'}")

    # Simula que alguien vuelve a dejar la misma factura con otro nombre: no se carga dos veces
    shutil.copy(entrada / "procesadas" / "factura_A_el_sol.pdf", entrada / "copia_de_factura_A.pdf")
    segunda = procesador.procesar_carpeta(entrada)
    print(f"Segunda pasada (se volvió a dejar la factura A con otro nombre): {segunda.resumen()}")
    return 0


def cmd_ejemplos(args, config: Config) -> int:
    esperados = generar_set(args.carpeta)
    print(f"Se generaron {len(esperados) + 1} PDF de ejemplo en {args.carpeta}")
    return 0


def cmd_cuit(args, config: Config) -> int:
    valido = cuit_util.es_valido(args.numero)
    print(f"{cuit_util.formatear(args.numero)}: {'válido' if valido else 'INVÁLIDO'}")
    return 0 if valido else 1


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m facturas", description="Lectura de facturas PDF (AFIP) a Excel/CSV/JSON")
    parser.add_argument("--env", default=".env", help="archivo .env a cargar (por defecto .env)")
    parser.add_argument("-v", "--verbose", action="store_true", help="logs detallados (DEBUG)")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("procesar", help="procesa los PDF de una carpeta")
    p.add_argument("entrada", help="carpeta con los PDF")
    p.add_argument("--excel", help="ruta del Excel de salida (por defecto salida/facturas.xlsx)")
    p.add_argument("--csv", help="ruta del CSV de salida")
    p.add_argument("--json", help="ruta del JSON de salida")
    p.add_argument("--vigilar", action="store_true", help="queda vigilando la carpeta (Ctrl+C para salir)")
    p.add_argument("--intervalo", type=float, help="segundos entre revisiones al vigilar")
    p.add_argument("--sin-mover", action="store_true", help="no mueve los PDF a procesadas/errores")
    p.add_argument("--forzar", action="store_true", help="reprocesa aunque el archivo ya esté en el registro")
    p.add_argument("--sin-ia", action="store_true", help="no usa la IA aunque haya clave")
    p.add_argument("--registro", help="ruta del registro de archivos procesados (JSON)")
    p.add_argument("--solo-nuevas", action="store_true", help="exporta solo lo procesado en esta corrida")
    p.set_defaults(func=cmd_procesar)

    d = sub.add_parser("demo", help="demo sin claves: genera facturas de ejemplo y las procesa")
    d.add_argument("--carpeta", default="demo", help="carpeta de trabajo de la demo (se borra y se recrea)")
    d.add_argument("--ia-real", action="store_true", help="usa la API real de Anthropic (necesita ANTHROPIC_API_KEY)")
    d.set_defaults(func=cmd_demo)

    e = sub.add_parser("ejemplos", help="genera PDF de ejemplo en una carpeta")
    e.add_argument("carpeta")
    e.set_defaults(func=cmd_ejemplos)

    c = sub.add_parser("cuit", help="valida un CUIT")
    c.add_argument("numero")
    c.set_defaults(func=cmd_cuit)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = crear_parser().parse_args(argv)
    config = Config.desde_entorno(args.env)
    configurar_logs("DEBUG" if args.verbose else config.log_nivel)
    try:
        return args.func(args, config)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
