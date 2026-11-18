# Facturas PDF a Excel (AFIP)

Lee facturas electrónicas argentinas en PDF y las pasa a Excel, CSV, JSON o a un ERP por webhook.
Pensado para pymes y estudios contables que hoy cargan a mano las facturas de proveedores.

## Qué resuelve

- Extrae de cada factura AFIP: tipo (A/B/C/M), código, punto de venta, número, fecha, CUIT y razón social
  del emisor y del receptor, neto gravado, no gravado, exento, IVA 21% / 10,5% / 27% (y 5% / 2,5%),
  percepciones (importe otros tributos), total, CAE y vencimiento del CAE.
- Controla cada factura:
  - dígito verificador de los CUIT;
  - que neto + IVA + percepciones dé el total (con tolerancia configurable);
  - CAE de 14 dígitos y vencimiento no anterior a la fecha;
  - que una factura A tenga CUIT del receptor y IVA discriminado, y que una B/C no lo tenga;
  - que no se cargue dos veces el mismo comprobante.
- Las reglas (pdfplumber + expresiones regulares) resuelven los PDF generados por AFIP y la mayoría de
  los sistemas de facturación. Para los que no entiende (escaneados, formatos raros) puede usar IA
  (Claude de Anthropic) y valida el JSON que devuelve. Sin clave de IA, esos PDF quedan marcados para revisar.
- Procesa una carpeta o la vigila. No repite archivos ya procesados (hash SHA-256) y mueve cada PDF a
  `procesadas/` o `errores/`.
- Exporta un Excel con tres hojas: **Facturas** (las que están bien), **Revisar** (las dudosas, con el motivo)
  y **Resumen** (totales). También exporta CSV y JSON y puede mandar cada factura a una API/ERP (POST con reintentos).

Usa el PDF de AFIP con ORIGINAL / DUPLICADO / TRIPLICADO en el mismo archivo sin contar tres veces la misma factura.

## Pedidos de Workana que cubre

- "Automatizar con IA la carga de facturas de proveedores para una pyme"
- "Script en Python que lea facturas PDF y las pase a Excel"
- "Extraer datos de facturas AFIP (CUIT, CAE, IVA) a una planilla para el estudio contable"
- "Cargar facturas de compra en el ERP / Tango / sistema propio desde los PDF que llegan por mail"
- "Armar el libro IVA compras a partir de PDFs"
- "OCR de facturas escaneadas con IA y validación de importes"

## Instalación

Requiere Python 3.12.

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

(En Linux/Mac: `.venv/bin/python` en lugar de `.venv/Scripts/python.exe`.)

## Demo en 1 minuto (sin cuentas ni claves)

```
.venv/Scripts/python.exe -m facturas demo
```

Genera seis PDF de ejemplo en `demo/entrada/`: una factura A (con duplicado y triplicado), una B, una C, una A
con un error de suma, una "escaneada" sin texto y un archivo roto. Los procesa y deja en `demo/salida/` el
`facturas.xlsx`, `facturas.csv` y `facturas.json`. La IA y el ERP están **simulados** (no hay conexión a internet):
la IA simulada "lee" la factura escaneada y el ERP simulado recibe las facturas que quedaron bien.
Al final vuelve a dejar la factura A con otro nombre para mostrar que no se carga dos veces.

Resultado esperado: 4 OK, 1 para revisar (error de suma), 1 con error (archivo roto), 4 enviadas al ERP.

Con una clave real en `.env`, `--ia-real` usa la API de Anthropic en lugar de la simulada.

## Uso

```
# Procesar una carpeta y generar el Excel
.venv/Scripts/python.exe -m facturas procesar entrada/ --excel salida.xlsx

# Excel + CSV + JSON
.venv/Scripts/python.exe -m facturas procesar entrada/ --excel salida.xlsx --csv salida.csv --json salida.json

# Vigilar la carpeta (revisa cada INTERVALO_VIGILAR segundos y regenera el Excel cuando hay nuevas)
.venv/Scripts/python.exe -m facturas procesar entrada/ --excel salida.xlsx --vigilar

# Otras opciones
--sin-mover      no mueve los PDF
--forzar         reprocesa aunque ya estén en el registro (por ejemplo, después de cargar la clave de IA)
--sin-ia         no usa la IA aunque haya clave
--solo-nuevas    el Excel trae solo lo procesado en esta corrida (por defecto trae todo el registro)
--registro RUTA  registro de procesados distinto (útil para tener uno por cliente)
-v               logs detallados

# Utilidades
.venv/Scripts/python.exe -m facturas cuit 30-71234567-1
.venv/Scripts/python.exe -m facturas ejemplos carpeta/
```

Estados de cada factura:

| Estado    | Significa                                                        | Dónde queda            |
|-----------|------------------------------------------------------------------|------------------------|
| `ok`      | se leyó todo y pasó todos los controles                          | hoja Facturas, `procesadas/` |
| `revisar` | se leyó pero algo no cierra (suma, CUIT, falta CAE, duplicado...) | hoja Revisar, `procesadas/`  |
| `error`   | el archivo no se pudo abrir como PDF                             | hoja Revisar, `errores/`     |

## Configuración

Copiar `.env.example` a `.env` y completar. Todas las variables tienen valor por defecto; ninguna es obligatoria.

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | clave de la API de Anthropic. Vacía = sin IA |
| `ANTHROPIC_MODELO` | modelo (por defecto `claude-haiku-5-5`, el más barato) |
| `IA_HABILITADA` | `false` para apagar la IA sin borrar la clave |
| `REGISTRO_PATH` | JSON con los hashes y datos ya procesados |
| `CARPETA_PROCESADAS`, `CARPETA_ERRORES` | destino de los PDF (por defecto dentro de la entrada) |
| `TOLERANCIA_SUMA` | diferencia aceptada en el control de suma (pesos) |
| `WEBHOOK_URL`, `WEBHOOK_TOKEN` | API/ERP que recibe cada factura (POST JSON, `Authorization: Bearer`) |
| `WEBHOOK_REINTENTOS` | reintentos ante 5xx, 429 o error de red (espera 1 s, 2 s, 4 s...) |
| `WEBHOOK_ENVIAR_REVISAR` | también manda las dudosas |
| `CSV_SEPARADOR` | `;` por defecto (Excel en español) |

El webhook manda el header `Idempotency-Key` con el hash del PDF para que el ERP pueda descartar repetidos.

### Costo de la IA

Solo se llama a la IA para los PDF que las reglas no entienden. Con un modelo chico como Haiku el costo por
factura es de centavos de dólar; conviene confirmarlo con los precios vigentes de Anthropic antes de cotizar.

## Pruebas

```
.venv/Scripts/python.exe -m pytest
```

79 pruebas, sin internet y sin claves: generan facturas PDF con reportlab (A, B, C, error de suma, escaneada,
archivo roto, CUIT inválido, número con columnas mezcladas) y verifican campo por campo lo extraído.
La API de Anthropic y el ERP se simulan con `httpx.MockTransport` (`facturas/simulador.py`).

## Despliegue

- **PC del cliente (lo más común)**: instalar Python 3.12, copiar la carpeta, crear el `.venv` y programar
  `python -m facturas procesar <carpeta> --excel <ruta>` con el Programador de tareas de Windows (por ejemplo,
  cada hora), o dejar `--vigilar` corriendo como servicio con NSSM.
- **Carpeta compartida (OneDrive / Google Drive / red)**: apuntar la entrada a la carpeta sincronizada donde
  el cliente o su contador deja los PDF, y la salida a otra carpeta compartida.
- **Servidor Linux**: `systemd` con `--vigilar`, o `cron` con `procesar`. El registro y las salidas tienen que
  estar en un disco persistente.

## Estructura

```
facturas/
  extractor_reglas.py   pdfplumber + regex (acá se agregan formatos nuevos)
  extractor_ia.py       respaldo con Claude por httpx, valida el JSON
  validaciones.py       controles (CUIT, sumas, CAE, tipo)
  procesador.py         carpeta, hash, registro, mover, vigilar
  exportar.py           Excel / CSV / JSON
  webhook.py            envío al ERP con reintentos
  config.py             variables de entorno
  cuit.py, importes.py  utilidades (dígito verificador, "1.234,56" -> Decimal)
  ejemplos.py           genera facturas PDF de ejemplo
  simulador.py          IA y ERP falsos para demo y pruebas
  cli.py                línea de comandos
tests/                  pruebas (pytest)
```

## CÓMO ADAPTARLO A UN CLIENTE

Checklist, con el archivo a tocar y el tiempo estimado:

- [ ] **Pedir 10-20 PDF reales** de los proveedores más frecuentes y correr
      `procesar muestras/ --sin-mover --solo-nuevas -v`. Ver qué queda en la hoja Revisar. *(30 min)*
- [ ] **Formatos que no reconoce**: agregar etiquetas o patrones en `facturas/extractor_reglas.py`
      (`ETIQUETAS_IMPORTE`, `RE_NUMERO`, `RE_CUIT`...) y una prueba con el texto en
      `tests/test_extractor_reglas.py` (ver `test_texto_con_formatos_alternativos`). *(30-60 min por formato raro)*
- [ ] **Columnas del Excel** (orden, nombres, columnas propias del cliente como "Centro de costo"):
      `COLUMNAS` en `facturas/exportar.py`. *(15-30 min)*
- [ ] **Formato de importación del ERP** (Tango, Bejerman, Xubio, Colppy, libro IVA compras): agregar una
      función de exportación en `facturas/exportar.py` y su opción en `facturas/cli.py`. *(1-2 h)*
- [ ] **Envío a API/ERP**: `WEBHOOK_URL` y `WEBHOOK_TOKEN` en `.env`. Si el ERP espera otro JSON,
      armarlo en `EnviadorWebhook.enviar` (`facturas/webhook.py`). *(30-60 min)*
- [ ] **Campos nuevos** (orden de compra, moneda, cotización, impuestos internos): agregarlos en
      `facturas/modelo.py`, la regla en `extractor_reglas.py`, la clave en `INSTRUCCION` de
      `extractor_ia.py` y la columna en `exportar.py`. *(30 min por campo)*
- [ ] **Controles propios** (proveedores autorizados, CUIT del receptor debe ser el del cliente, montos máximos):
      `facturas/validaciones.py`. *(15-30 min)*
- [ ] **IA**: crear la clave en la cuenta del cliente (que pague él el consumo) y cargarla en `.env`.
      Probar con 2-3 escaneados reales. *(15 min)*
- [ ] **Carpetas y programación**: `.env` (carpetas, registro) y la tarea programada o servicio. *(30 min)*
- [ ] **Entrega**: correr las pruebas, dejar un Excel de ejemplo con sus facturas y una nota de uso de una página. *(30 min)*

Total típico: 2-6 horas según cuántos formatos raros y si hay integración con ERP.

## Qué preguntarle al cliente

1. ¿Cuántas facturas por mes son y de cuántos proveedores distintos? ¿Me pasás 10-20 de ejemplo?
2. ¿Los PDF son los que genera AFIP o los sistemas de facturación, o también hay escaneados o fotos?
3. ¿Cómo llegan las facturas (mail, carpeta compartida, WhatsApp) y dónde querés que quede el resultado?
4. ¿Qué columnas necesitás en el Excel, y en qué orden? ¿Hay un formato de importación de tu ERP o del estudio contable?
5. ¿Hay que cargarlas en algún sistema (Tango, Xubio, Colppy, propio)? ¿Tiene API o importa archivos?
6. ¿Qué hacemos con las dudosas: te avisamos, quedan en una hoja aparte, las revisa el contador?
7. ¿Necesitás también notas de crédito/débito, facturas en dólares o facturas M?
8. ¿Querés usar IA para los escaneados? Necesita una clave de Anthropic a tu nombre (el costo es bajo y por uso).

## Limitaciones conocidas

- Las reglas están probadas con PDF que siguen el formato de AFIP. Otros sistemas de facturación pueden
  necesitar patrones nuevos (ver la checklist).
- Los escaneados y las fotos dependen de la IA; sin clave quedan para revisar.
- Las facturas en moneda extranjera se leen, pero no se guarda la moneda ni la cotización.
- Se usa IA (Claude) como respaldo y fue programado con ayuda de herramientas de IA.

## Licencia

MIT - markbackend
