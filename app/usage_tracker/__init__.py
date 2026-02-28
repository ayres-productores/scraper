"""
Flask Usage Tracker - Módulo reutilizable para tracking de uso.

Uso básico:
    from app.usage_tracker import UsageTracker
    tracker = UsageTracker(app)

Con factory pattern:
    tracker = UsageTracker()
    tracker.init_app(app)

Configuración (en config.py):
    USAGE_TRACKER_ENABLED = True
    USAGE_TRACKER_ENDPOINT = '/api/analytics/track'
    USAGE_TRACKER_BATCH_SIZE = 10
    USAGE_TRACKER_BATCH_TIMEOUT = 5000
"""

from flask import Blueprint

usage_tracker_bp = Blueprint(
    'usage_tracker',
    __name__,
    template_folder='templates',
    url_prefix='/analytics'
)


class UsageTracker:
    """Extensión Flask para tracking de uso de la aplicación."""

    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Inicializa el tracker con la aplicación Flask."""
        # Configuración por defecto
        app.config.setdefault('USAGE_TRACKER_ENABLED', True)
        app.config.setdefault('USAGE_TRACKER_ENDPOINT', '/api/analytics/track')
        app.config.setdefault('USAGE_TRACKER_BATCH_SIZE', 10)
        app.config.setdefault('USAGE_TRACKER_BATCH_TIMEOUT', 5000)
        app.config.setdefault('USAGE_TRACKER_TRACK_ELEMENTS',
                              'a, button, .btn, .nav-link, [data-track], input[type="submit"]')
        app.config.setdefault('USAGE_TRACKER_EXCLUDE_PATHS', ['/static/', '/api/analytics/'])

        # Registrar blueprint
        from app.usage_tracker import routes  # noqa: F401
        app.register_blueprint(usage_tracker_bp)

        # Context processor para inyectar config en templates
        @app.context_processor
        def inject_tracker_config():
            return {
                'usage_tracker_enabled': app.config['USAGE_TRACKER_ENABLED'],
                'usage_tracker_config': {
                    'endpoint': app.config['USAGE_TRACKER_ENDPOINT'],
                    'batchSize': app.config['USAGE_TRACKER_BATCH_SIZE'],
                    'batchTimeout': app.config['USAGE_TRACKER_BATCH_TIMEOUT'],
                    'trackElements': app.config['USAGE_TRACKER_TRACK_ELEMENTS'],
                    'excludePaths': app.config['USAGE_TRACKER_EXCLUDE_PATHS']
                }
            }

        # Guardar referencia
        app.extensions = getattr(app, 'extensions', {})
        app.extensions['usage_tracker'] = self
