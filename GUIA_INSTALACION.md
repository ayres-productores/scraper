# Guía del Portal de Seguros CRM

## Descripción General

Este es un sistema CRM para brokers de seguros desarrollado en **Flask** (Python). Incluye:
- Extractor automático de pólizas desde correo Gmail
- Parser de PDFs con detección automática de datos
- Gestión de clientes, pólizas y pagos
- Alertas de vencimiento
- Integración con WhatsApp

---

## Requisitos Previos

- Python 3.10 o superior
- pip (gestor de paquetes)

---

## Instalación

```bash
# 1. Crear entorno virtual
python -m venv venv

# 2. Activar entorno virtual (Windows)
venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

---

## Ejecutar el Servidor

### Modo Desarrollo (terminal abierta)
```bash
python run.py
```

El servidor estará disponible en: **http://127.0.0.1:5000**

### Dejar el Servidor Corriendo en Background (Windows)

**Opción 1: Usando `pythonw` (sin ventana)**
```bash
pythonw run.py
```

**Opción 2: Usando `start /b`**
```bash
start /b python run.py > server.log 2>&1
```

**Opción 3: Crear un servicio de Windows con NSSM**
1. Descargar NSSM: https://nssm.cc/download
2. Ejecutar:
```bash
nssm install PortalSeguros
```
3. Configurar:
   - Path: `C:\Users\César\portal_seguros\venv\Scripts\python.exe`
   - Startup directory: `C:\Users\César\portal_seguros`
   - Arguments: `run.py`
4. Iniciar servicio:
```bash
nssm start PortalSeguros
```

**Opción 4: Usar Task Scheduler de Windows**
1. Abrir "Programador de tareas"
2. Crear tarea básica
3. Configurar que se ejecute al iniciar Windows
4. Acción: Iniciar programa
   - Programa: `C:\Users\César\portal_seguros\venv\Scripts\python.exe`
   - Argumentos: `run.py`
   - Iniciar en: `C:\Users\César\portal_seguros`

---

## Credenciales por Defecto

| Campo | Valor |
|-------|-------|
| Usuario | `admin@empresa.com` |
| Contraseña | `CambiarEnPrimerLogin123!` |

**Importante:** Cambiar la contraseña en el primer inicio de sesión.

---

## Estructura del Proyecto

```
portal_seguros/
├── app/
│   ├── auth/           # Autenticación (login, logout)
│   ├── main/           # Dashboard principal
│   ├── extractor/      # Extractor de correos y PDFs
│   ├── distribucion/   # CRM (clientes, pólizas, pagos)
│   ├── admin/          # Panel de administración
│   ├── templates/      # Plantillas HTML
│   └── static/         # CSS y JavaScript
├── run.py              # Punto de entrada
├── requirements.txt    # Dependencias
└── portal_seguros.db   # Base de datos SQLite
```

---

## Rutas Principales

| Ruta | Descripción |
|------|-------------|
| `/login` | Inicio de sesión |
| `/dashboard` | Panel principal |
| `/extractor/` | Escanear correos Gmail |
| `/distribucion/crm` | Dashboard CRM |
| `/distribucion/clientes` | Gestión de clientes |
| `/distribucion/polizas` | Gestión de pólizas |
| `/distribucion/pagos` | Control de pagos |
| `/admin/` | Panel de administración |

---

## Configurar Cuenta Gmail

1. Ir a tu cuenta de Google → Seguridad
2. Activar verificación en dos pasos
3. Generar "Contraseña de aplicaciones"
4. En el portal, ir a Extractor → Agregar cuenta
5. Ingresar email y la contraseña de aplicación generada

---

## Para Producción

Si deseas usar el servidor en producción, se recomienda:

1. **Usar Waitress** en lugar del servidor de desarrollo:
```bash
pip install waitress
waitress-serve --port=5000 run:app
```

2. **Cambiar variables de entorno**:
```bash
set SECRET_KEY=una-clave-muy-segura-y-larga
set FLASK_ENV=production
```

3. **Usar un proxy reverso** como Nginx para mejor rendimiento y seguridad.

---

## Detener el Servidor

- Si está en terminal: `Ctrl + C`
- Si es servicio NSSM: `nssm stop PortalSeguros`
- Si es proceso en background: `taskkill /f /im python.exe`

---

## Soporte

Para dudas o problemas, revisar los archivos de documentación adicionales:
- `README.md` - Documentación general
- `MANUAL_CRM.md` - Manual de usuario del CRM
- `DOCUMENTACION_SISTEMA.txt` - Documentación técnica detallada
