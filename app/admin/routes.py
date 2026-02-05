"""
Rutas del panel de administración
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, Optional
from functools import wraps
from app import db
from app.models import Usuario, LogActividad, Escaneo, CuentaGmail
from app.auth.forms import validar_contrasena_segura
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__)


def admin_requerido(f):
    """Decorador que requiere rol de administrador (solo para funciones exclusivas de admin)."""
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
    """Decorador que requiere poder gestionar usuarios (admin o poweruser)."""
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


class CrearUsuarioForm(FlaskForm):
    """Formulario para crear usuario."""
    correo = StringField('Nombre de usuario', validators=[
        DataRequired(message='El nombre de usuario es requerido'),
        Length(min=3, max=50, message='El usuario debe tener entre 3 y 50 caracteres')
    ])
    nombre = StringField('Nombre completo', validators=[
        DataRequired(message='El nombre es requerido'),
        Length(min=2, max=100)
    ])
    contrasena = PasswordField('Contraseña temporal', validators=[
        DataRequired(message='La contraseña es requerida'),
        validar_contrasena_segura
    ])
    rol = SelectField('Rol', choices=[])  # Se llena dinámicamente según permisos
    submit = SubmitField('Crear Usuario')

    def __init__(self, usuario_actual=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Establecer opciones de rol según permisos del usuario actual
        if usuario_actual:
            roles_permitidos = usuario_actual.roles_que_puede_crear()
            self.rol.choices = [(r, Usuario.ROLES[i][1]) for i, (r, _) in enumerate(Usuario.ROLES) if r in roles_permitidos]
        else:
            # Default: solo collaborator
            self.rol.choices = [('collaborator', 'Collaborator')]


class EditarUsuarioForm(FlaskForm):
    """Formulario para editar usuario."""
    nombre = StringField('Nombre completo', validators=[
        DataRequired(message='El nombre es requerido'),
        Length(min=2, max=100)
    ])
    rol = SelectField('Rol', choices=[])  # Se llena dinámicamente
    activo = BooleanField('Cuenta activa')
    nueva_contrasena = PasswordField('Nueva contraseña (dejar vacío para no cambiar)',
                                      validators=[Optional(), validar_contrasena_segura])
    forzar_cambio = BooleanField('Forzar cambio de contraseña en próximo inicio')
    submit = SubmitField('Guardar Cambios')

    def __init__(self, usuario_actual=None, usuario_editado=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Establecer opciones de rol según permisos
        if usuario_actual and usuario_actual.es_admin():
            # Admin puede asignar cualquier rol (excepto admin a sí mismo por seguridad)
            self.rol.choices = [(r, nombre) for r, nombre in Usuario.ROLES]
        elif usuario_actual:
            # PowerUser solo puede mantener/cambiar a collaborator
            self.rol.choices = [('collaborator', 'Collaborator')]
        else:
            self.rol.choices = [('collaborator', 'Collaborator')]


@admin_bp.route('/')
@login_required
@admin_requerido
def index():
    """Panel principal de administración."""
    # Estadísticas generales
    total_usuarios = Usuario.query.count()
    usuarios_activos = Usuario.query.filter_by(activo=True).count()
    total_escaneos = Escaneo.query.count()
    escaneos_hoy = Escaneo.query.filter(
        Escaneo.fecha_inicio >= datetime.utcnow().date()
    ).count()

    # Últimos usuarios
    ultimos_usuarios = Usuario.query.order_by(
        Usuario.fecha_creacion.desc()
    ).limit(5).all()

    # Últimas actividades
    ultimas_actividades = LogActividad.query.order_by(
        LogActividad.fecha.desc()
    ).limit(10).all()

    return render_template('admin/index.html',
                          total_usuarios=total_usuarios,
                          usuarios_activos=usuarios_activos,
                          total_escaneos=total_escaneos,
                          escaneos_hoy=escaneos_hoy,
                          ultimos_usuarios=ultimos_usuarios,
                          ultimas_actividades=ultimas_actividades)


@admin_bp.route('/usuarios')
@login_required
@gestor_usuarios_requerido
def usuarios():
    """Listado de usuarios."""
    if current_user.es_admin():
        # Admin ve todos los usuarios
        usuarios = Usuario.query.order_by(Usuario.fecha_creacion.desc()).all()
    else:
        # PowerUser solo ve collaborators
        usuarios = Usuario.query.filter_by(rol=Usuario.ROL_COLLABORATOR).order_by(Usuario.fecha_creacion.desc()).all()
    return render_template('admin/usuarios.html', usuarios=usuarios)


@admin_bp.route('/usuarios/crear', methods=['GET', 'POST'])
@login_required
@gestor_usuarios_requerido
def crear_usuario():
    """Crear nuevo usuario."""
    form = CrearUsuarioForm(usuario_actual=current_user)

    if form.validate_on_submit():
        # Verificar que el rol seleccionado está permitido
        roles_permitidos = current_user.roles_que_puede_crear()
        if form.rol.data not in roles_permitidos:
            flash('No tienes permisos para crear usuarios con ese rol.', 'danger')
            return render_template('admin/crear_usuario.html', form=form)

        # Verificar que no exista
        existente = Usuario.query.filter_by(correo=form.correo.data.lower()).first()
        if existente:
            flash('Ya existe un usuario con ese correo.', 'danger')
            return render_template('admin/crear_usuario.html', form=form)

        usuario = Usuario(
            correo=form.correo.data.lower(),
            nombre=form.nombre.data,
            rol=form.rol.data,
            debe_cambiar_contrasena=True
        )
        usuario.establecer_contrasena(form.contrasena.data)

        db.session.add(usuario)
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'usuario_creado',
            f'Usuario creado: {usuario.correo} (rol: {usuario.rol})',
            request
        )

        flash(f'Usuario {usuario.correo} creado correctamente.', 'success')
        return redirect(url_for('admin.usuarios'))

    return render_template('admin/crear_usuario.html', form=form)


@admin_bp.route('/usuarios/<int:usuario_id>', methods=['GET', 'POST'])
@login_required
@gestor_usuarios_requerido
def editar_usuario(usuario_id):
    """Editar usuario existente."""
    usuario = Usuario.query.get_or_404(usuario_id)

    # Verificar permisos para editar este usuario
    if not current_user.puede_gestionar_usuario(usuario):
        flash('No tienes permisos para editar este usuario.', 'danger')
        return redirect(url_for('admin.usuarios'))

    form = EditarUsuarioForm(usuario_actual=current_user, usuario_editado=usuario, obj=usuario)

    if form.validate_on_submit():
        # Verificar que el rol está permitido
        if not current_user.es_admin() and form.rol.data != Usuario.ROL_COLLABORATOR:
            flash('No tienes permisos para asignar ese rol.', 'danger')
            return render_template('admin/editar_usuario.html', form=form, usuario=usuario)

        usuario.nombre = form.nombre.data
        # Solo admin puede cambiar roles libremente
        if current_user.es_admin():
            usuario.rol = form.rol.data
        usuario.activo = form.activo.data

        if form.nueva_contrasena.data:
            usuario.establecer_contrasena(form.nueva_contrasena.data)
            usuario.debe_cambiar_contrasena = True

        if form.forzar_cambio.data:
            usuario.debe_cambiar_contrasena = True

        # Resetear bloqueo si se edita
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None

        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'usuario_editado',
            f'Usuario editado: {usuario.correo}',
            request
        )

        flash('Usuario actualizado correctamente.', 'success')
        return redirect(url_for('admin.usuarios'))

    return render_template('admin/editar_usuario.html', form=form, usuario=usuario)


@admin_bp.route('/usuarios/<int:usuario_id>/eliminar', methods=['POST'])
@login_required
@gestor_usuarios_requerido
def eliminar_usuario(usuario_id):
    """Eliminar usuario."""
    if usuario_id == current_user.id:
        flash('No puedes eliminar tu propia cuenta.', 'danger')
        return redirect(url_for('admin.usuarios'))

    usuario = Usuario.query.get_or_404(usuario_id)

    # Verificar permisos
    if not current_user.puede_gestionar_usuario(usuario):
        flash('No tienes permisos para eliminar este usuario.', 'danger')
        return redirect(url_for('admin.usuarios'))

    correo = usuario.correo

    db.session.delete(usuario)
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'usuario_eliminado',
        f'Usuario eliminado: {correo}',
        request
    )

    flash(f'Usuario {correo} eliminado correctamente.', 'success')
    return redirect(url_for('admin.usuarios'))


@admin_bp.route('/usuarios/<int:usuario_id>/desbloquear', methods=['POST'])
@login_required
@gestor_usuarios_requerido
def desbloquear_usuario(usuario_id):
    """Desbloquear usuario."""
    usuario = Usuario.query.get_or_404(usuario_id)

    # Verificar permisos
    if not current_user.puede_gestionar_usuario(usuario):
        flash('No tienes permisos para desbloquear este usuario.', 'danger')
        return redirect(url_for('admin.usuarios'))

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'usuario_desbloqueado',
        f'Usuario desbloqueado: {usuario.correo}',
        request
    )

    flash(f'Usuario {usuario.correo} desbloqueado.', 'success')
    return redirect(url_for('admin.usuarios'))


@admin_bp.route('/usuarios/<int:usuario_id>/reset-password', methods=['POST'])
@login_required
@gestor_usuarios_requerido
def reset_password_usuario(usuario_id):
    """Resetea la contraseña del usuario a PASSWORD."""
    usuario = Usuario.query.get_or_404(usuario_id)

    # Verificar permisos
    if not current_user.puede_gestionar_usuario(usuario):
        flash('No tienes permisos para resetear la contraseña de este usuario.', 'danger')
        return redirect(url_for('admin.usuarios'))

    usuario.establecer_contrasena('PASSWORD')
    usuario.debe_cambiar_contrasena = True
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'password_reseteado',
        f'Contraseña reseteada para: {usuario.correo}',
        request
    )

    flash(f'Contraseña de {usuario.correo} reseteada a "PASSWORD".', 'success')
    return redirect(url_for('admin.usuarios'))


@admin_bp.route('/logs')
@login_required
@admin_requerido
def logs():
    """Visor de logs de actividad."""
    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 50

    filtro_accion = request.args.get('accion', '')
    filtro_usuario = request.args.get('usuario', '', type=str)

    query = LogActividad.query

    if filtro_accion:
        query = query.filter(LogActividad.accion.like(f'%{filtro_accion}%'))

    if filtro_usuario:
        query = query.join(Usuario).filter(Usuario.correo.like(f'%{filtro_usuario}%'))

    logs = query.order_by(LogActividad.fecha.desc()).paginate(
        page=pagina, per_page=por_pagina, error_out=False
    )

    # Obtener acciones únicas para filtro
    acciones = db.session.query(LogActividad.accion).distinct().all()
    acciones = [a[0] for a in acciones]

    return render_template('admin/logs.html',
                          logs=logs,
                          acciones=acciones,
                          filtro_accion=filtro_accion,
                          filtro_usuario=filtro_usuario)


@admin_bp.route('/estadisticas')
@login_required
@admin_requerido
def estadisticas():
    """Estadísticas del sistema."""
    # Usuarios por rol
    usuarios_por_rol = db.session.query(
        Usuario.rol, db.func.count(Usuario.id)
    ).group_by(Usuario.rol).all()

    # Escaneos por estado
    escaneos_por_estado = db.session.query(
        Escaneo.estado, db.func.count(Escaneo.id)
    ).group_by(Escaneo.estado).all()

    # Escaneos últimos 30 días
    hace_30_dias = datetime.utcnow() - timedelta(days=30)
    escaneos_recientes = Escaneo.query.filter(
        Escaneo.fecha_inicio >= hace_30_dias
    ).count()

    # PDFs totales descargados
    total_pdfs = db.session.query(
        db.func.sum(Escaneo.pdfs_descargados)
    ).scalar() or 0

    # Cuentas Gmail registradas
    total_cuentas_gmail = CuentaGmail.query.filter_by(activa=True).count()

    return render_template('admin/estadisticas.html',
                          usuarios_por_rol=dict(usuarios_por_rol),
                          escaneos_por_estado=dict(escaneos_por_estado),
                          escaneos_recientes=escaneos_recientes,
                          total_pdfs=total_pdfs,
                          total_cuentas_gmail=total_cuentas_gmail)
