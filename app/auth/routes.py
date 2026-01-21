"""
Rutas de autenticación
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import Usuario, LogActividad
from app.auth.forms import (LoginForm, CambiarContrasenaForm,
                             CambiarContrasenaObligatorioForm, PerfilForm)

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Página de inicio de sesión."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = LoginForm()

    if form.validate_on_submit():
        usuario = Usuario.query.filter_by(correo=form.correo.data.lower()).first()

        # Mensaje genérico para no revelar si el usuario existe
        mensaje_error = 'Credenciales inválidas. Verifica tu correo y contraseña.'

        if usuario:
            # Verificar si está bloqueado
            if usuario.esta_bloqueado():
                flash('Cuenta bloqueada temporalmente. Intenta más tarde.', 'danger')
                LogActividad.registrar(
                    usuario.id, 'login_bloqueado',
                    'Intento de login con cuenta bloqueada',
                    request
                )
                return render_template('auth/login.html', form=form)

            # Verificar si está activo
            if not usuario.activo:
                flash(mensaje_error, 'danger')
                return render_template('auth/login.html', form=form)

            # Verificar contraseña
            if usuario.verificar_contrasena(form.contrasena.data):
                usuario.resetear_intentos()
                login_user(usuario, remember=form.recordar.data)

                LogActividad.registrar(
                    usuario.id, 'login_exitoso',
                    f'Inicio de sesión desde {request.remote_addr}',
                    request
                )

                # Verificar si debe cambiar contraseña
                if usuario.debe_cambiar_contrasena:
                    flash('Debes cambiar tu contraseña antes de continuar.', 'warning')
                    return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

                next_page = request.args.get('next')
                if next_page and next_page.startswith('/'):
                    return redirect(next_page)
                return redirect(url_for('main.dashboard'))
            else:
                usuario.registrar_intento_fallido()
                LogActividad.registrar(
                    usuario.id, 'login_fallido',
                    f'Contraseña incorrecta desde {request.remote_addr}',
                    request
                )

        flash(mensaje_error, 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    """Cerrar sesión."""
    LogActividad.registrar(
        current_user.id, 'logout',
        'Cierre de sesión',
        request
    )
    logout_user()
    session.clear()
    flash('Has cerrado sesión correctamente.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/cambiar-contrasena-obligatorio', methods=['GET', 'POST'])
@login_required
def cambiar_contrasena_obligatorio():
    """Cambio obligatorio de contraseña (primer inicio)."""
    if not current_user.debe_cambiar_contrasena:
        return redirect(url_for('main.dashboard'))

    form = CambiarContrasenaObligatorioForm()

    if form.validate_on_submit():
        current_user.establecer_contrasena(form.nueva_contrasena.data)
        current_user.debe_cambiar_contrasena = False
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'cambio_contrasena',
            'Cambio de contraseña obligatorio completado',
            request
        )

        flash('Contraseña actualizada correctamente.', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('auth/cambiar_contrasena_obligatorio.html', form=form)


@auth_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    """Página de perfil del usuario."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    form_perfil = PerfilForm(obj=current_user)
    form_contrasena = CambiarContrasenaForm()

    if 'guardar_perfil' in request.form and form_perfil.validate_on_submit():
        current_user.nombre = form_perfil.nombre.data
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'perfil_actualizado',
            'Datos del perfil actualizados',
            request
        )

        flash('Perfil actualizado correctamente.', 'success')
        return redirect(url_for('auth.perfil'))

    if 'cambiar_contrasena' in request.form and form_contrasena.validate_on_submit():
        if current_user.verificar_contrasena(form_contrasena.contrasena_actual.data):
            current_user.establecer_contrasena(form_contrasena.nueva_contrasena.data)
            db.session.commit()

            LogActividad.registrar(
                current_user.id, 'cambio_contrasena',
                'Cambio de contraseña voluntario',
                request
            )

            flash('Contraseña actualizada correctamente.', 'success')
            return redirect(url_for('auth.perfil'))
        else:
            flash('La contraseña actual es incorrecta.', 'danger')

    return render_template('auth/perfil.html',
                          form_perfil=form_perfil,
                          form_contrasena=form_contrasena)
