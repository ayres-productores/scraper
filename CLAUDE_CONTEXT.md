# Sistema Portal de Seguros - Contexto para Claude

> Este archivo proporciona contexto completo del sistema para sesiones futuras con Claude.
> **Leer este archivo al inicio de cada sesión de desarrollo.**

---

## Arquitectura de Alto Nivel

```
+------------------------+      +------------------------+
|     PORTAL SEGUROS     |      |    EXTRACTOR SERVER    |
|       (Flask App)      |      |    (Flask Standalone)  |
|     Puerto: 5000       |      |      Puerto: 5001      |
+------------------------+      +------------------------+
          |                               |
          |     Comparten BD SQLite       |
          +---------------+---------------+
                          |
                          v
              +------------------------+
              |   portal_seguros.db    |
              |      (SQLite WAL)      |
              +------------------------+
```

---

## 1. PORTAL SEGUROS (Proyecto Principal)

### Ubicacion
`C:\Users\César\portal_seguros\`

### Stack
- **Backend**: Flask 3.0 + SQLAlchemy 3.1.1
- **BD**: SQLite (WAL mode) / PostgreSQL (prod)
- **Auth**: Flask-Login + Bcrypt
- **Encrypt**: Fernet AES-256

### Estructura de Carpetas
```
portal_seguros/
├── app/
│   ├── __init__.py          # create_app() factory
│   ├── config.py            # Config dev/prod
│   ├── models.py            # 24 modelos SQLAlchemy
│   ├── auth/                # Login, logout, perfil
│   ├── main/                # Dashboard, archivos
│   ├── admin/               # CRUD usuarios, logs
│   ├── distribucion/        # CRM principal
│   │   ├── routes.py        # Clientes, polizas, envios
│   │   └── whatsapp_sender.py
│   ├── api/                 # Webhook WhatsApp
│   ├── services/            # Logica de negocio
│   ├── tasks/               # Alertas, evaluacion clientes
│   └── utils/               # encryption, db_session
├── run.py                   # Punto de entrada
└── .env                     # Configuracion
```

### Modelos Principales (models.py)

| Modelo | Tabla | Uso |
|--------|-------|-----|
| Usuario | usuarios | Auth, roles (admin/poweruser/collaborator) |
| Cliente | clientes | CRM - contactos, WhatsApp, documento |
| PolizaCliente | polizas_cliente | Polizas con 100+ campos |
| CuentaGmail | cuentas_gmail | Cuentas IMAP para extraccion |
| ArchivoDescargado | archivos_descargados | PDFs con matching cliente |
| EnvioWhatsApp | envios_whatsapp | Tracking envios (sent/delivered/read) |
| AlertaVencimiento | alertas_vencimiento | Alertas automaticas |

### Endpoints Clave

```
/auth/login                    - Autenticacion
/dashboard                     - Panel principal
/archivos                      - PDFs descargados
/distribucion/clientes         - CRM clientes
/distribucion/cliente/<id>     - Detalle cliente
/distribucion/poliza/<id>      - Detalle poliza
/distribucion/enviar-poliza    - Enviar por WhatsApp
/api/whatsapp/webhook          - Callback Meta (HMAC)
```

### Integraciones
1. **WhatsApp Business API** (Meta) - Envio + tracking
2. **Gmail IMAP** - Extraccion de polizas (delegado a extractor_server)

---

## 2. EXTRACTOR SERVER (Servidor Independiente)

### Ubicacion
`C:\Users\César\extractor_server\`

### Proposito
Servidor separado para extraccion de PDFs de Gmail.
Fue refactorizado del portal principal (commit 79f11b6).

### Stack
- **Backend**: Flask standalone
- **BD**: Misma SQLite del portal
- **IMAP**: imaplib con SSL
- **PDF**: PyMuPDF (fitz)

### Estructura de Carpetas
```
extractor_server/
├── app.py               # Rutas Flask + endpoints API
├── run.py               # Punto de entrada
├── config.py            # Configuracion
├── models.py            # Modelos compartidos
├── db.py                # Conexion BD
├── encryption.py        # Descifrar credenciales Gmail
├── scanner.py           # Motor IMAP
├── extractor.py         # Extraccion datos PDF
├── consolidator.py      # Guardar en BD
├── bot_asignacion.py    # Asignacion automatica
├── estrategias/         # Estrategias por compania
│   ├── base.py
│   ├── generica.py
│   ├── berkley.py
│   ├── liderar.py
│   └── registro.py
└── templates/
    ├── dashboard.html
    ├── escaneo.html
    ├── debug_steps.html    # Debugger step-by-step
    └── revision_poliza.html
```

### Endpoints Principales

```
/                          - Dashboard
/escaneo                   - Escaneo completo
/debug                     - Debugger step-by-step (3 pasos)
/revision                  - Revision de polizas

/api/cuentas               - Listar cuentas Gmail
/api/debug/session         - Crear sesion debug
/api/debug/connect/<id>    - Conectar IMAP
/api/debug/search/<id>     - Buscar correos
/api/debug/download/<id>   - Descargar PDF
/api/debug/extract-text    - Extraer texto
/api/debug/detect-company  - Detectar compania
/api/debug/extract-data    - Extraer datos poliza
/api/debug/consolidate     - Guardar en BD
```

### Debugger Step-by-Step (/debug)

**Flujo actual (3 pasos):**
```
Paso 1: Seleccionar Cuenta + Conectar IMAP
        ├── Seleccionar cuenta Gmail
        ├── Crear sesion debug
        └── Conectar a imap.gmail.com:993 (automatico)

Paso 2: Buscar Correos
        ├── Configurar rango fechas
        └── Buscar correos con PDFs

Paso 3: Procesar PDFs
        ├── Descargar
        ├── Extraer texto
        ├── Detectar compania
        └── Consolidar (guardar)
```

### Estrategias de Extraccion

El sistema usa estrategias especificas por compania:
- `EstrategiaGenerica`: Fallback para companias desconocidas
- `EstrategiaBerkley`: Berkley Argentina
- `EstrategiaLiderar`: Liderar Seguros

Cada estrategia implementa:
- `extraer_datos(texto)` -> dict con campos poliza
- `calcular_confianza(datos)` -> float 0-1

---

## 3. BASE DE DATOS COMPARTIDA

### Archivo
`C:\Users\César\portal_seguros\portal_seguros.db`

### Configuracion SQLite
```python
PRAGMA busy_timeout=120000  # 120s timeout
PRAGMA journal_mode=WAL     # Write-Ahead Logging
PRAGMA synchronous=NORMAL   # Balance seguridad/rendimiento
```

### Tablas Principales

```sql
usuarios              -- Autenticacion
cuentas_gmail         -- Cuentas IMAP (password encriptado)
escaneos              -- Historial de escaneos
archivos_descargados  -- PDFs descargados
clientes              -- CRM contactos
polizas_cliente       -- Polizas
envios_whatsapp       -- Tracking envios
alertas_vencimiento   -- Alertas automaticas
```

---

## 4. SEGURIDAD

### Encriptacion de Credenciales
```python
# Formato en BD: {salt}:{encrypted_data}
# Algoritmo: Fernet (AES-256)
# Salt: unico por cuenta
```

### Variables de Entorno (.env)
```bash
SECRET_KEY=<64 hex chars>
ENCRYPTION_KEY=<32 chars exactos>
WHATSAPP_APP_SECRET=<Meta app secret>
WHATSAPP_API_KEY=<Bearer token>
WHATSAPP_PHONE_ID=<phone ID>
```

### Webhook WhatsApp
- Validacion HMAC-SHA256
- Header: `X-Hub-Signature-256`

---

## 5. FLUJO DE TRABAJO TIPICO

### Extraer Polizas
```
1. Usuario selecciona cuenta Gmail (extractor_server/debug)
2. Sistema conecta IMAP automaticamente
3. Busca correos con PDFs (rango fechas)
4. Descarga y procesa cada PDF:
   - Extrae texto (PyMuPDF)
   - Detecta compania (regex + dominio)
   - Extrae datos (estrategia especifica)
   - Guarda en BD (consolidar)
5. PDFs quedan en archivos_descargados
```

### Enviar Poliza
```
1. Usuario va a /distribucion/cliente/<id>
2. Selecciona poliza y hace clic "Enviar"
3. Sistema envia via WhatsApp Business API
4. Webhook recibe estados (sent/delivered/read)
5. Al recibir "read", poliza se marca como confirmada
```

---

## 6. ARCHIVOS DE CONFIGURACION

### Portal (.env.example)
```
C:\Users\César\portal_seguros\.env.example
```

### Extractor
```
C:\Users\César\extractor_server\config.py
```

---

## 7. COMANDOS UTILES

### Iniciar Portal
```bash
cd C:\Users\César\portal_seguros
python run.py
# Puerto 5000
```

### Iniciar Extractor
```bash
cd C:\Users\César\extractor_server
python run.py
# Puerto 5001
```

---

## 8. NOTAS DE DESARROLLO

### Cambios Recientes
- **Commit 79f11b6**: Extractor separado a servidor independiente
- **Debugger**: Reducido de 4 a 3 pasos (conexion IMAP integrada al paso 1)

### Patrones de Codigo
- Services pattern en `/services/`
- Context managers para conexiones IMAP
- Thread-safe sessions con `thread_session(app)`
- Deduplicacion de PDFs por SHA-256

### Consideraciones
- SQLite con WAL permite lecturas concurrentes
- Cada cuenta Gmail tiene salt unico para encriptacion
- Webhook WhatsApp requiere HTTPS en produccion
