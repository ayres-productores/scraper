"""
Portal de Extracción de Pólizas de Seguros
Aplicación Flask con autenticación segura
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_bcrypt import Bcrypt
import os
import sys

# Diagnóstico de inicialización
import logging
_init_logger = logging.getLogger('app.init')

def _diag(msg):
    """Log de diagnóstico durante inicialización."""
    _init_logger.debug(f"[INIT] {msg}")

_diag("Cargando extensiones Flask...")
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
bcrypt = Bcrypt()
_diag("Extensiones cargadas OK")


def get_base_path():
    """Obtiene la ruta base, funciona tanto en desarrollo como en ejecutable."""
    if getattr(sys, 'frozen', False):
        # Ejecutando como ejecutable (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Ejecutando como script Python
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(config_class=None):
    """Factory de la aplicación Flask."""
    _diag("create_app() iniciando...")

    # Determinar rutas para templates y static
    if getattr(sys, 'frozen', False):
        _diag("Modo: ejecutable PyInstaller")
        # Modo ejecutable: buscar en el directorio de la aplicacion
        base_path = os.path.dirname(sys.executable)
        template_folder = os.path.join(base_path, 'app', 'templates')
        static_folder = os.path.join(base_path, 'app', 'static')
        app = Flask(__name__,
                    template_folder=template_folder,
                    static_folder=static_folder)
    else:
        _diag("Modo: desarrollo (script)")
        # Modo desarrollo normal
        app = Flask(__name__)

    # Configuración
    _diag("Cargando configuración...")
    if config_class:
        app.config.from_object(config_class)
    else:
        from app.config import Config
        app.config.from_object(Config)
    _diag("Configuración cargada OK")

    # Inicializar extensiones
    _diag("Inicializando extensiones en app...")
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    bcrypt.init_app(app)
    _diag("Extensiones inicializadas OK")

    # Configuración de login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Por favor inicia sesión para acceder a esta página.'
    login_manager.login_message_category = 'warning'

    # Registrar blueprints
    _diag("Importando blueprints...")
    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    from app.admin.routes import admin_bp
    from app.distribucion.routes import distribucion_bp
    from app.api.routes import api_bp
    _diag("Blueprints importados OK")

    _diag("Registrando blueprints...")
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(distribucion_bp, url_prefix='/distribucion')
    app.register_blueprint(api_bp, url_prefix='/api')
    _diag("Blueprints registrados OK")

    # Eximir webhook de WhatsApp de CSRF (recibe POSTs de Meta)
    csrf.exempt(api_bp)

    # Crear tablas y usuario admin por defecto
    _diag("Creando contexto de app y tablas...")
    with app.app_context():
        db.create_all()
        _diag("Tablas creadas OK")

        # Configurar PRAGMAs de SQLite para TODAS las conexiones
        # Esto se ejecuta cada vez que se crea una nueva conexión al pool
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout=120000")  # 120 segundos
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        _diag("SQLite WAL mode habilitado (via event listener)")

        crear_admin_por_defecto()
        _diag("Admin verificado OK")

    # Sincronizar archivos disco <-> BD en background (no bloquea el boot)
    _iniciar_sincronizacion_background(app)

    # Iniciar procesador de cola de WhatsApp (solo si no es el proceso de recarga)
    _diag(f"Verificando WhatsApp processor... WERKZEUG_RUN_MAIN={os.environ.get('WERKZEUG_RUN_MAIN')}, debug={app.debug}")
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        _diag("Iniciando procesador WhatsApp...")
        from app.distribucion.whatsapp_sender import iniciar_procesador_whatsapp
        iniciar_procesador_whatsapp(app)
        _diag("Procesador WhatsApp iniciado OK")
    else:
        _diag("WhatsApp processor OMITIDO (proceso padre de reloader)")

    # Headers de seguridad
    @app.after_request
    def agregar_headers_seguridad(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    _diag("create_app() completado exitosamente")
    return app


def crear_admin_por_defecto():
    """Crea el usuario administrador por defecto si no existe."""
    from app.models import Usuario

    admin = Usuario.query.filter_by(correo='admin@empresa.com').first()
    if not admin:
        admin = Usuario(
            correo='admin@empresa.com',
            nombre='Administrador',
            rol='admin',
            debe_cambiar_contrasena=True
        )
        admin.establecer_contrasena('CambiarEnPrimerLogin123!')
        db.session.add(admin)
        db.session.commit()
        _init_logger.info('Usuario administrador creado: admin@empresa.com')


def _iniciar_sincronizacion_background(app):
    """Inicia la sincronización de archivos en un thread background.

    Usa thread_session para garantizar que las operaciones de BD sean
    thread-safe y no tengan problemas de sesiones detached.
    """
    import threading

    def _sync_worker():
        """Worker que ejecuta la sincronización con contexto de app."""
        _diag("Iniciando sincronización en background...")
        try:
            from app.utils.db_session import thread_session
            with thread_session(app) as session:
                sincronizar_archivos(session)
            _diag("Sincronización background completada")
        except Exception as e:
            _diag(f"Error en sincronización background: {e}")

    # Solo ejecutar en el proceso principal (evitar duplicados en reloader)
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        thread = threading.Thread(target=_sync_worker, daemon=True, name="SyncArchivos")
        thread.start()
        _diag("Thread de sincronización iniciado")
    else:
        _diag("Sincronización background OMITIDA (proceso padre de reloader)")


def sincronizar_archivos(db_session=None):
    """
    Sincroniza los archivos en disco con la base de datos al iniciar.

    Solo elimina registros de BD cuyos archivos ya no existen en disco.
    La detección de nuevos archivos la hace el extractor_server.

    Args:
        db_session: Sesión SQLAlchemy thread-safe (opcional, usa db.session si no se provee)
    """
    from app.models import ArchivoDescargado, RegistroAnalisisPDF

    # Usar la sesión proporcionada o db.session como fallback
    if db_session is None:
        db_session = db.session

    _diag("Sincronizando archivos disco <-> BD...")

    huerfanos = 0

    # Eliminar registros huérfanos (archivos en BD que no existen en disco)
    for archivo in db_session.query(ArchivoDescargado).all():
        if not os.path.exists(archivo.ruta_archivo):
            # Eliminar registros relacionados primero
            db_session.query(RegistroAnalisisPDF).filter_by(archivo_id=archivo.id).delete()
            db_session.delete(archivo)
            huerfanos += 1

    if huerfanos > 0:
        db_session.commit()
        _diag(f"Sincronización: {huerfanos} huérfanos eliminados")
    else:
        _diag("Sincronización: sin cambios")
