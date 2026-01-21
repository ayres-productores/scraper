"""
Formularios de autenticación
"""

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
import re


def validar_contrasena_segura(form, field):
    """Valida que la contraseña cumpla requisitos de seguridad."""
    contrasena = field.data
    errores = []

    if len(contrasena) < 8:
        errores.append('mínimo 8 caracteres')
    if not re.search(r'[A-Z]', contrasena):
        errores.append('una mayúscula')
    if not re.search(r'[a-z]', contrasena):
        errores.append('una minúscula')
    if not re.search(r'\d', contrasena):
        errores.append('un número')
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', contrasena):
        errores.append('un símbolo especial')

    if errores:
        raise ValidationError(f'La contraseña debe contener: {", ".join(errores)}')


class LoginForm(FlaskForm):
    """Formulario de inicio de sesión."""

    correo = StringField('Usuario', validators=[
        DataRequired(message='El usuario es requerido')
    ])
    contrasena = PasswordField('Contraseña', validators=[
        DataRequired(message='La contraseña es requerida')
    ])
    recordar = BooleanField('Recordar sesión')
    submit = SubmitField('Iniciar Sesión')


class CambiarContrasenaForm(FlaskForm):
    """Formulario para cambiar contraseña."""

    contrasena_actual = PasswordField('Contraseña actual', validators=[
        DataRequired(message='Ingresa tu contraseña actual')
    ])
    nueva_contrasena = PasswordField('Nueva contraseña', validators=[
        DataRequired(message='Ingresa la nueva contraseña'),
        validar_contrasena_segura
    ])
    confirmar_contrasena = PasswordField('Confirmar nueva contraseña', validators=[
        DataRequired(message='Confirma la nueva contraseña'),
        EqualTo('nueva_contrasena', message='Las contraseñas no coinciden')
    ])
    submit = SubmitField('Cambiar Contraseña')


class CambiarContrasenaObligatorioForm(FlaskForm):
    """Formulario para cambio obligatorio de contraseña (primer inicio)."""

    nueva_contrasena = PasswordField('Nueva contraseña', validators=[
        DataRequired(message='Ingresa la nueva contraseña'),
        validar_contrasena_segura
    ])
    confirmar_contrasena = PasswordField('Confirmar nueva contraseña', validators=[
        DataRequired(message='Confirma la nueva contraseña'),
        EqualTo('nueva_contrasena', message='Las contraseñas no coinciden')
    ])
    submit = SubmitField('Establecer Contraseña')


class PerfilForm(FlaskForm):
    """Formulario para editar perfil."""

    nombre = StringField('Nombre completo', validators=[
        DataRequired(message='El nombre es requerido'),
        Length(min=2, max=100, message='El nombre debe tener entre 2 y 100 caracteres')
    ])
    submit = SubmitField('Guardar Cambios')
