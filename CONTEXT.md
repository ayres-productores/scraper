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
