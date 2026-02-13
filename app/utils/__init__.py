"""
Utilidades comunes para la aplicación.

Este módulo contiene decoradores, mixins, funciones auxiliares
y gestión de sesiones thread-safe para la aplicación.
"""

from app.utils.decoradores import (
    login_requerido_json,
    propietario_requerido,
    admin_requerido,
    gestor_usuarios_requerido,
    auditar_accion
)
from app.utils.mixins import UserScopedMixin, AuditableMixin, TimestampMixin
from app.utils.db_session import (
    thread_session,
    thread_session_no_autocommit,
    cleanup_session_factory
)
from app.utils.database_gateway import (
    db_gateway,
    DatabaseGateway,
    DatabaseError,
    DatabaseLockError,
    DatabaseIntegrityError
)
from app.utils.structured_logger import (
    log_operacion,
    log_extraccion,
    log_whatsapp,
    log_seguridad,
    log_bd,
    get_operations_logger
)
from app.utils.task_progress import task_store, TaskProgressStore
from app.utils.encryption import (
    encrypt_credential,
    decrypt_credential,
    generate_salt,
    migrate_credential
)

__all__ = [
    # Decoradores
    'login_requerido_json',
    'propietario_requerido',
    'admin_requerido',
    'gestor_usuarios_requerido',
    'auditar_accion',
    # Mixins
    'UserScopedMixin',
    'AuditableMixin',
    'TimestampMixin',
    # Sesiones thread-safe (legacy)
    'thread_session',
    'thread_session_no_autocommit',
    'cleanup_session_factory',
    # Database Gateway (recomendado)
    'db_gateway',
    'DatabaseGateway',
    'DatabaseError',
    'DatabaseLockError',
    'DatabaseIntegrityError',
    # Logging estructurado
    'log_operacion',
    'log_extraccion',
    'log_whatsapp',
    'log_seguridad',
    'log_bd',
    'get_operations_logger',
    # Task progress (thread-safe)
    'task_store',
    'TaskProgressStore',
    # Encriptación segura
    'encrypt_credential',
    'decrypt_credential',
    'generate_salt',
    'migrate_credential',
]
