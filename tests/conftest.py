"""
Fixtures compartidas para tests del Portal de Seguros.

Este módulo proporciona:
- Aplicación Flask de prueba con BD en memoria
- Fixtures para usuarios, cuentas y otros modelos
- Utilidades para tests de threading
"""

import os
import sys
import pytest
import tempfile

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar variables de entorno ANTES de importar la app
os.environ['FLASK_ENV'] = 'development'
os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only-32chars!'
os.environ['ENCRYPTION_KEY'] = 'test-encryption-key-32-chars!!'


@pytest.fixture(scope='session')
def app():
    """
    Crea una aplicación Flask de prueba con BD en memoria.

    Esta fixture tiene scope='session' para reutilizar la app entre tests,
    pero cada test usa su propia transacción que se revierte al finalizar.
    """
    from app import create_app
    from app.config import Config

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        WTF_CSRF_ENABLED = False
        SERVER_NAME = 'localhost'

    test_app = create_app(TestConfig)

    # Crear contexto de aplicación
    ctx = test_app.app_context()
    ctx.push()

    # Crear todas las tablas
    from app import db
    db.create_all()

    yield test_app

    # Limpiar
    db.drop_all()
    ctx.pop()


@pytest.fixture(scope='function')
def db(app):
    """
    Proporciona acceso a la base de datos con rollback automático.

    Cada test obtiene una transacción limpia que se revierte al finalizar,
    asegurando aislamiento entre tests.

    Compatible con Flask-SQLAlchemy 3.x
    """
    from app import db as _db

    # En Flask-SQLAlchemy 3.x usamos la sesión directamente
    # Guardamos el estado para restaurar después
    yield _db

    # Rollback cualquier cambio pendiente
    _db.session.rollback()

    # Limpiar todos los datos de prueba (tablas en orden inverso de dependencias)
    meta = _db.metadata
    for table in reversed(meta.sorted_tables):
        _db.session.execute(table.delete())
    _db.session.commit()


@pytest.fixture
def client(app):
    """Cliente de prueba para hacer requests HTTP."""
    return app.test_client()


@pytest.fixture
def usuario_test(app, db):
    """
    Crea un usuario de prueba.

    Returns:
        Usuario: objeto Usuario para usar en tests
    """
    from app.models import Usuario

    usuario = Usuario(
        correo='test@ejemplo.com',
        nombre='Usuario Test',
        rol='admin',
        activo=True
    )
    usuario.establecer_contrasena('test123')
    db.session.add(usuario)
    db.session.commit()

    return usuario


@pytest.fixture
def cuenta_gmail_test(app, db, usuario_test):
    """
    Crea una cuenta Gmail de prueba.

    Returns:
        CuentaGmail: objeto CuentaGmail para usar en tests
    """
    from app.models import CuentaGmail

    cuenta = CuentaGmail(
        usuario_id=usuario_test.id,
        correo_gmail='test@gmail.com',
        activa=True
    )
    # Establecer contraseña encriptada (usa método del modelo si existe)
    cuenta.establecer_contrasena('fake-app-password')
    db.session.add(cuenta)
    db.session.commit()

    return cuenta


@pytest.fixture
def escaneo_test(app, db, usuario_test):
    """
    Crea un escaneo de prueba.

    Returns:
        Escaneo: objeto Escaneo para usar en tests
    """
    from app.models import Escaneo
    from datetime import datetime

    escaneo = Escaneo(
        usuario_id=usuario_test.id,
        estado='en_progreso',
        fecha_inicio=datetime.utcnow()
    )
    db.session.add(escaneo)
    db.session.commit()

    return escaneo


@pytest.fixture
def compania_test(app, db):
    """
    Crea una compañía de prueba.

    Returns:
        Compania: objeto Compania para usar en tests
    """
    from app.models import Compania
    from datetime import datetime

    compania = Compania(
        nombre='Test Seguros S.A.',
        dominio_email='testseguros.com',
        cantidad_documentos=0,
        fecha_primer_documento=datetime.utcnow()
    )
    db.session.add(compania)
    db.session.commit()

    return compania
