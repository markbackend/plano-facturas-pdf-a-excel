"""Genera facturas PDF de ejemplo con el formato de AFIP (para la demo y las pruebas).

Los datos son ficticios. Los CUIT se arman con dígito verificador válido.
"""

from __future__ import annotations

import copy
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .cuit import armar
from .importes import CENTAVOS, formatear_importe

CODIGO_POR_TIPO = {"A": "01", "B": "06", "C": "11"}

CUIT_SOL = armar("30", "71234567")  # 30-71234567-1
CUIT_NORTE = armar("30", "70987654")  # 30-70987654-2
CUIT_ANDES = armar("30", "71555444")  # 30-71555444-1
CUIT_GARCIA = armar("20", "28456789")  # 20-28456789-8
CUIT_PEREZ = armar("27", "33123456")  # 27-33123456-2
CUIT_SUR = armar("33", "70111222")  # 33-70111222-4

FACTURA_A = {
    "tipo": "A",
    "punto_venta": 3,
    "numero": 1234,
    "fecha": date(2026, 10, 15),
    "emisor": {
        "nombre": "DISTRIBUIDORA EL SOL S.A.",
        "cuit": CUIT_SOL,
        "domicilio": "Av. Corrientes 1234 - CABA",
        "condicion": "IVA Responsable Inscripto",
    },
    "receptor": {"nombre": "COMERCIAL NORTE S.R.L.", "cuit": CUIT_NORTE, "condicion": "IVA Responsable Inscripto"},
    "items": [
        ("Resma papel A4 x500", 10, Decimal("5500.00"), Decimal("21")),
        ("Libros técnicos", 2, Decimal("12000.00"), Decimal("10.5")),
    ],
    "percepciones": [("Percepción IIBB CABA", Decimal("2500.00"))],
    "cae": "76123456789012",
    "vto_cae": date(2026, 10, 25),
    "copias": ["ORIGINAL", "DUPLICADO", "TRIPLICADO"],
}

FACTURA_B = {
    "tipo": "B",
    "punto_venta": 7,
    "numero": 45678,
    "fecha": date(2026, 10, 20),
    "emisor": {
        "nombre": "FERRETERÍA LOS ANDES S.R.L.",
        "cuit": CUIT_ANDES,
        "domicilio": "San Martín 550 - Mendoza",
        "condicion": "IVA Responsable Inscripto",
    },
    "receptor": {"nombre": "GARCÍA JUAN PABLO", "cuit": CUIT_GARCIA, "condicion": "Consumidor Final"},
    "items": [
        ("Taladro percutor 750W", 1, Decimal("85000.00"), None),
        ("Juego de mechas x10", 2, Decimal("7250.00"), None),
    ],
    "percepciones": [],
    "cae": "76234567890123",
    "vto_cae": date(2026, 10, 30),
}

FACTURA_C = {
    "tipo": "C",
    "punto_venta": 1,
    "numero": 87,
    "fecha": date(2026, 11, 2),
    "emisor": {
        "nombre": "PÉREZ MARÍA LAURA",
        "cuit": CUIT_PEREZ,
        "domicilio": "Belgrano 1020 - Rosario",
        "condicion": "Responsable Monotributo",
    },
    "receptor": {"nombre": "DISTRIBUIDORA EL SOL S.A.", "cuit": CUIT_SOL, "condicion": "IVA Responsable Inscripto"},
    "items": [("Diseño de logo e identidad visual", 1, Decimal("150000.00"), None)],
    "percepciones": [],
    "cae": "76345678901234",
    "vto_cae": date(2026, 11, 12),
}

FACTURA_A_ERROR_SUMA = {
    "tipo": "A",
    "punto_venta": 2,
    "numero": 999,
    "fecha": date(2026, 11, 5),
    "emisor": {
        "nombre": "SERVICIOS INTEGRALES DEL SUR S.A.",
        "cuit": CUIT_SUR,
        "domicilio": "Mitre 300 - Bahía Blanca",
        "condicion": "IVA Responsable Inscripto",
    },
    "receptor": {"nombre": "COMERCIAL NORTE S.R.L.", "cuit": CUIT_NORTE, "condicion": "IVA Responsable Inscripto"},
    "items": [("Mantenimiento mensual de equipos", 1, Decimal("200000.00"), Decimal("21"))],
    "percepciones": [],
    "cae": "76456789012345",
    "vto_cae": date(2026, 11, 15),
    "error_total": Decimal("1000.00"),  # el total impreso tiene $1.000 de más
}


def calcular(datos: dict) -> dict:
    """Calcula los importes que deberían salir de la factura (lo que esperan las pruebas)."""
    tipo = datos["tipo"]
    neto = Decimal("0.00")
    iva = {"21": Decimal("0.00"), "10.5": Decimal("0.00"), "27": Decimal("0.00")}
    for _, cantidad, precio, alicuota in datos["items"]:
        subtotal = (Decimal(cantidad) * precio).quantize(CENTAVOS)
        neto += subtotal
        if tipo == "A" and alicuota is not None:
            iva[str(alicuota)] += (subtotal * alicuota / 100).quantize(CENTAVOS)
    percepciones = sum((p for _, p in datos.get("percepciones", [])), Decimal("0.00"))
    total = neto + sum(iva.values()) + percepciones + datos.get("error_total", Decimal("0.00"))
    return {
        "tipo": tipo,
        "punto_venta": f"{datos['punto_venta']:05d}",
        "numero": f"{datos['numero']:08d}",
        "fecha": datos["fecha"],
        "cuit_emisor": datos["emisor"]["cuit"],
        "razon_social_emisor": datos["emisor"]["nombre"],
        "cuit_receptor": datos["receptor"].get("cuit", ""),
        "razon_social_receptor": datos["receptor"]["nombre"],
        "neto_gravado": neto,
        "iva_21": iva["21"],
        "iva_10_5": iva["10.5"],
        "iva_27": iva["27"],
        "percepciones": percepciones,
        "total": total,
        "cae": datos["cae"],
        "vencimiento_cae": datos["vto_cae"],
    }


def _plata(valor: Decimal) -> str:
    return f"$ {formatear_importe(valor)}"


def _dibujar_factura(c: canvas.Canvas, d: dict, copia: str, valores: dict) -> None:
    ancho, _ = A4
    tipo = d["tipo"]
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(ancho / 2, 812, copia)
    c.rect(30, 690, ancho - 60, 110)

    # Letra y código en el recuadro del medio
    c.rect(ancho / 2 - 22, 752, 44, 44)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(ancho / 2, 768, tipo)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(ancho / 2, 756, f"COD. {CODIGO_POR_TIPO[tipo]}")

    # Emisor (izquierda) y comprobante (derecha). Varias etiquetas comparten renglón, como en AFIP.
    e = d["emisor"]
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, 778, e["nombre"])
    c.setFont("Helvetica-Bold", 16)
    c.drawString(340, 778, "FACTURA")
    c.setFont("Helvetica", 8)
    if d.get("formato_numero") == "mezclado":
        c.drawString(340, 760, "Punto de Venta:   Comp. Nro:")
        c.drawString(450, 760, f"{d['punto_venta']:05d}   {d['numero']:08d}")
    else:
        c.drawString(340, 760, f"Punto de Venta: {d['punto_venta']:05d}     Comp. Nro: {d['numero']:08d}")
    c.drawString(40, 744, f"Razón Social: {e['nombre']}")
    c.drawString(340, 744, f"Fecha de Emisión: {d['fecha']:%d/%m/%Y}")
    c.drawString(40, 730, f"Domicilio Comercial: {e['domicilio']}")
    c.drawString(340, 730, f"CUIT: {e['cuit']}")
    c.drawString(40, 716, f"Condición frente al IVA: {e['condicion']}")
    c.drawString(340, 716, "Ingresos Brutos: 901-123456-7")
    c.drawString(340, 702, "Fecha de Inicio de Actividades: 01/03/2015")

    # Receptor
    r = d["receptor"]
    c.rect(30, 640, ancho - 60, 44)
    if r.get("cuit"):
        c.drawString(40, 668, f"CUIT: {r['cuit']}")
    else:
        c.drawString(40, 668, "DNI: 30123456")
    c.drawString(200, 668, f"Apellido y Nombre / Razón Social: {r['nombre']}")
    c.drawString(40, 652, f"Condición frente al IVA: {r['condicion']}")
    c.drawString(340, 652, "Condición de venta: Contado")

    # Ítems
    y = 620
    c.setFont("Helvetica-Bold", 8)
    columnas = ["Producto / Servicio", "Cantidad", "Precio Unit.", "Subtotal"]
    if tipo == "A":
        columnas = ["Producto / Servicio", "Cantidad", "Precio Unit.", "Alícuota IVA", "Subtotal"]
    xs = [40, 270, 330, 410, 490] if tipo == "A" else [40, 300, 380, 480]
    for x, titulo in zip(xs, columnas):
        c.drawString(x, y, titulo)
    c.setFont("Helvetica", 8)
    for descripcion, cantidad, precio, alicuota in d["items"]:
        y -= 16
        subtotal = (Decimal(cantidad) * precio).quantize(CENTAVOS)
        celdas = [descripcion, f"{cantidad},00", formatear_importe(precio)]
        if tipo == "A":
            celdas.append(f"{str(alicuota).replace('.', ',')}%")
        celdas.append(formatear_importe(subtotal))
        for x, texto in zip(xs, celdas):
            c.drawString(x, y, texto)

    # Otros tributos (detalle) a la izquierda
    y_tot = 260
    if d.get("percepciones"):
        c.setFont("Helvetica-Bold", 8)
        c.drawString(40, y_tot + 14, "Otros tributos")
        c.setFont("Helvetica", 8)
        for i, (nombre, importe) in enumerate(d["percepciones"]):
            c.drawString(40, y_tot - 14 * (i + 1), f"{nombre}: {_plata(importe)}")

    # Totales a la derecha
    if tipo == "A":
        filas = [
            ("Importe Neto Gravado", valores["neto_gravado"]),
            ("IVA 27%", valores["iva_27"]),
            ("IVA 21%", valores["iva_21"]),
            ("IVA 10.5%", valores["iva_10_5"]),
            ("Importe Otros Tributos", valores["percepciones"]),
            ("Importe Total", valores["total"]),
        ]
    else:
        filas = [
            ("Subtotal", valores["neto_gravado"]),
            ("Importe Otros Tributos", valores["percepciones"]),
            ("Importe Total", valores["total"]),
        ]
    c.rect(30, y_tot - 14 * len(filas) - 8, ancho - 60, 14 * len(filas) + 24)
    for i, (etiqueta, importe) in enumerate(filas):
        yy = y_tot - 14 * i
        c.setFont("Helvetica-Bold" if etiqueta == "Importe Total" else "Helvetica", 8)
        c.drawRightString(470, yy, f"{etiqueta}:")
        c.drawRightString(555, yy, _plata(importe))

    # CAE
    c.setFont("Helvetica-Bold", 8)
    c.drawString(40, 120, "Comprobante Autorizado")
    c.drawString(340, 120, f"CAE N°: {d['cae']}")
    c.drawString(340, 106, f"Fecha de Vto. de CAE: {d['vto_cae']:%d/%m/%Y}")
    c.setFont("Helvetica", 7)
    c.drawString(40, 106, "Esta Administración Federal no se responsabiliza por los datos ingresados en el detalle.")
    c.drawCentredString(ancho / 2, 60, "Pág. 1/1")


def _dibujar_escaneo(c: canvas.Canvas, semilla: int = 7) -> None:
    """Simula un escaneo: solo trazos y manchas, sin texto seleccionable."""
    ancho, alto = A4
    azar = random.Random(semilla)
    c.setFillGray(0.97)
    c.rect(0, 0, ancho, alto, fill=1, stroke=0)
    c.setFillGray(0.2)
    c.rect(30, 690, ancho - 60, 110, fill=0)
    for _ in range(260):
        x, y = azar.uniform(40, ancho - 80), azar.uniform(80, alto - 60)
        c.rect(x, y, azar.uniform(2, 40), azar.uniform(1, 5), fill=1, stroke=0)


def crear_factura_pdf(ruta: str | Path, datos: dict, ilegible: bool = False) -> dict:
    """Crea el PDF y devuelve los valores esperados."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    valores = calcular(datos)
    c = canvas.Canvas(str(ruta), pagesize=A4)
    c.setTitle(f"Factura {datos['tipo']} {datos['punto_venta']:05d}-{datos['numero']:08d}")
    for copia in datos.get("copias", ["ORIGINAL"]):
        if ilegible:
            _dibujar_escaneo(c)
        else:
            _dibujar_factura(c, datos, copia, valores)
        c.showPage()
    c.save()
    return valores


def variante(base: dict, **cambios) -> dict:
    """Copia una factura de ejemplo cambiando algunos campos."""
    nueva = copy.deepcopy(base)
    nueva.update(cambios)
    return nueva


def generar_set(carpeta: str | Path) -> dict[str, dict]:
    """Genera el set de ejemplo: A (con duplicado/triplicado), B, C, A con error de suma,
    una escaneada (sin texto) y un archivo roto. Devuelve {nombre_archivo: valores_esperados}."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    esperados = {
        "factura_A_el_sol.pdf": crear_factura_pdf(carpeta / "factura_A_el_sol.pdf", FACTURA_A),
        "factura_B_los_andes.pdf": crear_factura_pdf(carpeta / "factura_B_los_andes.pdf", FACTURA_B),
        "factura_C_perez.pdf": crear_factura_pdf(carpeta / "factura_C_perez.pdf", FACTURA_C),
        "factura_A_error_suma.pdf": crear_factura_pdf(carpeta / "factura_A_error_suma.pdf", FACTURA_A_ERROR_SUMA),
        "factura_escaneada.pdf": crear_factura_pdf(
            carpeta / "factura_escaneada.pdf", variante(FACTURA_C, numero=88), ilegible=True
        ),
    }
    (carpeta / "archivo_roto.pdf").write_bytes(b"esto no es un PDF, se corto la descarga")
    return esperados
