"""
Gateway centralizado para acceso a base de datos.

Este módulo proporciona un punto único de acceso para todas las operaciones
de base de datos, garantizando:
- Thread-safety automático
- Retry con backoff exponencial para locks
- Manejo uniforme de errores
- Logging centralizado de operaciones
- Métricas de performance (opcional)

Uso básico:
    from app.utils.database_gateway import db_gateway

    # Leer datos
    resultado = db_gateway.read(lambda s: s.query(Usuario).all())

    # Escribir datos
    db_gateway.write(lambda s: s.add(nuevo_usuario))

    # Con decoradores
    @db_gateway.with_read_session
    def obtener_usuarios(session):
        return session.query(Usuario).all()

    @db_gateway.with_write_session
    def crear_usuario(session, nombre):
        usuario = Usuario(nombre=nombre)
        session.add(usuario)
        return usuario
"""

import logging
import time
import functools
from contextlib import contextmanager
from threading import Lock, current_thread, local
from typing import TypeVar, Callable, Optional, Any, List
from datetime import datetime

from flask import current_app, has_app_context
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.exc import OperationalError, IntegrityError

logger = logging.getLogger(__name__)

T = TypeVar('T')


class DatabaseError(Exception):
    """Error base para operaciones de base de datos."""
    pass


class DatabaseLockError(DatabaseError):
    """Error cuando la base de datos está bloqueada después de todos los reintentos."""
    pass


class DatabaseIntegrityError(DatabaseError):
    """Error de integridad de datos (duplicados, FK violations, etc.)."""
    pass


class DatabaseGateway:
    """
    Gateway centralizado para todas las operaciones de base de datos.

    Proporciona métodos thread-safe para leer y escribir datos con
    manejo automático de errores, reintentos y logging.

    Attributes:
        max_retries: Número máximo de reintentos para operaciones bloqueadas
        base_delay: Delay base en segundos para backoff exponencial
        max_delay: Delay máximo en segundos entre reintentos
    """

    _instance = None
    _instance_lock = Lock()

    def __new__(cls):
        """Singleton thread-safe con double-checked locking."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        """Inicializa el gateway si no está inicializado."""
        if self._initialized:
            return

        self._lock = Lock()
        self._session_factories = {}
        self._thread_local = local()

        # Configuración de retry
        self.max_retries = 5
        self.base_delay = 0.5  # 0.5 segundos
        self.max_delay = 8.0   # 8 segundos máximo

        # Estadísticas (thread-safe)
        self._stats_lock = Lock()
        self._stats = {
            'reads': 0,
            'writes': 0,
            'retries': 0,
            'errors': 0,
            'total_read_time': 0.0,
            'total_write_time': 0.0,
        }

        self._initialized = True
        logger.debug("[DBGateway] Inicializado")

    # =========================================================================
    # MÉTODOS PÚBLICOS PRINCIPALES
    # =========================================================================

    def read(
        self,
        operation: Callable[['Session'], T],
        app=None,
        description: str = None
    ) -> T:
        """
        Ejecuta una operación de solo lectura en la base de datos.

        La operación recibe una sesión y debe retornar los datos leídos.
        NO debe modificar datos. Si necesita modificar, use write().

        Args:
            operation: Función que recibe session y retorna datos
            app: Flask app (opcional, usa current_app si disponible)
            description: Descripción para logging (opcional)

        Returns:
            Lo que retorne la operación

        Raises:
            DatabaseLockError: Si la BD está bloqueada después de reintentos
            DatabaseError: Para otros errores de BD

        Ejemplo:
            usuarios = db_gateway.read(
                lambda s: s.query(Usuario).filter_by(activo=True).all(),
                description="obtener usuarios activos"
            )
        """
        start_time = time.time()
        desc = description or "read operation"

        try:
            result = self._execute_with_retry(
                operation,
                app=app,
                auto_commit=False,
                description=desc
            )
            self._record_stats('read', time.time() - start_time)
            return result
        except Exception as e:
            self._record_stats('error')
            raise

    def write(
        self,
        operation: Callable[['Session'], T],
        app=None,
        description: str = None
    ) -> T:
        """
        Ejecuta una operación de escritura en la base de datos.

        La operación recibe una sesión y puede modificar datos.
        El commit se hace automáticamente si no hay errores.

        Args:
            operation: Función que recibe session y opcionalmente retorna datos
            app: Flask app (opcional, usa current_app si disponible)
            description: Descripción para logging (opcional)

        Returns:
            Lo que retorne la operación (puede ser None)

        Raises:
            DatabaseLockError: Si la BD está bloqueada después de reintentos
            DatabaseIntegrityError: Para violaciones de integridad (duplicados, etc.)
            DatabaseError: Para otros errores de BD

        Ejemplo:
            db_gateway.write(
                lambda s: s.add(Usuario(nombre="Juan")),
                description="crear usuario Juan"
            )
        """
        start_time = time.time()
        desc = description or "write operation"

        try:
            result = self._execute_with_retry(
                operation,
                app=app,
                auto_commit=True,
                description=desc
            )
            self._record_stats('write', time.time() - start_time)
            return result
        except Exception as e:
            self._record_stats('error')
            raise

    def bulk_write(
        self,
        operations: List[Callable[['Session'], Any]],
        app=None,
        description: str = None,
        stop_on_error: bool = True
    ) -> List[Any]:
        """
        Ejecuta múltiples operaciones de escritura en una transacción.

        Todas las operaciones comparten la misma sesión y transacción.
        Si una falla y stop_on_error=True, hace rollback de todas.

        Args:
            operations: Lista de funciones que reciben session
            app: Flask app (opcional)
            description: Descripción para logging
            stop_on_error: Si True, falla todo si una operación falla

        Returns:
            Lista de resultados de cada operación

        Ejemplo:
            resultados = db_gateway.bulk_write([
                lambda s: s.add(Usuario(nombre="Juan")),
                lambda s: s.add(Usuario(nombre="María")),
            ], description="crear usuarios en lote")
        """
        desc = description or f"bulk write ({len(operations)} ops)"

        def _batch_operation(session):
            results = []
            for i, op in enumerate(operations):
                try:
                    result = op(session)
                    results.append(result)
                except Exception as e:
                    if stop_on_error:
                        logger.error(f"[DBGateway] Error en operación {i+1}: {e}")
                        raise
                    else:
                        logger.warning(f"[DBGateway] Operación {i+1} falló: {e}")
                        results.append(None)
            return results

        return self.write(_batch_operation, app=app, description=desc)

    # =========================================================================
    # DECORADORES
    # =========================================================================

    def with_read_session(self, func: Callable = None, *, description: str = None):
        """
        Decorador que inyecta una sesión de solo lectura.

        La función decorada recibe 'session' como primer argumento.

        Ejemplo:
            @db_gateway.with_read_session
            def obtener_usuarios(session):
                return session.query(Usuario).all()

            @db_gateway.with_read_session(description="buscar cliente")
            def buscar_cliente(session, cliente_id):
                return session.query(Cliente).get(cliente_id)
        """
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                desc = description or f"{fn.__module__}.{fn.__name__}"
                return self.read(
                    lambda s: fn(s, *args, **kwargs),
                    description=desc
                )
            return wrapper

        if func is not None:
            return decorator(func)
        return decorator

    def with_write_session(self, func: Callable = None, *, description: str = None):
        """
        Decorador que inyecta una sesión de escritura con auto-commit.

        La función decorada recibe 'session' como primer argumento.

        Ejemplo:
            @db_gateway.with_write_session
            def crear_usuario(session, nombre):
                usuario = Usuario(nombre=nombre)
                session.add(usuario)
                return usuario

            @db_gateway.with_write_session(description="actualizar perfil")
            def actualizar_perfil(session, usuario_id, datos):
                usuario = session.query(Usuario).get(usuario_id)
                usuario.nombre = datos['nombre']
                return usuario
        """
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                desc = description or f"{fn.__module__}.{fn.__name__}"
                return self.write(
                    lambda s: fn(s, *args, **kwargs),
                    description=desc
                )
            return wrapper

        if func is not None:
            return decorator(func)
        return decorator

    # =========================================================================
    # CONTEXT MANAGERS
    # =========================================================================

    @contextmanager
    def session(self, app=None, auto_commit: bool = True):
        """
        Context manager para obtener una sesión con retry automático.

        Útil cuando necesitas control manual sobre la sesión.

        Args:
            app: Flask app (opcional)
            auto_commit: Si True, hace commit al salir exitosamente

        Yields:
            Session: Sesión SQLAlchemy thread-safe

        Ejemplo:
            with db_gateway.session() as session:
                usuario = session.query(Usuario).get(1)
                usuario.activo = False
                # commit automático al salir
        """
        session = self._get_session(app)
        thread_name = current_thread().name

        try:
            yield session

            if auto_commit:
                self._commit_with_retry(session, description="session context")

        except Exception as e:
            session.rollback()
            logger.error(f"[DBGateway] Rollback en {thread_name}: {e}")
            raise

        finally:
            self._remove_session(app)

    @contextmanager
    def read_session(self, app=None):
        """
        Context manager para sesión de solo lectura (sin auto-commit).

        Ejemplo:
            with db_gateway.read_session() as session:
                usuarios = session.query(Usuario).all()
                # NO hace commit, solo lectura
        """
        with self.session(app=app, auto_commit=False) as session:
            yield session

    @contextmanager
    def write_session(self, app=None):
        """
        Context manager para sesión de escritura (con auto-commit).

        Ejemplo:
            with db_gateway.write_session() as session:
                session.add(Usuario(nombre="Nuevo"))
                # commit automático al salir
        """
        with self.session(app=app, auto_commit=True) as session:
            yield session

    # =========================================================================
    # MÉTODOS DE UTILIDAD
    # =========================================================================

    def query(self, model_class, app=None):
        """
        Inicia una query para un modelo específico.

        Retorna un QueryWrapper que permite encadenar métodos.

        Ejemplo:
            usuarios = db_gateway.query(Usuario).filter_by(activo=True).all()
            usuario = db_gateway.query(Usuario).get(1)
        """
        return QueryWrapper(self, model_class, app)

    def add(self, obj, app=None, description: str = None):
        """
        Agrega un objeto a la base de datos.

        Ejemplo:
            db_gateway.add(Usuario(nombre="Juan"))
        """
        return self.write(
            lambda s: s.add(obj),
            app=app,
            description=description or f"add {obj.__class__.__name__}"
        )

    def add_all(self, objects: List, app=None, description: str = None):
        """
        Agrega múltiples objetos a la base de datos.

        Ejemplo:
            db_gateway.add_all([Usuario(nombre="Juan"), Usuario(nombre="María")])
        """
        return self.write(
            lambda s: s.add_all(objects),
            app=app,
            description=description or f"add_all {len(objects)} objects"
        )

    def delete(self, obj, app=None, description: str = None):
        """
        Elimina un objeto de la base de datos.

        Ejemplo:
            db_gateway.delete(usuario)
        """
        return self.write(
            lambda s: s.delete(obj),
            app=app,
            description=description or f"delete {obj.__class__.__name__}"
        )

    def get_stats(self) -> dict:
        """
        Retorna estadísticas de uso del gateway.

        Returns:
            Dict con contadores de operaciones, tiempos, etc.
        """
        with self._stats_lock:
            return {
                **self._stats,
                'avg_read_time': (
                    self._stats['total_read_time'] / self._stats['reads']
                    if self._stats['reads'] > 0 else 0
                ),
                'avg_write_time': (
                    self._stats['total_write_time'] / self._stats['writes']
                    if self._stats['writes'] > 0 else 0
                ),
            }

    def reset_stats(self):
        """Reinicia las estadísticas."""
        with self._stats_lock:
            for key in self._stats:
                self._stats[key] = 0 if isinstance(self._stats[key], int) else 0.0

    # =========================================================================
    # MÉTODOS INTERNOS
    # =========================================================================

    def _get_session_factory(self, app):
        """Obtiene o crea un session factory para la app."""
        app_id = id(app)

        if app_id not in self._session_factories:
            with self._lock:
                if app_id not in self._session_factories:
                    from app import db
                    factory = sessionmaker(bind=db.engine)
                    self._session_factories[app_id] = scoped_session(factory)
                    logger.debug(f"[DBGateway] Session factory creado para app {app_id}")

        return self._session_factories[app_id]

    def _get_app(self, app=None):
        """Obtiene la app de Flask."""
        if app is not None:
            return app

        if has_app_context():
            return current_app._get_current_object()

        raise RuntimeError(
            "DatabaseGateway requiere app_context o parámetro 'app'. "
            "Usa: db_gateway.read(op, app=mi_app)"
        )

    def _get_session(self, app=None):
        """Obtiene una sesión para el thread actual."""
        app = self._get_app(app)

        # Asegurar app_context
        if not has_app_context():
            ctx = app.app_context()
            ctx.push()
            # Guardar contexto para limpieza posterior
            if not hasattr(self._thread_local, 'contexts'):
                self._thread_local.contexts = []
            self._thread_local.contexts.append(ctx)

        factory = self._get_session_factory(app)
        return factory()

    def _remove_session(self, app=None):
        """Remueve la sesión del thread actual."""
        app = self._get_app(app)
        factory = self._get_session_factory(app)
        factory.remove()

        # Limpiar contextos que creamos
        if hasattr(self._thread_local, 'contexts') and self._thread_local.contexts:
            ctx = self._thread_local.contexts.pop()
            ctx.pop()

    def _execute_with_retry(
        self,
        operation: Callable,
        app=None,
        auto_commit: bool = True,
        description: str = ""
    ):
        """Ejecuta una operación con retry para locks."""
        app = self._get_app(app)
        session = self._get_session(app)
        thread_name = current_thread().name

        try:
            # Ejecutar operación
            result = operation(session)

            # Commit si es necesario
            if auto_commit:
                self._commit_with_retry(session, description)

            return result

        except IntegrityError as e:
            session.rollback()
            logger.error(f"[DBGateway] IntegrityError en {description}: {e}")
            raise DatabaseIntegrityError(f"Error de integridad: {e}") from e

        except Exception as e:
            session.rollback()
            raise

        finally:
            self._remove_session(app)

    def _commit_with_retry(self, session, description: str = ""):
        """Hace commit con retry para manejar locks."""
        for attempt in range(self.max_retries):
            try:
                session.commit()
                return
            except OperationalError as e:
                if 'database is locked' in str(e).lower():
                    if attempt < self.max_retries - 1:
                        delay = min(
                            self.base_delay * (2 ** attempt),
                            self.max_delay
                        )
                        self._record_stats('retry')
                        logger.warning(
                            f"[DBGateway] BD bloqueada en '{description}', "
                            f"reintentando en {delay:.1f}s ({attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        raise DatabaseLockError(
                            f"Base de datos bloqueada después de {self.max_retries} intentos"
                        ) from e
                raise

    def _record_stats(self, operation_type: str, duration: float = 0):
        """Registra estadísticas de operaciones."""
        with self._stats_lock:
            if operation_type == 'read':
                self._stats['reads'] += 1
                self._stats['total_read_time'] += duration
            elif operation_type == 'write':
                self._stats['writes'] += 1
                self._stats['total_write_time'] += duration
            elif operation_type == 'retry':
                self._stats['retries'] += 1
            elif operation_type == 'error':
                self._stats['errors'] += 1


class QueryWrapper:
    """
    Wrapper para queries que permite encadenamiento fluido.

    Proporciona una interfaz similar a session.query() pero con
    retry automático y thread-safety.
    """

    def __init__(self, gateway: DatabaseGateway, model_class, app=None):
        self._gateway = gateway
        self._model_class = model_class
        self._app = app
        self._filters = []
        self._order_by = []
        self._limit_val = None
        self._offset_val = None

    def filter(self, *criterion):
        """Agrega filtros a la query."""
        self._filters.extend(criterion)
        return self

    def filter_by(self, **kwargs):
        """Agrega filtros por igualdad."""
        for key, value in kwargs.items():
            self._filters.append(getattr(self._model_class, key) == value)
        return self

    def order_by(self, *criterion):
        """Agrega ordenamiento."""
        self._order_by.extend(criterion)
        return self

    def limit(self, limit: int):
        """Limita resultados."""
        self._limit_val = limit
        return self

    def offset(self, offset: int):
        """Salta resultados."""
        self._offset_val = offset
        return self

    def _build_query(self, session):
        """Construye la query SQLAlchemy."""
        query = session.query(self._model_class)

        for f in self._filters:
            query = query.filter(f)

        for o in self._order_by:
            query = query.order_by(o)

        if self._limit_val is not None:
            query = query.limit(self._limit_val)

        if self._offset_val is not None:
            query = query.offset(self._offset_val)

        return query

    def all(self) -> List:
        """Ejecuta la query y retorna todos los resultados."""
        return self._gateway.read(
            lambda s: self._build_query(s).all(),
            app=self._app,
            description=f"query {self._model_class.__name__}.all()"
        )

    def first(self):
        """Ejecuta la query y retorna el primer resultado."""
        return self._gateway.read(
            lambda s: self._build_query(s).first(),
            app=self._app,
            description=f"query {self._model_class.__name__}.first()"
        )

    def one(self):
        """Ejecuta la query y retorna exactamente un resultado."""
        return self._gateway.read(
            lambda s: self._build_query(s).one(),
            app=self._app,
            description=f"query {self._model_class.__name__}.one()"
        )

    def one_or_none(self):
        """Ejecuta la query y retorna un resultado o None."""
        return self._gateway.read(
            lambda s: self._build_query(s).one_or_none(),
            app=self._app,
            description=f"query {self._model_class.__name__}.one_or_none()"
        )

    def get(self, id):
        """Obtiene un objeto por su ID primario."""
        return self._gateway.read(
            lambda s: s.query(self._model_class).get(id),
            app=self._app,
            description=f"query {self._model_class.__name__}.get({id})"
        )

    def count(self) -> int:
        """Cuenta los resultados de la query."""
        return self._gateway.read(
            lambda s: self._build_query(s).count(),
            app=self._app,
            description=f"query {self._model_class.__name__}.count()"
        )

    def exists(self) -> bool:
        """Verifica si existen resultados."""
        return self._gateway.read(
            lambda s: self._build_query(s).first() is not None,
            app=self._app,
            description=f"query {self._model_class.__name__}.exists()"
        )


# Instancia singleton global
db_gateway = DatabaseGateway()
