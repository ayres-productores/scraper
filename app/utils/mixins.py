"""
Mixins reutilizables para modelos SQLAlchemy.

Estos mixins proporcionan funcionalidad común que puede ser
heredada por múltiples modelos, eliminando duplicación de código.
"""

from datetime import datetime
from flask_login import current_user

from app import db


class TimestampMixin:
    """
    Mixin que agrega campos de timestamp automáticos.

    Campos:
        fecha_creacion: Fecha de creación del registro
        fecha_actualizacion: Fecha de última actualización
    """
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow,
                                     onupdate=datetime.utcnow, nullable=False)


class AuditableMixin:
    """
    Mixin que agrega campos de auditoría.

    Campos:
        creado_por_id: ID del usuario que creó el registro
        modificado_por_id: ID del usuario que modificó el registro
        fecha_creacion: Timestamp de creación
        fecha_modificacion: Timestamp de modificación
    """
    creado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    modificado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_modificacion = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def marcar_creacion(self, usuario_id=None):
        """Marca el registro como creado por el usuario actual o especificado."""
        if usuario_id:
            self.creado_por_id = usuario_id
        elif current_user and current_user.is_authenticated:
            self.creado_por_id = current_user.id

    def marcar_modificacion(self, usuario_id=None):
        """Marca el registro como modificado por el usuario actual o especificado."""
        if usuario_id:
            self.modificado_por_id = usuario_id
        elif current_user and current_user.is_authenticated:
            self.modificado_por_id = current_user.id


class UserScopedMixin:
    """
    Mixin para modelos que pertenecen a un usuario específico.

    Proporciona métodos de clase para filtrar consultas automáticamente
    por el usuario actual, eliminando la necesidad de repetir
    .filter_by(usuario_id=current_user.id) en cada query.

    Requisito: El modelo debe tener un campo `usuario_id`
    """

    @classmethod
    def por_usuario(cls, usuario):
        """
        Retorna query filtrada por usuario.

        Args:
            usuario: Usuario por el cual filtrar

        Returns:
            Query filtrada

        Uso:
            cuentas = CuentaGmail.por_usuario(current_user).all()
            cuenta = CuentaGmail.por_usuario(current_user).filter_by(id=1).first()
        """
        return cls.query.filter_by(usuario_id=usuario.id)

    @classmethod
    def del_usuario_actual(cls):
        """
        Retorna query filtrada por el usuario actual (current_user).

        Returns:
            Query filtrada o None si no hay usuario autenticado

        Uso:
            clientes = Cliente.del_usuario_actual().all()
        """
        if current_user and current_user.is_authenticated:
            return cls.query.filter_by(usuario_id=current_user.id)
        return cls.query.filter(False)  # Query vacía si no hay usuario

    @classmethod
    def obtener_del_usuario(cls, id, usuario):
        """
        Obtiene un registro verificando que pertenezca al usuario.

        Args:
            id: ID del registro
            usuario: Usuario propietario esperado

        Returns:
            Instancia del modelo o None

        Uso:
            cuenta = CuentaGmail.obtener_del_usuario(cuenta_id, current_user)
        """
        return cls.query.filter_by(id=id, usuario_id=usuario.id).first()

    @classmethod
    def obtener_o_404(cls, id, usuario):
        """
        Obtiene un registro verificando propiedad, o lanza 404.

        Args:
            id: ID del registro
            usuario: Usuario propietario esperado

        Returns:
            Instancia del modelo

        Raises:
            404 si no existe o no pertenece al usuario
        """
        return cls.query.filter_by(id=id, usuario_id=usuario.id).first_or_404()

    def pertenece_a(self, usuario):
        """
        Verifica si este registro pertenece al usuario dado.

        Args:
            usuario: Usuario a verificar

        Returns:
            bool
        """
        return self.usuario_id == usuario.id


class SoftDeleteMixin:
    """
    Mixin para eliminación lógica (soft delete).

    En lugar de eliminar registros, los marca como eliminados.
    """
    eliminado = db.Column(db.Boolean, default=False, index=True)
    fecha_eliminacion = db.Column(db.DateTime, nullable=True)
    eliminado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    def eliminar_logico(self, usuario_id=None):
        """Marca el registro como eliminado."""
        self.eliminado = True
        self.fecha_eliminacion = datetime.utcnow()
        if usuario_id:
            self.eliminado_por_id = usuario_id
        elif current_user and current_user.is_authenticated:
            self.eliminado_por_id = current_user.id

    def restaurar(self):
        """Restaura un registro eliminado lógicamente."""
        self.eliminado = False
        self.fecha_eliminacion = None
        self.eliminado_por_id = None

    @classmethod
    def activos(cls):
        """Retorna query de registros no eliminados."""
        return cls.query.filter_by(eliminado=False)

    @classmethod
    def eliminados(cls):
        """Retorna query de registros eliminados."""
        return cls.query.filter_by(eliminado=True)
