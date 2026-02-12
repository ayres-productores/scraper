"""
Configuración de la aplicación Flask
"""

import os
import sys
import logging
from datetime import timedelta

_config_logger = logging.getLogger('app.config')

# Detectar si estamos corriendo como ejecutable PyInstaller
if getattr(sys, 'frozen', False):
    # Ejecutable: usar directorio del .exe
    basedir = os.path.dirname(sys.executable)
else:
    # Desarrollo: usar directorio del archivo config.py
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _generar_clave_desarrollo():
    """Genera una clave segura para desarrollo (no usar en producción)."""
    import secrets
    return secrets.token_hex(32)


# Detectar modo de ejecución
# Es desarrollo si:
# 1. FLASK_ENV=development o FLASK_DEBUG=1
# 2. No es un ejecutable PyInstaller (es script Python normal)
# 3. No existe variable PRODUCTION=1
_ES_EJECUTABLE = getattr(sys, 'frozen', False)
_ES_PRODUCCION_EXPLICITA = os.environ.get('PRODUCTION') == '1'
_ES_DESARROLLO = (
    os.environ.get('FLASK_ENV') == 'development' or
    os.environ.get('FLASK_DEBUG') == '1' or
    (not _ES_EJECUTABLE and not _ES_PRODUCCION_EXPLICITA)
)


class Config:
    """Configuración base."""

    # ========== CLAVES SECRETAS ==========
    # En producción, estas DEBEN estar configuradas en variables de entorno
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # Validar en producción
    if not SECRET_KEY:
        if _ES_DESARROLLO:
            # En desarrollo, generar clave temporal (advertencia en logs)
            SECRET_KEY = _generar_clave_desarrollo()
            _config_logger.warning("SECRET_KEY no configurada. Usando clave temporal para desarrollo.")
        else:
            raise ValueError(
                "SECRET_KEY debe estar configurada en variables de entorno. "
                "Genera una con: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

    # Base de datos
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'portal_seguros.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Opciones del engine para SQLite - evitar "database is locked"
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {
            'timeout': 120,  # Esperar hasta 120 segundos si la BD está bloqueada
            'check_same_thread': False  # Permitir uso desde múltiples threads
        },
        'pool_pre_ping': True,  # Verificar conexión antes de usar
    }

    # Sesiones
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_SECURE = False  # True en producción con HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Protección CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hora

    # Rate limiting
    INTENTOS_LOGIN_MAX = 5
    BLOQUEO_MINUTOS = 15

    # Archivos
    UPLOAD_FOLDER = os.path.join(basedir, 'archivos_usuarios')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB

    # Backup de PDFs de polizas (permanente, no se borra al limpiar)
    POLIZAS_BACKUP_FOLDER = os.path.join(basedir, 'polizas_backup')

    # Repositorio central de archivos (deduplicación por hash)
    REPOSITORIO_ARCHIVOS = os.path.join(basedir, 'repositorio_archivos')

    # Clave de encriptación para credenciales Gmail (32 bytes para AES-256)
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')

    if not ENCRYPTION_KEY:
        if _ES_DESARROLLO:
            # En desarrollo, usar clave temporal (advertencia en logs)
            ENCRYPTION_KEY = 'dev-key-32-bytes-solo-desarroll'  # Exactamente 32 bytes
            _config_logger.warning("ENCRYPTION_KEY no configurada. Usando clave temporal para desarrollo.")
        else:
            raise ValueError(
                "ENCRYPTION_KEY debe estar configurada en variables de entorno (exactamente 32 caracteres). "
                "Genera una con: python -c \"import secrets; print(secrets.token_hex(16))\""
            )

    # WhatsApp Business API (central/fallback)
    WHATSAPP_API_KEY = os.environ.get('WHATSAPP_API_KEY')
    WHATSAPP_PHONE_ID = os.environ.get('WHATSAPP_PHONE_ID')
    WHATSAPP_VERIFY_TOKEN = os.environ.get('WHATSAPP_VERIFY_TOKEN')

    # App Secret para validar firma HMAC de webhooks de Meta
    # IMPORTANTE: Esto es crítico para seguridad - sin esto, cualquiera puede enviar webhooks falsos
    # Se obtiene de: Meta Developer Dashboard > App Settings > Basic > App Secret
    WHATSAPP_APP_SECRET = os.environ.get('WHATSAPP_APP_SECRET')

    if not WHATSAPP_VERIFY_TOKEN:
        if _ES_DESARROLLO:
            WHATSAPP_VERIFY_TOKEN = 'dev_webhook_token_temporal'
        else:
            # En producción sin WhatsApp configurado, usar None (webhook deshabilitado)
            WHATSAPP_VERIFY_TOKEN = None

    if not WHATSAPP_APP_SECRET and not _ES_DESARROLLO:
        _config_logger.warning("WHATSAPP_APP_SECRET no configurado. Los webhooks NO validarán firma HMAC.")

    # Modo automático: usa 'api' si las credenciales están configuradas, sino 'manual'
    WHATSAPP_MODO = os.environ.get('WHATSAPP_MODO') or ('api' if WHATSAPP_API_KEY and WHATSAPP_PHONE_ID else 'manual')

    # WhatsApp Web Service (sesiones personales por usuario)
    WHATSAPP_SERVICE_URL = os.environ.get('WHATSAPP_SERVICE_URL', 'http://localhost:3001')
    WHATSAPP_SERVICE_TIMEOUT = int(os.environ.get('WHATSAPP_SERVICE_TIMEOUT', '30'))


class ProductionConfig(Config):
    """Configuración de producción."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class DevelopmentConfig(Config):
    """Configuración de desarrollo."""
    DEBUG = True
