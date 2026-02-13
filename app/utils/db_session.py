"""
Gestión de sesiones SQLAlchemy thread-safe.

Este módulo proporciona un context manager para manejar sesiones de base de datos
de forma segura en threads background (escaneos, procesador WhatsApp, etc.).

NOTA: Para nuevo código, se recomienda usar DatabaseGateway:
    from app.utils.database_gateway import db_gateway

    # Operaciones de lectura con retry automático
    usuarios = db_gateway.read(lambda s: s.query(Usuario).all())

    # Operaciones de escritura con commit y retry
    db_gateway.write(lambda s: s.add(Usuario(nombre="Juan")))

Este módulo (thread_session) se mantiene para compatibilidad con código existente.

Problema que resuelve:
    SQLAlchemy sessions están ligadas al thread que las creó. Cuando un thread
    background intenta usar objetos cargados desde otro thread (o la sesión del
    request de Flask), ocurren errores como:
    - DetachedInstanceError: Instance is not bound to a Session
    - InvalidRequestError: Object already attached to session

Uso:
    from app.utils.db_session import thread_session

    def mi_funcion_en_thread():
        with thread_session() as session:
            usuario = session.query(Usuario).get(1)
            usuario.nombre = "Nuevo nombre"
            # commit automático al salir del with
"""

import logging
from contextlib import contextmanager
from threading import current_thread

from flask import current_app, has_app_context
from sqlalchemy.orm import scoped_session, sessionmaker

logger = logging.getLogger(__name__)

# Cache de session factories por app
_session_factories = {}


def _get_session_factory(app):
    """
    Obtiene o crea un session factory para la app dada.

    Usa scoped_session para que cada thread tenga su propia sesión.
    Los PRAGMAs de SQLite se configuran globalmente en __init__.py.
    """
    app_id = id(app)

    if app_id not in _session_factories:
        from app import db

        # Crear un sessionmaker vinculado al engine de la app
        factory = sessionmaker(bind=db.engine)

        # Wrap con scoped_session para thread-safety
        # Cada thread obtiene su propia sesión
        _session_factories[app_id] = scoped_session(factory)

        logger.debug(f"[DB] Session factory creado para app {app_id}")

    return _session_factories[app_id]


@contextmanager
def thread_session(app=None):
    """
    Context manager thread-safe para sesiones SQLAlchemy.

    Crea una sesión independiente para el thread actual, garantizando:
    - Aislamiento: cada thread tiene su propia sesión
    - Commit automático: si no hay errores, hace commit al salir
    - Rollback automático: si hay excepción, hace rollback
    - Limpieza: siempre cierra/remueve la sesión al finalizar

    Args:
        app: Instancia de Flask app. Si no se proporciona, usa current_app.
             Necesario cuando se llama desde threads sin app_context.

    Yields:
        Session: Sesión SQLAlchemy thread-safe

    Ejemplo:
        def procesar_en_thread(app, item_id):
            with thread_session(app) as session:
                item = session.query(MiModelo).get(item_id)
                item.procesado = True
                # commit automático

    Nota:
        Los objetos cargados dentro del with NO deben usarse fuera de él.
        Si necesitas datos fuera, extráelos a variables simples (int, str, dict).
    """
    # Determinar la app a usar
    if app is None:
        if has_app_context():
            app = current_app._get_current_object()
        else:
            raise RuntimeError(
                "thread_session() requiere app_context o parámetro 'app'. "
                "Usa: with thread_session(mi_app) as session: ..."
            )

    # Asegurar que tenemos app_context
    # Esto es necesario para que db.engine esté disponible
    ctx = None
    if not has_app_context():
        ctx = app.app_context()
        ctx.push()

    session_factory = _get_session_factory(app)
    session = session_factory()

    thread_name = current_thread().name
    logger.debug(f"[DB] Sesión iniciada en thread '{thread_name}'")

    try:
        yield session

        # Si llegamos aquí sin excepción, hacer commit
        session.commit()
        logger.debug(f"[DB] Commit exitoso en thread '{thread_name}'")

    except Exception as e:
        # Rollback en caso de error
        session.rollback()
        logger.error(f"[DB] Rollback en thread '{thread_name}': {e}")
        raise

    finally:
        # Siempre limpiar la sesión
        session_factory.remove()
        logger.debug(f"[DB] Sesión removida en thread '{thread_name}'")

        # Limpiar app_context si lo creamos nosotros
        if ctx is not None:
            ctx.pop()


@contextmanager
def thread_session_no_autocommit(app=None):
    """
    Variante de thread_session sin commit automático.

    Útil cuando necesitas control manual del commit, por ejemplo
    para hacer múltiples operaciones en una transacción.

    Ejemplo:
        with thread_session_no_autocommit(app) as session:
            session.add(obj1)
            session.add(obj2)
            if todo_ok:
                session.commit()
            else:
                session.rollback()
    """
    if app is None:
        if has_app_context():
            app = current_app._get_current_object()
        else:
            raise RuntimeError("thread_session_no_autocommit() requiere app_context o parámetro 'app'.")

    ctx = None
    if not has_app_context():
        ctx = app.app_context()
        ctx.push()

    session_factory = _get_session_factory(app)
    session = session_factory()

    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session_factory.remove()
        if ctx is not None:
            ctx.pop()


def cleanup_session_factory(app=None):
    """
    Limpia el session factory de una app específica.

    Útil para testing o cuando se reinicia la app.
    """
    if app is None:
        if has_app_context():
            app = current_app._get_current_object()
        else:
            return

    app_id = id(app)
    if app_id in _session_factories:
        _session_factories[app_id].remove()
        del _session_factories[app_id]
        logger.debug(f"[DB] Session factory limpiado para app {app_id}")
