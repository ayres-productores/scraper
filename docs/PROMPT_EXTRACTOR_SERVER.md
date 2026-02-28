# Prompt: Crear Extractor Server (desde cero)

## Objetivo

Crear un servidor independiente que extrae pólizas de seguros desde cuentas Gmail y las consolida a una base de datos SQLite compartida con otro sistema.

## Contexto

- **Base de datos:** SQLite en `../portal_seguros/portal_seguros.db` (compartida, usar locks)
- **Archivos:** PDFs se guardan en `../portal_seguros/archivos_usuarios/{usuario_id}/`
- **Puerto:** 5001

## Requisitos Funcionales

### 1. Escaneo de Gmail

- Conectar via IMAP a cuentas Gmail (con app passwords)
- Escanear todas las carpetas automáticamente (en background, sin mostrar paso de listado)
- Mostrar cada PDF encontrado en tiempo real conforme se descubre
- Ofrecer opción de descargar cada PDF individualmente
- Evitar reprocesar correos ya vistos (guardar message_id)

### 2. Extracción de Datos

Para cada PDF descargado, extraer:
- Nombre del asegurado
- Documento (DNI/CUIT)
- Compañía aseguradora (detectar del contenido)
- Datos del vehículo si aplica (marca, modelo, patente)
- Vigencia (desde/hasta)
- Número de póliza

### 3. Consolidación (proceso separado)

- Worker independiente que corre cada N segundos
- Lee PDFs pendientes de procesar
- Extrae datos y los inserta en BD
- Usa transacciones cortas para no bloquear

### 4. API REST

```
POST /api/scan/start      - Iniciar escaneo
GET  /api/scan/{id}       - Estado del escaneo
POST /api/scan/{id}/stop  - Detener escaneo
GET  /api/health          - Health check
```

## Tablas de BD (ya existen)

```sql
-- Usuario que inicia el escaneo
usuarios (id, correo, nombre, ...)

-- Cuentas Gmail configuradas
cuentas_gmail (id, usuario_id, correo, password_cifrado, ...)

-- Registro de escaneos
escaneos (id, usuario_id, estado, fecha_inicio, fecha_fin, ...)

-- PDFs descargados
archivos_descargados (id, escaneo_id, nombre_archivo, ruta_archivo,
                      compania_id, hash_archivo, ...)

-- Compañías detectadas
companias (id, nombre, dominio_email, ...)

-- Correos ya procesados (para no reprocesar)
correos_procesados (id, cuenta_gmail_id, message_id, carpeta, ...)
```

## Principios de Diseño

1. **SQLite con locks cuidadosos:**
   - Transacciones lo más cortas posible
   - Retry con backoff si hay lock
   - Un solo writer a la vez (el consolidador)

2. **Separación escaneo/consolidación:**
   - Escaneo solo descarga archivos y guarda metadata en JSON temporal
   - Consolidador lee JSON y escribe a BD
   - Si falla consolidación, no se pierde el escaneo

3. **Simplicidad:**
   - Sin frameworks pesados
   - Código legible y mantenible
   - Logging claro

## Stack Sugerido

- Python 3.10+
- Flask (API REST)
- SQLAlchemy (ORM)
- IMAPClient (conexión Gmail)
- pdfplumber (extracción de texto)

## Estructura Mínima

```
extractor_server/
├── app.py              # Flask app + endpoints
├── config.py           # Configuración
├── models.py           # Modelos SQLAlchemy (compartidos)
├── scanner.py          # Lógica de escaneo IMAP
├── extractor.py        # Extracción de datos de PDF
├── consolidator.py     # Worker de consolidación
├── db.py               # Conexión BD con locks
└── run.py              # Entry point
```

## Entregable

Servidor funcional que:
1. Expone API REST en puerto 5001
2. Escanea Gmail y descarga PDFs
3. Consolida datos a la BD compartida
4. No bloquea la BD por más de 1 segundo
