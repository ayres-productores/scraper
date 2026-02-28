# Portal de Seguros - Análisis de Ingeniería Inversa

> **Generado**: 2026-02-17
> **Stack**: Flask 3.0 + SQLAlchemy + SQLite/PostgreSQL
> **Propósito**: CRM completo para productores de seguros con extracción automática de pólizas

---

## Arquitectura General

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PORTAL DE SEGUROS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │   Frontend   │   │   Backend    │   │   Workers    │   │  Integraciones│ │
│  │   (Jinja2)   │   │   (Flask)    │   │  (Threads)   │   │   Externas   │  │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘  │
│         │                  │                  │                  │          │
│         ▼                  ▼                  ▼                  ▼          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        SQLAlchemy ORM                               │    │
│  │                    (24 modelos de datos)                            │    │
│  └─────────────────────────────────┬───────────────────────────────────┘    │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                  SQLite (dev) / PostgreSQL (prod)                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Estructura de Directorios

```
portal_seguros/
├── app/
│   ├── __init__.py          # Factory Flask, create_app()
│   ├── config.py            # Config dev/prod
│   ├── models.py            # 24 modelos (2656 líneas)
│   │
│   ├── auth/                # Autenticación
│   │   └── routes.py        # login, logout, perfil
│   │
│   ├── main/                # Dashboard principal
│   │   └── routes.py        # archivos, estadísticas
│   │
│   ├── admin/               # Panel administración
│   │   └── routes.py        # usuarios, logs, config
│   │
│   ├── distribucion/        # CRM (módulo principal)
│   │   ├── routes.py        # clientes, pólizas, envíos
│   │   └── whatsapp_sender.py
│   │
│   ├── api/                 # APIs externas
│   │   └── routes.py        # webhook WhatsApp
│   │
│   ├── services/            # Lógica de negocio
│   │   ├── escaneo_service.py
│   │   ├── usuario_service.py
│   │   └── archivo_service.py
│   │
│   ├── tasks/               # Tareas programadas
│   │   ├── alertas.py       # Vencimientos
│   │   └── clientes_actuales.py
│   │
│   ├── utils/               # Utilidades
│   │   ├── encryption.py    # AES-256 + Fernet
│   │   ├── db_session.py    # Thread-safe sessions
│   │   └── task_progress.py # Tracking de progreso
│   │
│   ├── static/              # CSS, JS, uploads
│   └── templates/           # Jinja2
│
├── archivos_usuarios/       # PDFs descargados
├── polizas_backup/          # Backups permanentes
├── repositorio_archivos/    # Deduplicación central
│
├── run.py                   # Punto de entrada
├── requirements.txt         # Dependencias
└── .env                     # Configuración
```

---

## Modelos de Datos (24 entidades)

### Diagrama de Relaciones

```
                    ┌─────────────────┐
                    │     Usuario     │
                    │   (auth base)   │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  CuentaGmail  │   │    Cliente    │   │ LogActividad  │
│ (extracción)  │   │    (CRM)      │   │  (auditoría)  │
└───────┬───────┘   └───────┬───────┘   └───────────────┘
        │                   │
        ▼                   ▼
┌───────────────┐   ┌───────────────┐
│   Escaneo     │   │ PolizaCliente │◄──────────────────┐
│  (proceso)    │   │  (producto)   │                   │
└───────┬───────┘   └───────┬───────┘                   │
        │                   │                           │
        ▼                   ├───────────────┬───────────┤
┌───────────────┐           ▼               ▼           ▼
│ArchivoDescarg.│   ┌───────────────┐ ┌─────────┐ ┌──────────┐
│   (PDF)       │   │ EnvioWhatsApp │ │  Pago   │ │Siniestro │
└───────────────┘   │  (tracking)   │ │ (cuota) │ │          │
                    └───────────────┘ └─────────┘ └──────────┘
```

### Entidades Principales

| Modelo | Tabla | Propósito |
|--------|-------|-----------|
| `Usuario` | usuarios | Autenticación, roles (admin/poweruser/collaborator) |
| `Cliente` | clientes | CRM - contactos con WhatsApp, email, documento |
| `PolizaCliente` | polizas_cliente | Pólizas con 100+ campos (vehículos, inmuebles, vida) |
| `CuentaGmail` | cuentas_gmail | Cuentas para extracción IMAP |
| `Escaneo` | escaneos | Procesos de descarga de PDFs |
| `ArchivoDescargado` | archivos_descargados | PDFs con matching automático de cliente |
| `EnvioWhatsApp` | envios_whatsapp | Envíos con tracking (sent/delivered/read) |
| `AlertaVencimiento` | alertas_vencimiento | Alertas automáticas de vencimientos |
| `Pago` | pagos | Cuotas y plan de pagos |
| `Siniestro` | siniestros | Registro de siniestros |
| `Inmobiliaria` | inmobiliarias | Administradores de propiedades |

---

## Flujos de Negocio Principales

### 1. Extracción de Pólizas (Gmail → PDF → Cliente)

```
┌─────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐
│  Gmail  │───▶│  IMAP    │───▶│  Filter  │───▶│  PyMuPDF │───▶│ Cliente │
│ (cuenta)│    │ Connect  │    │ Dominios │    │ Extract  │    │ Matching│
└─────────┘    └──────────┘    └──────────┘    └──────────┘    └─────────┘
     │                                              │               │
     └──────────────────────────────────────────────┴───────────────┘
                              Deduplicación SHA-256
```

**Código relevante**: `app/services/escaneo_service.py`

### 2. Envío de Pólizas por WhatsApp

```
┌─────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐
│ Póliza  │───▶│  Cola    │───▶│ WhatsApp │───▶│ Webhook  │───▶│ Update  │
│ (PDF)   │    │ Envíos   │    │ API Meta │    │ Callback │    │ Estado  │
└─────────┘    └──────────┘    └──────────┘    └──────────┘    └─────────┘
                    │                               │
                    │         ┌──────────────┐      │
                    └────────▶│  Status:     │◀─────┘
                              │  sent        │
                              │  delivered   │
                              │  read ────────▶ Póliza confirmada
                              └──────────────┘
```

**Código relevante**:
- `app/distribucion/whatsapp_sender.py` (envío)
- `app/api/routes.py` (webhook)

### 3. Alertas Automáticas

```
┌──────────────────────────────────────────────────────────────┐
│                     Task: generar_alertas                    │
└──────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Vencimiento  │    │  Vencimiento  │    │   Cliente     │
│   Pólizas     │    │    Pagos      │    │  No Actual    │
│ (30,15,7 días)│    │  (5 días)     │    │ (180 días)    │
└───────────────┘    └───────────────┘    └───────────────┘
```

**Código relevante**: `app/tasks/alertas.py`, `app/tasks/clientes_actuales.py`

---

## Rutas Principales

### Autenticación (`/auth`)
```
GET/POST  /login                    → Login con rate limiting
GET       /logout                   → Cerrar sesión
GET/POST  /cambiar-contrasena-obligatorio → Cambio forzado
GET/POST  /perfil                   → Editar perfil
```

### Dashboard (`/`)
```
GET  /                              → Redirect a dashboard
GET  /dashboard                     → Panel principal
GET  /archivos                      → PDFs por compañía
GET  /archivo/<id>/descargar        → Descargar PDF
```

### Administración (`/admin`)
```
GET  /admin                         → Panel admin
GET  /admin/usuarios                → CRUD usuarios
GET  /admin/logs                    → Auditoría
```

### CRM - Distribución (`/distribucion`)
```
GET  /distribucion/                 → Dashboard CRM
GET  /distribucion/clientes         → Listado clientes

POST /distribucion/clientes/nuevo   → Crear cliente
GET  /distribucion/cliente/<id>     → Detalle cliente
POST /distribucion/cliente/<id>/editar

POST /distribucion/asignar-poliza   → Crear póliza
POST /distribucion/poliza/<id>/confirmar
POST /distribucion/enviar-poliza/<id> → Enviar WhatsApp

GET  /distribucion/alertas          → Dashboard alertas
POST /distribucion/alerta/<id>/resolver

POST /distribucion/analizar-pdf     → OCR inteligente
GET  /distribucion/buscar-polizas   → Búsqueda avanzada
```

### API WhatsApp (`/api`)
```
GET/POST  /api/whatsapp/webhook     → Callback de Meta
                                      (valida HMAC-SHA256)
```

---

## Integraciones Externas

### 1. WhatsApp Business API (Meta)

```python
# Endpoint
POST https://graph.facebook.com/v17.0/{phone_id}/messages

# Headers
Authorization: Bearer {WHATSAPP_API_KEY}
Content-Type: application/json

# Webhook validation
X-Hub-Signature-256: sha256={HMAC-SHA256(body, app_secret)}
```

**Estados de mensaje**: `sent` → `delivered` → `read` → `failed`

### 2. Gmail IMAP

```python
# Conexión
imap.gmail.com:993 (IMAP4_SSL)

# Autenticación
App Password (16 chars)
Encriptado: Fernet + AES-256 + salt único
```

### 3. WhatsApp Web Service (opcional)

```
URL: http://localhost:3001
Endpoints:
  GET  /session/{user_id}/status
  POST /session/{user_id}/init
  POST /session/{user_id}/disconnect
```

---

## Seguridad

### Autenticación
- **Hash**: Bcrypt
- **Rate limiting**: 5 intentos → 15 min bloqueo
- **CSRF**: Flask-WTF automático
- **Sesiones**: Flask-Login + cookies seguras

### Roles
| Rol | Acceso |
|-----|--------|
| `admin` | Todo |
| `poweruser` | CRM + crear collaborators |
| `collaborator` | CRM básico |

### Encriptación
```python
# Credenciales Gmail
Fernet(key) + salt único por cuenta
AES-256 en modo CBC

# Almacenamiento
{salt}:{encrypted_data}  # formato en BD
```

### Webhook Validation
```python
# HMAC-SHA256
expected = hmac.new(app_secret, body, sha256).hexdigest()
actual = request.headers['X-Hub-Signature-256'].replace('sha256=', '')
hmac.compare_digest(expected, actual)
```

---

## Configuración (.env)

```bash
# Seguridad (CRÍTICOS)
SECRET_KEY=<64 hex chars>
ENCRYPTION_KEY=<32 chars exactos>
WHATSAPP_APP_SECRET=<app secret de Meta>

# WhatsApp Business API
WHATSAPP_API_KEY=<bearer token>
WHATSAPP_PHONE_ID=<phone number ID>
WHATSAPP_VERIFY_TOKEN=<webhook verify>

# WhatsApp Web Service (opcional)
WHATSAPP_SERVICE_URL=http://localhost:3001
WHATSAPP_SERVICE_TIMEOUT=30

# Base de datos
DATABASE_URL=sqlite:///portal_seguros.db
# DATABASE_URL=postgresql://user:pass@host/db

# Modo
FLASK_ENV=development
FLASK_DEBUG=1
```

---

## Workers y Tareas Background

### Thread 1: Procesador WhatsApp
```python
# app/distribucion/whatsapp_sender.py
iniciar_procesador_whatsapp(app)
# Cola de envíos pendientes
# Reintentos con backoff exponencial
```

### Thread 2: Alertas de Vencimiento
```python
# app/tasks/alertas.py
generar_alertas_vencimiento_polizas(usuario_id, [30, 15, 7])
generar_alertas_vencimiento_pagos(usuario_id, 5)
```

### Thread 3: Evaluación Clientes
```python
# app/tasks/clientes_actuales.py
evaluar_clientes_actuales(usuario_id)
# Cliente actual = comunicación 180 días + póliza 1 año
```

### Thread 4: Sincronización
```python
# app/__init__.py
sincronizar_archivos(session)
# Elimina registros de PDFs huérfanos
```

---

## Almacenamiento de Archivos

```
archivos_usuarios/          # PDFs por usuario
  {usuario_id}/
    {fecha}/
      {archivo}.pdf

polizas_backup/             # Backup permanente
  {poliza_id}/
    {nombre}.pdf

repositorio_archivos/       # Deduplicación central
  ab/                       # hash[0:2]
    cd1234ef/               # hash[0:8]
      original_name.pdf
```

**Deduplicación**: SHA-256 + contador de referencias

---

## Puntos de Entrada

### Desarrollo
```bash
python run.py
# Puerto: 5000
# Debug: activado
# Reloader: activado
```

### Producción
```bash
# Con Waitress
waitress-serve --port=5000 app:create_app

# Como ejecutable (PyInstaller)
./portal_seguros.exe
# Auto-detecta paths relativos
```

---

## Credenciales por Defecto

```
Usuario: admin@empresa.com
Password: CambiarEnPrimerLogin123!
Acción: Debe cambiar en primer login
```

---

## Dependencias Críticas

| Paquete | Versión | Uso |
|---------|---------|-----|
| Flask | 3.0.0 | Framework web |
| SQLAlchemy | 3.1.1 | ORM |
| Flask-Login | 0.6.3 | Sesiones |
| Flask-Bcrypt | 1.0.1 | Hash passwords |
| cryptography | 41.0.7 | AES-256 |
| PyMuPDF | 1.23.8 | Parsing PDFs |
| requests | - | HTTP client |
| Waitress | 2.1.2 | Server prod |

---

## Características Técnicas Destacadas

1. **Deduplicación inteligente** - SHA-256 con contador de referencias
2. **Matching fuzzy** - Nombre (similitud) + documento (exacto)
3. **Lazy-loading** - Cliente matching bajo demanda en API
4. **Encriptación con salt** - Cada cuenta Gmail tiene salt único
5. **WAL mode SQLite** - Múltiples lectores simultáneos
6. **Thread-safe sessions** - Contextos independientes para workers
7. **HMAC webhooks** - Previene inyección de datos
8. **Logs estructurados** - JSON para monitoreo
9. **TaskStore con TTL** - Limpieza automática (1 hora)
10. **Sync automático** - Elimina huérfanos al iniciar

---

## Resumen Ejecutivo

**Portal de Seguros** es un CRM especializado para productores de seguros que:

1. **Extrae automáticamente** pólizas de correos Gmail
2. **Parsea PDFs** con OCR inteligente (PyMuPDF)
3. **Hace matching** automático con clientes existentes
4. **Envía pólizas** por WhatsApp Business API
5. **Trackea entregas** (sent → delivered → read)
6. **Genera alertas** de vencimientos automáticamente
7. **Gestiona pagos** con plan de cuotas
8. **Registra siniestros** y seguimiento
9. **Notifica inmobiliarias** sobre pólizas de propiedades

Sistema robusto con seguridad empresarial, threads background, y arquitectura lista para producción.
