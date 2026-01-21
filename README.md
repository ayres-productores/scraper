# Portal de Seguros - Sistema CRM

Sistema integral de gestión para productores de seguros con extracción automática de pólizas desde correos electrónicos.

## Características

### Extractor de Correos
- Conexión segura a Gmail vía IMAP
- Descarga automática de PDFs adjuntos
- Detección automática de compañía aseguradora
- Filtrado por palabras clave y fechas
- Progreso en tiempo real

### Intérprete de PDFs
- Extracción automática de datos con expresiones regulares
- Indicador de confianza de extracción
- Formulario de revisión y edición
- Procesamiento por lotes
- Re-extracción y comparación de datos

### CRM Completo
- Gestión de clientes con datos completos
- Historial de interacciones (llamadas, emails, reuniones)
- Seguimiento de tareas pendientes

### Gestión de Pólizas
- Datos completos: asegurado, vehículo, coberturas
- Control de vigencias y renovaciones
- Vinculación con PDFs originales
- Estados: activa, vencida, cancelada, en renovación

### Control de Pagos
- Gestión de cuotas
- Control de vencimientos
- Múltiples métodos de pago

### Alertas Automáticas
- Vencimiento de pólizas (30, 15, 7 días)
- Pagos pendientes
- Seguimientos programados

### Gestión de Siniestros
- Registro y seguimiento de reclamos
- Estados del proceso
- Montos reclamados y aprobados

## Tecnologías

- **Backend**: Python 3.x, Flask
- **Base de Datos**: SQLite (desarrollo) / PostgreSQL (producción)
- **Frontend**: HTML5, CSS3, JavaScript
- **Extracción PDF**: PyMuPDF (fitz)
- **Autenticación**: Flask-Login, bcrypt

## Instalación

### Requisitos

- Python 3.8 o superior
- pip (gestor de paquetes)

### Pasos

1. Clonar el repositorio:
```bash
git clone https://github.com/tu-usuario/portal-seguros.git
cd portal-seguros
```

2. Crear entorno virtual:
```bash
python -m venv venv
```

3. Activar entorno virtual:
```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

4. Instalar dependencias:
```bash
pip install -r requirements.txt
```

5. Ejecutar la aplicación:
```bash
python run.py
```

6. Acceder en el navegador:
```
http://127.0.0.1:5000
```

## Credenciales por Defecto

| Usuario | Contraseña | Rol |
|---------|------------|-----|
| admin@empresa.com | CambiarEnPrimerLogin123! | Administrador |

> **Importante**: Cambiar estas credenciales en el primer inicio de sesión.

## Configuración de Gmail

Para usar el extractor de correos se requiere una contraseña de aplicación:

1. Ir a [myaccount.google.com](https://myaccount.google.com)
2. Seguridad → Verificación en dos pasos (activar)
3. Seguridad → Contraseñas de aplicaciones
4. Generar nueva contraseña para "Correo"
5. Usar esa contraseña de 16 caracteres en el sistema

## Estructura del Proyecto

```
portal_seguros/
├── app/
│   ├── __init__.py          # Fábrica de aplicación
│   ├── models.py            # Modelos de base de datos
│   ├── auth/                # Autenticación
│   │   ├── forms.py
│   │   └── routes.py
│   ├── main/                # Rutas principales
│   │   └── routes.py
│   ├── extractor/           # Extractor de correos
│   │   ├── motor.py         # Motor de escaneo IMAP
│   │   ├── pdf_parser.py    # Extractor de datos PDF
│   │   └── routes.py
│   ├── distribucion/        # CRM y gestión
│   │   ├── forms.py
│   │   └── routes.py
│   ├── admin/               # Administración
│   │   └── routes.py
│   ├── templates/           # Plantillas HTML
│   └── static/              # CSS, JS, imágenes
├── run.py                   # Punto de entrada
├── requirements.txt         # Dependencias
└── DOCUMENTACION_SISTEMA.txt # Documentación técnica completa
```

## Módulos Principales

### `/extractor`
Panel de extracción de correos con:
- Configuración de cuentas Gmail
- Control de escaneo (iniciar/detener/reiniciar)
- Historial de escaneos

### `/distribucion`
CRM completo con:
- Dashboard con estadísticas
- Gestión de clientes
- Gestión de pólizas
- Historial de interacciones
- Control de pagos
- Alertas de vencimiento

### `/distribucion/interprete-pdf`
Intérprete de pólizas PDF:
- Lista de PDFs pendientes/procesados
- Extracción automática de datos
- Formulario de revisión
- Procesamiento por lotes

## Seguridad

- Contraseñas hasheadas con bcrypt (factor 12)
- Credenciales Gmail encriptadas con AES-256
- Protección CSRF en todos los formularios
- Headers de seguridad configurados
- Límite de intentos de login

## Configuración de Producción

1. **Cambiar clave secreta**:
```python
SECRET_KEY = 'tu-clave-secreta-muy-segura'
```

2. **Usar PostgreSQL**:
```
DATABASE_URL=postgresql://user:pass@host/dbname
```

3. **Habilitar HTTPS**:
```python
SESSION_COOKIE_SECURE = True
```

4. **Usar servidor WSGI**:
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"
```

## Documentación

Ver `DOCUMENTACION_SISTEMA.txt` para documentación técnica completa incluyendo:
- Descripción de todos los modelos de base de datos
- Lista completa de rutas y endpoints
- Descripción de cada plantilla HTML
- Guía de configuración detallada

## Licencia

Software propietario - Uso interno exclusivo.
