"""
Utilidades comunes para la aplicación.

Este módulo contiene decoradores, mixins y funciones auxiliares
que eliminan código duplicado en la aplicación.
"""

from app.utils.decoradores import (
    login_requerido_json,
    propietario_requerido,
    admin_requerido,
    gestor_usuarios_requerido,
    auditar_accion
)
from app.utils.mixins import UserScopedMixin, AuditableMixin, TimestampMixin

__all__ = [
    'login_requerido_json',
    'propietario_requerido',
    'admin_requerido',
    'gestor_usuarios_requerido',
    'auditar_accion',
    'UserScopedMixin',
    'AuditableMixin',
    'TimestampMixin'
]
