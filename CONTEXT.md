# Portal de Seguros - Contexto del Proyecto

## Resumen Ejecutivo

Aplicación Flask para gestión de pólizas de seguros:
- Escaneo automático de correos Gmail descargando PDFs
- Gestión de clientes y pólizas (CRM)
- Distribución vía WhatsApp con tracking de estados
- Alertas automáticas de vencimientos
- Multi-usuario con roles (admin, poweruser, collaborator)

---

## Estructura de Directorios

```
portal_seguros/
├── app/
│   ├── __init__.py              # Factory Flask
│   ├── config.py                # Configuración
│   ├── models.py                # Modelos SQLAlchemy (~2600 líneas)
│   │
│   ├── auth/                    # Autenticación
│   │   ├── forms.py
│   │   └── routes.py            # login, logout, perfil
│   │
│   ├── main/                    # Dashboard y archivos
│   │   └── routes.py
│   │
│   ├── admin/                   # Panel administración
│   │   └── routes.py            # Gestión usuarios
│   │
│   ├── distribucion/            # CRM y distribución
│   │   ├── routes.py            # Clientes, pólizas, envíos
│   │   ├── forms.py
│   │   ├── asignacion_service.py
│   │   ├── whatsapp_sender.py
│   │   └── backup_polizas.py
│   │
│   ├── api/                     # APIs
│   │   ├── routes.py
│   │   └── whatsapp_webhook.py  # Webhook Meta
│   │
│   ├── services/                # Servicios
│   │   ├── archivo_service.py
│   │   ├── escaneo_service.py
│   │   └── usuario_service.py
│   │
│   ├── utils/                   # Utilidades
│   │   ├── database_gateway.py  # Gateway BD thread-safe
│   │   ├── db_session.py
│   │   ├── encryption.py        # Encriptación credenciales
│   │   ├── decoradores.py
│   │   ├── structured_logger.py
│   │   └── task_progress.py
│   │
│   ├── tasks/                   # Tareas background
│   │   ├── alertas.py
│   │   └── clientes_actuales.py
│   │
│   ├── templates/               # Jinja2 templates
│   └── static/                  # CSS, JS
│
├── run.py                       # Entry point desarrollo
├── servidor_lan.py              # Servidor LAN
├── config.py                    # Config centralizada
├── requirements.txt
└── scripts/                     # Migraciones y utilidades
```

---

## Blueprints y Rutas Principales

### auth (Autenticación)
- `GET/POST /login` - Inicio de sesión
- `GET /logout` - Cierre de sesión
- `GET/POST /perfil` - Gestión perfil

### main (Principal)
- `GET /` - Redirige a dashboard
- `GET /dashboard` - Panel principal
- `GET /archivos` - Listado PDFs descargados

### admin (Administración)
- `GET /admin/` - Panel admin
- `GET /admin/usuarios` - CRUD usuarios
- `GET /admin/logs` - Logs actividad

### distribucion (CRM)
- `GET/POST /distribucion/clientes` - CRUD clientes
- `GET/POST /distribucion/polizas` - CRUD pólizas
- `GET/POST /distribucion/envios` - Envíos WhatsApp
- `GET /distribucion/alertas` - Alertas vencimiento
- `GET /distribucion/analisis-pdf` - Análisis PDFs
- `GET /distribucion/inmobiliarias` - Gestión inmobiliarias

### api
- `GET/POST /api/whatsapp/webhook` - Webhook Meta (estados mensajes)

---

## Modelos de Base de Datos (SQLite)

### Usuarios y Autenticación
```
Usuario
├── id, correo, nombre, contrasena_hash
├── rol (admin, poweruser, collaborator)
├── activo, debe_cambiar_contrasena
├── intentos_fallidos, bloqueado_hasta
└── Relaciones: cuentas_gmail, escaneos, clientes

CuentaGmail
├── id, usuario_id, correo_gmail
├── contrasena_app_encriptada, encryption_salt
├── activa, ultimo_escaneo
└── Métodos: establecer_contrasena_app(), obtener_contrasena_app()

LogActividad
├── id, usuario_id, accion, detalle
├── direccion_ip, user_agent, fecha
```

### Escaneo y Archivos
```
Escaneo
├── id, usuario_id, cuenta_gmail_id
├── estado (en_progreso, completado, error, cancelado)
├── correos_escaneados, pdfs_descargados
├── fecha_desde, fecha_hasta
└── Relaciones: archivos, logs

ArchivoDescargado
├── id, id_documento (PDF-XXXX)
├── escaneo_id, nombre_archivo, ruta_archivo
├── hash_archivo (SHA-256), tamano_bytes
├── remitente, asunto, fecha_correo
├── compania_id, cuenta_origen
├── estado_confirmacion (pendiente, definitivo)
├── cliente_existente_id, cliente_match_confianza
└── Relaciones: escaneo, compania, polizas

Compania
├── id, nombre, dominio_email
├── cantidad_documentos
└── Métodos: detectar_o_crear()

CorreoProcesado (memoria de escaneo)
├── id, cuenta_gmail_id, message_id
├── carpeta, tiene_pdfs
└── Métodos: ya_procesado()

RangoCobertura (rangos escaneados)
├── id, cuenta_gmail_id, carpeta
├── fecha_inicio, fecha_fin
```

### CRM y Distribución
```
Cliente
├── id, usuario_id, nombre, apellido
├── telefono_whatsapp, email, documento_identidad
├── activo, es_cliente_actual
└── Métodos: evaluar_si_actual(), buscar_por_documento()

PolizaCliente
├── id, cliente_id, archivo_id, compania_id
├── numero_poliza, tipo_seguro
├── fecha_vigencia_desde, fecha_vigencia_hasta
├── prima_anual, suma_asegurada
├── estado (activa, vencida, cancelada...)
├── estado_confirmacion (pendiente, definitivo)
├── Datos asegurado, vehículo, inmueble
├── datos_extraidos (JSON), confianza_extraccion
└── Métodos: dias_para_vencimiento(), esta_por_vencer()

EnvioWhatsApp
├── id, cliente_id, poliza_cliente_id
├── mensaje_enviado, estado (pendiente, enviado, error)
├── wamid (WhatsApp Message ID)
├── estado_mensaje (sent, delivered, read, failed)
└── Métodos: actualizar_estado_mensaje()

PlantillaMensaje
├── id, usuario_id, nombre_plantilla, mensaje
└── Métodos: renderizar(cliente, poliza)

Pago
├── id, poliza_cliente_id, numero_cuota, monto
├── fecha_vencimiento, fecha_pago
├── estado (pendiente, pagado, vencido)

Interaccion (historial CRM)
├── id, cliente_id, poliza_cliente_id
├── tipo (llamada, email, whatsapp, reunion)
├── requiere_seguimiento, fecha_seguimiento

AlertaVencimiento
├── id, poliza_cliente_id, tipo
├── fecha_alerta, estado, prioridad

Inmobiliaria
├── id, nombre, telefono, email
└── Relaciones: polizas
```

---

## Utilidades Clave

### DatabaseGateway (Singleton thread-safe)
```python
from app.utils.database_gateway import DatabaseGateway
db = DatabaseGateway()

# Lectura
result = db.read(lambda session: session.query(Cliente).all())

# Escritura con retry
db.write(lambda session: session.add(nuevo_cliente))
```

### Encriptación de Credenciales
```python
from app.utils.encryption import encrypt_credential, decrypt_credential

# Encriptar
encrypted, salt = encrypt_credential(password)

# Desencriptar
password = decrypt_credential(encrypted, salt)
```

---

## Flujos Principales

### Escaneo de Correos
```
Iniciar → Conectar Gmail → Procesar carpetas
    → Buscar PDFs → Calcular hash (deduplicación)
    → Detectar compañía por dominio
    → Guardar ArchivoDescargado
    → Marcar CorreoProcesado
```

### Asignación de Pólizas
```
Seleccionar PDF → Extraer datos (extractor_server)
    → Buscar cliente (documento o fuzzy name)
    → Confirmar/corregir datos
    → Crear PolizaCliente
```

### Envío WhatsApp
```
Seleccionar póliza → Elegir plantilla → Personalizar
    → Enviar (API o manual) → Guardar WAMID
    → Webhook actualiza estado → Si leído: marca definitivo
```

---

## Configuración

### Variables de Entorno
```
SECRET_KEY           # Clave secreta Flask
ENCRYPTION_KEY       # 32 bytes para AES-256
WHATSAPP_API_KEY     # API key WhatsApp Business
WHATSAPP_PHONE_ID    # Phone ID de Meta
WHATSAPP_VERIFY_TOKEN # Token verificación webhook
WHATSAPP_APP_SECRET  # Para HMAC de webhooks
```

### Base de Datos
- SQLite con WAL mode
- Timeout 120 segundos
- Pool pre-ping habilitado

---

## Integraciones

1. **Gmail API** - Credenciales encriptadas, múltiples cuentas
2. **WhatsApp Business API** - Envío automático + webhooks
3. **Extractor Server** - Servidor separado para extracción de PDFs

---

## Seguridad

- Contraseñas: bcrypt con salt
- Sesiones: httponly, samesite
- CSRF: Flask-WTF tokens
- Rate limiting: 5 intentos, 15 min bloqueo
- Webhooks: HMAC-SHA256 validación
- Credenciales Gmail: Fernet (AES) encriptación

---

## Estados Importantes

### Póliza
```
activa → en_renovacion → vencida
      → suspendida
      → cancelada
```

### Confirmación
```
pendiente (extracción automática)
    → definitivo (manual o WhatsApp read)
```

### Envío WhatsApp
```
pendiente → enviado → (webhook) → delivered → read
         → error
```

---

## Comandos Útiles

```bash
# Desarrollo
python run.py

# Servidor LAN
python servidor_lan.py

# Crear usuario admin
python scripts/crear_usuario.py
```

---

## Relación con Extractor Server

El `extractor_server` (puerto 5252) es un servidor independiente que:
- Extrae datos de PDFs usando IA
- Maneja conexiones IMAP para escaneo
- Tiene su propio debugger de pasos

El portal (puerto 5000) consume los datos extraídos y gestiona:
- Usuarios y autenticación
- CRM de clientes y pólizas
- Envíos WhatsApp
- Alertas y seguimiento

---

## Sesión 2026-02-28 - Cambios Realizados

### 1. Commit: Refactor thread-safety y servidor LAN (315861e)
- `run.py` refactorizado para acceso LAN unificado + soporte Waitress
- `servidor_lan.py` eliminado (funcionalidad integrada en run.py)
- `alertas.py` y `clientes_actuales.py` thread-safe con sesiones inyectables
- `whatsapp_sender.py` optimizado con sesiones cortas
- Nuevo endpoint `/api/extractor/reset-total` para limpieza de datos
- Templates actualizados para apuntar a Extractor Server (puerto 5252)
- Nueva vista de pólizas en distribución
- Nuevas utilidades: `structured_logger.py`, `task_progress.py`, `encryption.py`
- Tests de thread-safety agregados

### 2. CRUD Cuentas Gmail en Extractor Server
**Archivos modificados en `C:\Users\César\extractor_server\`:**

- `encryption.py` - Agregadas funciones:
  - `generate_salt()` - Genera salt de 32 bytes
  - `encrypt_credential(plaintext, salt)` - Encripta con PBKDF2 + Fernet

- `app.py` - Nuevos endpoints:
  ```
  GET    /api/cuentas              # Listar activas
  GET    /api/cuentas/todas        # Listar todas
  GET    /api/cuentas/<id>         # Detalle
  POST   /api/cuentas              # Crear (usuario_id, correo_gmail, contrasena_app)
  PUT    /api/cuentas/<id>         # Editar
  DELETE /api/cuentas/<id>         # Desactivar (soft delete)
  POST   /api/cuentas/<id>/reactivar  # Reactivar
  GET    /cuentas                  # UI de gestión
  ```

- `templates/cuentas.html` - UI completa con:
  - Tabla de cuentas (correo, estado, último escaneo)
  - Modal crear/editar con validación
  - Botones editar, desactivar, reactivar
  - Tema oscuro consistente

- `templates/dashboard.html` y `escaneo.html` - Enlace "Cuentas" en nav

### 3. Integración Portal ↔ Extractor
- `app/templates/base.html` - Menú Extractor ahora incluye "Cuentas Gmail"
- Acceso: Menú Extractor → Cuentas Gmail (abre `http://{host}:5252/cuentas`)

### Commits Pushed
- `315861e` - Refactor: mejorar thread-safety y consolidar servidor LAN
- `f4c75ad` - Feat: agregar enlace a CRUD de cuentas Gmail en menu extractor

### Nota: Extractor Server no tiene Git
Los cambios en `C:\Users\César\extractor_server\` no están versionados.
Archivos modificados que deben respaldarse:
- `encryption.py`
- `app.py`
- `templates/cuentas.html`
- `templates/dashboard.html`
- `templates/escaneo.html`

---

## Sesión 2026-02-28 (continuación) - Vista Representante y Usage Tracker

### 4. Vista de Representante (Collaborator)

Nuevo módulo para el rol `collaborator` que actúa como representante comercial.

**Archivos creados:**
```
app/representante/
├── __init__.py              # Blueprint
├── routes.py                # Rutas del representante
app/templates/representante/
├── dashboard.html           # Panel con todas las pólizas
├── poliza_detalle.html      # Detalle de póliza
├── confirmar_envio.html     # Confirmación antes de enviar
├── envio_confirmacion.html  # Resultado de envío masivo
└── editar_telefono.html     # Edición de teléfono cliente
```

**Rutas del representante:**
```
GET  /representante/                    # Dashboard con todas las pólizas
GET  /representante/poliza/<id>         # Detalle de póliza
GET/POST /representante/poliza/<id>/whatsapp  # Enviar WhatsApp
```

**Características:**
- Ve TODAS las pólizas del sistema (no solo las propias)
- Columnas especiales: "Descargado por", "Cuenta Gmail", "Fecha descarga"
- Filtros avanzados: por usuario que descargó, cuenta Gmail, fechas
- Acciones: ver detalle, enviar WhatsApp, descargar PDF
- Estadísticas: total, activas, por vencer, vencidas, sin contactar

**Archivos modificados:**
- `app/utils/decoradores.py` - Agregado `@collaborator_requerido`
- `app/auth/routes.py` - Redirección condicional post-login
- `app/main/routes.py` - Redirección de collaborator a su panel
- `app/templates/base.html` - Menú diferenciado por rol
- `app/__init__.py` - Registro del blueprint

**Comportamiento por rol:**
| Rol | `/` redirige a | `/dashboard` | `/representante/` |
|-----|---------------|--------------|-------------------|
| admin | /dashboard | OK | Bloqueado |
| poweruser | /dashboard | OK | Bloqueado |
| collaborator | /representante/ | → /representante/ | OK |

### 5. Sistema de Usage Tracker (Heatmap)

Módulo reutilizable para tracking de uso y generación de heatmaps mensuales.

**Archivos creados:**
```
app/usage_tracker/
├── __init__.py              # UsageTracker class (extensión Flask)
├── models.py                # Modelo EventoUso
├── routes.py                # API + Panel analytics
└── templates/usage_tracker/
    └── analytics.html       # Dashboard de analytics
app/static/js/
└── click-tracker.js         # Script de tracking (batch + sendBeacon)
```

**Modelo EventoUso:**
```python
EventoUso
├── id, fecha, mes (YYYY-MM)
├── pagina, elemento, elemento_id, elemento_texto
├── accion (click, submit, etc.)
├── posicion_x, posicion_y, viewport_width, viewport_height
└── Métodos: registrar(), estadisticas_paginas(), estadisticas_elementos(),
             datos_heatmap(), meses_disponibles(), limpiar_antiguos()
```

**Rutas de analytics:**
```
POST /analytics/track          # Recibe eventos del frontend
GET  /analytics/               # Panel de analytics (solo admin)
GET  /analytics/heatmap-data   # API para datos de heatmap (AJAX)
POST /analytics/limpiar        # Limpieza de datos antiguos
```

**Características:**
- Tracking automático de clics en: `a`, `button`, `.btn`, `.nav-link`, `[data-track]`
- Batch de eventos (10 clics o 5 segundos)
- Envío no bloqueante con `navigator.sendBeacon`
- Panel con estadísticas por página y por elemento
- Heatmap visual usando heatmap.js
- Selector de mes y limpieza de datos antiguos

**Configuración (config.py):**
```python
USAGE_TRACKER_ENABLED = True
USAGE_TRACKER_ENDPOINT = '/api/analytics/track'
USAGE_TRACKER_BATCH_SIZE = 10
USAGE_TRACKER_BATCH_TIMEOUT = 5000
USAGE_TRACKER_TRACK_ELEMENTS = 'a, button, .btn, .nav-link, [data-track]'
USAGE_TRACKER_EXCLUDE_PATHS = ['/static/', '/api/analytics/']
```

**Para reutilizar en otro proyecto Flask:**
```python
# 1. Copiar carpeta app/usage_tracker/ y app/static/js/click-tracker.js
# 2. En __init__.py:
from app.usage_tracker import UsageTracker
UsageTracker(app)

# 3. Incluir script en base.html:
<script src="{{ url_for('static', filename='js/click-tracker.js') }}"></script>
```

**Archivos modificados:**
- `app/__init__.py` - Inicializa UsageTracker, exime de CSRF
- `app/templates/base.html` - Incluye click-tracker.js, menú Admin con dropdown

### Estructura Actualizada de Directorios

```
app/
├── representante/           # NUEVO - Vista para collaborators
│   ├── __init__.py
│   └── routes.py
├── usage_tracker/           # NUEVO - Módulo de analytics reutilizable
│   ├── __init__.py
│   ├── models.py
│   ├── routes.py
│   └── templates/usage_tracker/
│       └── analytics.html
├── static/js/
│   ├── main.js
│   ├── tracking-extraccion.js
│   └── click-tracker.js     # NUEVO - Script de tracking
└── templates/
    └── representante/       # NUEVO - Templates del representante
        ├── dashboard.html
        ├── poliza_detalle.html
        ├── confirmar_envio.html
        ├── envio_confirmacion.html
        └── editar_telefono.html
```

### Blueprints Actuales

| Blueprint | Prefijo | Descripción |
|-----------|---------|-------------|
| auth | / | Autenticación |
| main | / | Dashboard y archivos |
| admin | /admin | Administración |
| distribucion | /distribucion | CRM y pólizas |
| api | /api | APIs y webhooks |
| representante | /representante | Vista collaborator |
| usage_tracker | /analytics | Tracking de uso |

---

## Sesión 2026-03-02 - Cambios Realizados

### 1. Eliminación Completa de Funcionalidad de Pagos

Se eliminó toda la funcionalidad de registro y gestión de pagos del sistema (no se hacen cobranzas).

**Rutas eliminadas de `distribucion/routes.py`:**
- `GET /distribucion/poliza/<id>/pagos` - Lista de pagos
- `GET/POST /distribucion/poliza/<id>/pagos/nuevo` - Nuevo pago
- `GET/POST /distribucion/pago/<id>/editar` - Editar pago
- `POST /distribucion/pago/<id>/marcar-pagado` - Marcar como pagado
- `GET/POST /distribucion/poliza/<id>/pagos/generar` - Generar cuotas
- `GET /distribucion/pagos/pendientes` - Pagos pendientes

**Formularios eliminados de `distribucion/forms.py`:**
- `PagoForm`
- `GenerarCuotasForm`

**Templates eliminados:**
- `app/templates/distribucion/pagos.html`
- `app/templates/distribucion/pago_form.html`
- `app/templates/distribucion/pagos_pendientes.html`
- `app/templates/distribucion/generar_cuotas.html`
- `app/templates/representante/registrar_pago.html`

**Archivos modificados:**
- `app/templates/base.html` - Quitado enlace "Pagos Pendientes" del menú
- `app/templates/distribucion/crm_dashboard.html` - Quitada sección y acciones de pagos
- `app/templates/distribucion/poliza_completa.html` - Quitado tab de pagos
- `app/representante/routes.py` - Quitada ruta `registrar_pago`
- `app/templates/representante/dashboard.html` - Quitado botón "$"
- `app/templates/representante/poliza_detalle.html` - Quitada sección de pagos

**Nota:** El modelo `Pago` se mantiene en `models.py` para compatibilidad con datos históricos y el sistema de alertas (`tasks/alertas.py`).

### 2. Edición de Teléfono con Normalización Argentina

Se agregó funcionalidad para que el representante pueda editar el teléfono WhatsApp del cliente con normalización automática al formato argentino.

**Archivos creados:**
- `app/templates/representante/editar_telefono.html` - Formulario de edición

**Archivos modificados:**
- `app/models.py` - Agregados métodos en clase `Cliente`:
  - `normalizar_telefono_argentina(telefono)` - Método estático que normaliza cualquier formato al estándar `549XXXXXXXXXX`
  - `establecer_telefono(telefono)` - Método de instancia que valida y guarda
- `app/representante/routes.py` - Nueva ruta `editar_telefono`
- `app/templates/representante/poliza_detalle.html` - Botón "Editar Tel" en datos del cliente

**Formato de normalización:**
```
Entrada                  -> Salida
+54 9 11 1234-5678      -> 5491112345678
011 15 1234-5678        -> 5491112345678
11 1234-5678            -> 5491112345678
351 123-4567            -> 5493511234567
```

**Rutas actuales del representante:**
- `GET /representante/` - Dashboard
- `GET /representante/poliza/<id>` - Detalle
- `GET/POST /representante/cliente/<id>/enviar` - Enviar documentos pendientes
- `GET/POST /representante/cliente/<id>/telefono` - Editar teléfono

### 3. Envío Simplificado de Documentos

Se reemplazó el envío individual de pólizas por un envío masivo de documentos pendientes por cliente.

**Cambios:**
- Nueva ruta `enviar_documentos(cliente_id)` reemplaza `enviar_whatsapp(poliza_id)`
- Envía automáticamente TODAS las pólizas del cliente que no tienen envío previo
- Usa la plantilla predeterminada (sin editor de mensaje)
- Flujo: Confirmar → Crear EnvioWhatsApp por cada póliza → Background processor envía

**Templates nuevos:**
- `confirmar_envio.html` - Muestra lista de documentos a enviar antes de confirmar
- `envio_confirmacion.html` - Confirmación con documentos encolados

**Templates eliminados:**
- `enviar_whatsapp.html` (editor de mensaje individual)
- `enviar_resultado.html` (resultado de envío individual)

### 4. Integración Completa con API de WhatsApp

Se corrigió y completó la integración con `whatsapp-service-standalone` para el envío real de documentos.

**Problema detectado:**
El sistema marcaba documentos como "encolados" pero no los enviaba porque caía al modo "manual" cuando no detectaba una sesión API activa.

**Solución implementada:**
El sistema verifica 2 modos de envío por API en orden de prioridad:
1. **API Local** (`whatsapp-service-standalone` en localhost:3001) - Sesión personal
2. **API de Meta** (WhatsApp Business Cloud API) - Cuenta business

Si ninguna API está disponible, muestra enlaces wa.me para envío manual.

**Archivos modificados:**

`app/representante/routes.py`:
- Importado modelo `WhatsAppSession`
- Función `enviar_documentos` verifica sesión API activa:
  ```python
  sesion_web = WhatsAppSession.query.filter_by(
      usuario_id=current_user.id,
      estado='ready',
      activo=True
  ).first()
  envio_automatico = modo_api or sesion_web is not None
  ```
- Dashboard recibe `sesion_whatsapp` para mostrar estado de conexión

`app/templates/representante/dashboard.html`:
- Agregado indicador de estado API en header
- Botón "Configurar API" o "API Conectada" con LED verde/rojo
- Enlace a `/distribucion/whatsapp/configurar` para escanear QR

**Flujo de envío:**
```
Usuario abre /representante/
    ↓
Indicador muestra estado de API
    ↓ (si desconectado)
Click "Configurar API" → /distribucion/whatsapp/configurar
    ↓
Escanear QR → WhatsAppSession.estado = 'ready'
    ↓
Volver a /representante/ → Click "Enviar Documentos"
    ↓
Sistema crea EnvioWhatsApp con estado='pendiente'
    ↓
WhatsAppQueueProcessor (background) detecta pendientes
    ↓
POST localhost:3001/session/{userId}/send-document
    ↓
Documento enviado, EnvioWhatsApp.estado = 'enviado'
```

**whatsapp-service-standalone:**
Servicio Node.js que expone API REST para WhatsApp:
- Ubicación: `C:\Users\César\whatsapp-service-standalone\`
- Puerto: 3001
- Endpoints principales:
  - `POST /session/:userId/start` - Iniciar sesión
  - `GET /session/:userId/qr` - Obtener QR
  - `GET /session/:userId/status` - Estado de sesión
  - `POST /session/:userId/send` - Enviar texto
  - `POST /session/:userId/send-document` - Enviar documento con caption

**Para iniciar el servicio:**
```bash
cd C:\Users\César\whatsapp-service-standalone
npm start  # o usar iniciar.bat
```

**Configuración del portal:**
```python
# config.py
WHATSAPP_SERVICE_URL = 'http://localhost:3001'
WHATSAPP_SERVICE_TIMEOUT = 30
```

---
