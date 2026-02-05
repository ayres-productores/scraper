"""
Decoradores reutilizables para la aplicación.

Estos decoradores eliminan la duplicación de código en las rutas
para verificación de permisos, autenticación y auditoría.
"""

from functools import wraps
from flask import redirect, url_for, flash, jsonify, request, abort
from flask_login import current_user

from app.models import LogActividad


def login_requerido_json(f):
    """
    Decorador para rutas que retornan JSON.
    Retorna error JSON en lugar de redirección si no está autenticado.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'No autenticado', 'code': 'AUTH_REQUIRED'}), 401
        return f(*args, **kwargs)
    return decorated_function


def admin_requerido(f):
    """
    Decorador que requiere rol de administrador.
    Redirige a dashboard si no tiene permisos.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.es_admin():
            flash('Acceso denegado. Se requieren permisos de administrador.', 'danger')
            return redirect(url_for('main.dashboard'))
        if current_user.debe_cambiar_contrasena:
            return redirect(url_for('auth.cambiar_contrasena_obligatorio'))
        return f(*args, **kwargs)
    return decorated_function


def gestor_usuarios_requerido(f):
    """
    Decorador que requiere permisos de gestión de usuarios.
    Admin y PowerUser pueden gestionar usuarios.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.puede_gestionar_usuarios():
            flash('Acceso denegado. No tienes permisos para gestionar usuarios.', 'danger')
            return redirect(url_for('main.dashboard'))
        if current_user.debe_cambiar_contrasena:
            return redirect(url_for('auth.cambiar_contrasena_obligatorio'))
        return f(*args, **kwargs)
    return decorated_function


def propietario_requerido(modelo, id_param='id', campo_usuario='usuario_id'):
    """
    Decorador que verifica que el recurso pertenezca al usuario actual.

    Args:
        modelo: Clase del modelo SQLAlchemy
        id_param: Nombre del parámetro en la URL que contiene el ID
        campo_usuario: Nombre del campo que contiene el usuario_id en el modelo

    Uso:
        @propietario_requerido(CuentaGmail, 'cuenta_id', 'usuario_id')
        def mi_ruta(cuenta_id):
            # cuenta ya está verificada
            pass
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))

            recurso_id = kwargs.get(id_param)
            if not recurso_id:
                abort(400, description="ID de recurso no especificado")

            recurso = modelo.query.get(recurso_id)
            if not recurso:
                abort(404, description="Recurso no encontrado")

            # Verificar propiedad
            usuario_id_recurso = getattr(recurso, campo_usuario, None)
            if usuario_id_recurso != current_user.id:
                # Admins pueden acceder a todo
                if not current_user.es_admin():
                    abort(403, description="No tienes acceso a este recurso")

            # Inyectar el recurso en kwargs para uso en la función
            kwargs['_recurso'] = recurso
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def auditar_accion(accion, detalle_func=None):
    """
    Decorador que registra automáticamente una acción en el log de actividad.

    Args:
        accion: Nombre de la acción (ej: 'crear_usuario', 'eliminar_archivo')
        detalle_func: Función opcional que recibe los argumentos y retorna el detalle

    Uso:
        @auditar_accion('crear_cliente', lambda **kw: f"Cliente: {kw.get('nombre')}")
        def crear_cliente(nombre, telefono):
            pass
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            resultado = f(*args, **kwargs)

            # Generar detalle
            if detalle_func:
                detalle = detalle_func(**kwargs)
            else:
                detalle = f.__doc__ or f"Acción: {accion}"

            # Registrar solo si hay usuario autenticado
            if current_user.is_authenticated:
                try:
                    LogActividad.registrar(
                        current_user.id,
                        accion,
                        detalle,
                        request
                    )
                except Exception:
                    pass  # No fallar la operación por error de auditoría

            return resultado
        return decorated_function
    return decorator


def validar_contrasena_segura(contrasena):
    """
    Valida que una contraseña cumpla con los requisitos de seguridad.

    Returns:
        Tuple[bool, str]: (es_valida, mensaje_error)
    """
    import re

    if len(contrasena) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres"

    if not re.search(r'[A-Z]', contrasena):
        return False, "La contraseña debe contener al menos una mayúscula"

    if not re.search(r'[a-z]', contrasena):
        return False, "La contraseña debe contener al menos una minúscula"

    if not re.search(r'\d', contrasena):
        return False, "La contraseña debe contener al menos un número"

    return True, "OK"


def validar_next_url(next_url, default='/'):
    """
    Valida que una URL de redirección sea segura (local).

    Args:
        next_url: URL a validar
        default: URL por defecto si la validación falla

    Returns:
        URL segura para redirección
    """
    if not next_url:
        return default

    # Solo permitir URLs locales que empiecen con /
    # y no sean protocol-relative (//)
    if next_url.startswith('/') and not next_url.startswith('//'):
        return next_url

    return default
