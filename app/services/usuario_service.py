"""
Servicio de gestión de usuarios.

Encapsula la lógica de negocio relacionada con usuarios,
autenticación y autorización.
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from flask import current_app

from app import db
from app.models import Usuario, LogActividad


class UsuarioService:
    """Servicio para operaciones de usuarios."""

    @staticmethod
    def autenticar(correo: str, contrasena: str, request=None) -> Tuple[Optional[Usuario], str]:
        """
        Autentica un usuario por correo y contraseña.

        Returns:
            Tuple[Usuario|None, str]: Usuario autenticado y mensaje de estado
        """
        usuario = Usuario.query.filter_by(correo=correo).first()

        if not usuario:
            return None, "Credenciales inválidas"

        if not usuario.activo:
            LogActividad.registrar(
                usuario.id, 'login_inactivo',
                'Intento de login con cuenta inactiva', request
            )
            return None, "Cuenta desactivada. Contacte al administrador."

        if usuario.esta_bloqueado():
            minutos_restantes = int((usuario.bloqueado_hasta - datetime.utcnow()).total_seconds() / 60) + 1
            LogActividad.registrar(
                usuario.id, 'login_bloqueado',
                'Intento de login con cuenta bloqueada', request
            )
            return None, f"Cuenta bloqueada. Intente en {minutos_restantes} minutos."

        if not usuario.verificar_contrasena(contrasena):
            usuario.registrar_intento_fallido()
            intentos_restantes = current_app.config['INTENTOS_LOGIN_MAX'] - usuario.intentos_fallidos
            LogActividad.registrar(
                usuario.id, 'login_fallido',
                f'Contraseña incorrecta. Intentos restantes: {intentos_restantes}', request
            )
            return None, "Credenciales inválidas"

        # Login exitoso
        usuario.resetear_intentos()
        LogActividad.registrar(
            usuario.id, 'login_exitoso',
            f'Inicio de sesión desde {request.remote_addr if request else "desconocido"}', request
        )

        return usuario, "OK"

    @staticmethod
    def crear_usuario(correo: str, nombre: str, rol: str, contrasena: str,
                      creado_por: Usuario = None) -> Tuple[Optional[Usuario], str]:
        """
        Crea un nuevo usuario.

        Returns:
            Tuple[Usuario|None, str]: Usuario creado y mensaje de estado
        """
        # Validar que el correo no exista
        if Usuario.query.filter_by(correo=correo).first():
            return None, "Ya existe un usuario con ese correo"

        # Validar rol si hay creador
        if creado_por and rol not in creado_por.roles_que_puede_crear():
            return None, "No tienes permisos para crear usuarios con ese rol"

        usuario = Usuario(
            correo=correo,
            nombre=nombre,
            rol=rol,
            debe_cambiar_contrasena=True
        )
        usuario.establecer_contrasena(contrasena)

        db.session.add(usuario)
        db.session.commit()

        return usuario, "Usuario creado exitosamente"

    @staticmethod
    def cambiar_contrasena(usuario: Usuario, contrasena_actual: str,
                           nueva_contrasena: str) -> Tuple[bool, str]:
        """
        Cambia la contraseña de un usuario verificando la actual.

        Returns:
            Tuple[bool, str]: Éxito y mensaje
        """
        if not usuario.verificar_contrasena(contrasena_actual):
            return False, "La contraseña actual es incorrecta"

        usuario.establecer_contrasena(nueva_contrasena)
        usuario.debe_cambiar_contrasena = False
        db.session.commit()

        return True, "Contraseña actualizada exitosamente"

    @staticmethod
    def resetear_contrasena(usuario: Usuario, nueva_contrasena: str) -> None:
        """Resetea la contraseña de un usuario (admin)."""
        usuario.establecer_contrasena(nueva_contrasena)
        usuario.debe_cambiar_contrasena = True
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None
        db.session.commit()

    @staticmethod
    def desbloquear(usuario: Usuario) -> None:
        """Desbloquea un usuario bloqueado."""
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None
        db.session.commit()

    @staticmethod
    def obtener_por_id(usuario_id: int) -> Optional[Usuario]:
        """Obtiene un usuario por ID."""
        return Usuario.query.get(usuario_id)

    @staticmethod
    def listar_usuarios(solo_activos: bool = False) -> List[Usuario]:
        """Lista todos los usuarios."""
        query = Usuario.query
        if solo_activos:
            query = query.filter_by(activo=True)
        return query.order_by(Usuario.nombre).all()

    @staticmethod
    def puede_gestionar(gestor: Usuario, objetivo: Usuario) -> bool:
        """Verifica si un usuario puede gestionar a otro."""
        if gestor.id == objetivo.id:
            return False  # No puede gestionarse a sí mismo (excepto perfil)
        return gestor.puede_gestionar_usuario(objetivo)
