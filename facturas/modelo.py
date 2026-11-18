"""Modelo de datos de una factura y conversión a/desde dict (JSON)."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from decimal import Decimal

from .importes import parse_fecha, parse_importe

CAMPOS_IMPORTE = (
    "neto_gravado",
    "no_gravado",
    "exento",
    "iva_21",
    "iva_10_5",
    "iva_27",
    "iva_otros",
    "percepciones",
    "total",
)
CAMPOS_FECHA = ("fecha", "vencimiento_cae")

# Código de comprobante AFIP -> (comprobante, letra)
CODIGOS_AFIP = {
    1: ("FACTURA", "A"),
    2: ("NOTA DE DEBITO", "A"),
    3: ("NOTA DE CREDITO", "A"),
    6: ("FACTURA", "B"),
    7: ("NOTA DE DEBITO", "B"),
    8: ("NOTA DE CREDITO", "B"),
    11: ("FACTURA", "C"),
    12: ("NOTA DE DEBITO", "C"),
    13: ("NOTA DE CREDITO", "C"),
    51: ("FACTURA", "M"),
    52: ("NOTA DE DEBITO", "M"),
    53: ("NOTA DE CREDITO", "M"),
}

ESTADO_OK = "ok"
ESTADO_REVISAR = "revisar"
ESTADO_ERROR = "error"


@dataclass
class Factura:
    archivo: str = ""
    hash: str = ""
    comprobante: str = ""  # FACTURA, NOTA DE CREDITO, NOTA DE DEBITO
    tipo: str = ""  # A, B, C o M
    codigo: str = ""  # código AFIP con 3 dígitos: 001, 006, 011...
    punto_venta: str = ""  # 5 dígitos
    numero: str = ""  # 8 dígitos
    fecha: date | None = None
    cuit_emisor: str = ""
    razon_social_emisor: str = ""
    cuit_receptor: str = ""
    razon_social_receptor: str = ""
    neto_gravado: Decimal = Decimal("0.00")  # en B y C: subtotal (el IVA no se discrimina)
    no_gravado: Decimal = Decimal("0.00")
    exento: Decimal = Decimal("0.00")
    iva_21: Decimal = Decimal("0.00")
    iva_10_5: Decimal = Decimal("0.00")
    iva_27: Decimal = Decimal("0.00")
    iva_otros: Decimal = Decimal("0.00")  # 5% y 2,5%
    percepciones: Decimal = Decimal("0.00")  # "Importe Otros Tributos" (percepciones IIBB, IVA, etc.)
    total: Decimal | None = None
    cae: str = ""
    vencimiento_cae: date | None = None
    estado: str = ESTADO_REVISAR
    origen: str = "reglas"  # reglas | ia
    observaciones: list[str] = field(default_factory=list)
    enviado: bool = False
    procesado_el: str = ""

    @property
    def iva_total(self) -> Decimal:
        return self.iva_21 + self.iva_10_5 + self.iva_27 + self.iva_otros

    @property
    def numero_completo(self) -> str:
        """Ej.: 'A-00003-00001234'."""
        if not (self.tipo and self.punto_venta and self.numero):
            return ""
        return f"{self.tipo}-{self.punto_venta}-{self.numero}"

    @property
    def clave(self) -> str:
        """Identifica el comprobante (para detectar la misma factura en dos PDF distintos)."""
        if not (self.cuit_emisor and self.numero_completo):
            return ""
        return f"{self.cuit_emisor}|{self.numero_completo}"

    def a_dict(self) -> dict:
        """Dict serializable a JSON (fechas ISO, importes como float con 2 decimales)."""
        datos: dict = {}
        for campo in fields(self):
            valor = getattr(self, campo.name)
            if isinstance(valor, Decimal):
                valor = float(valor)
            elif isinstance(valor, date):
                valor = valor.isoformat()
            elif isinstance(valor, list):
                valor = list(valor)
            datos[campo.name] = valor
        datos["iva_total"] = float(self.iva_total)
        datos["numero_completo"] = self.numero_completo
        return datos

    @classmethod
    def desde_dict(cls, datos: dict) -> "Factura":
        nombres = {c.name for c in fields(cls)}
        limpio = {k: v for k, v in datos.items() if k in nombres}
        for campo in CAMPOS_IMPORTE:
            if campo in limpio:
                importe = parse_importe(limpio[campo])
                if importe is None and campo != "total":
                    importe = Decimal("0.00")
                limpio[campo] = importe
        for campo in CAMPOS_FECHA:
            if campo in limpio:
                limpio[campo] = parse_fecha(limpio[campo])
        if "observaciones" in limpio and not isinstance(limpio["observaciones"], list):
            limpio["observaciones"] = [str(limpio["observaciones"])]
        return cls(**limpio)
