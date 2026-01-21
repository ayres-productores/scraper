"""
Configuración de la aplicación Flask
"""

import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Configuración base."""

    # Clave secreta (cambiar en producción)
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'clave-secreta-cambiar-en-produccion-2024'

    # Base de datos
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.dirname(basedir), 'portal_seguros.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Sesiones
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
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
    UPLOAD_FOLDER = os.path.join(os.path.dirname(basedir), 'archivos_usuarios')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB

    # Clave de encriptación para credenciales Gmail (32 bytes para AES-256)
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY') or 'clave-encriptacion-32-bytes-xx!'


class ProductionConfig(Config):
    """Configuración de producción."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class DevelopmentConfig(Config):
    """Configuración de desarrollo."""
    DEBUG = True
