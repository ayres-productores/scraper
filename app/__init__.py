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

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
bcrypt = Bcrypt()


def create_app(config_class=None):
    """Factory de la aplicación Flask."""
    app = Flask(__name__)

    # Configuración
    if config_class:
        app.config.from_object(config_class)
    else:
        from app.config import Config
        app.config.from_object(Config)

    # Inicializar extensiones
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    bcrypt.init_app(app)

    # Configuración de login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Por favor inicia sesión para acceder a esta página.'
    login_manager.login_message_category = 'warning'

    # Registrar blueprints
    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    from app.extractor.routes import extractor_bp
    from app.admin.routes import admin_bp
    from app.distribucion.routes import distribucion_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(extractor_bp, url_prefix='/extractor')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(distribucion_bp, url_prefix='/distribucion')

    # Crear tablas y usuario admin por defecto
    with app.app_context():
        db.create_all()
        crear_admin_por_defecto()

    # Iniciar procesador de cola de WhatsApp (solo si no es el proceso de recarga)
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        from app.distribucion.whatsapp_sender import iniciar_procesador_whatsapp
        iniciar_procesador_whatsapp(app)

    # Headers de seguridad
    @app.after_request
    def agregar_headers_seguridad(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

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
        print('Usuario administrador creado: admin@empresa.com')
