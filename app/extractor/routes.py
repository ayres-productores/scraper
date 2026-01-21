"""
Rutas del módulo extractor de PDFs
"""

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, jsonify, current_app)
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, DateField, SubmitField
from wtforms.validators import DataRequired, Email
from app import db
from app.models import CuentaGmail, Escaneo, LogActividad, HistorialEscaneoCarpeta, CorreoProcesado
from app.extractor.motor import (MotorExtractorWeb, crear_motor, obtener_motor,
                                  eliminar_motor, motores_activos)
from datetime import datetime, timedelta
import os

extractor_bp = Blueprint('extractor', __name__)


class CuentaGmailForm(FlaskForm):
    """Formulario para agregar cuenta de Gmail."""
    correo_gmail = StringField('Correo Gmail', validators=[
        DataRequired(message='El correo es requerido'),
        Email(message='Ingresa un correo válido')
    ])
    contrasena_app = PasswordField('Contraseña de Aplicación', validators=[
        DataRequired(message='La contraseña de aplicación es requerida')
    ])
    submit = SubmitField('Agregar Cuenta')


class ConfigEscaneoForm(FlaskForm):
    """Formulario de configuración de escaneo."""
    palabras_clave = TextAreaField('Palabras clave (una por línea)')
    carpetas = StringField('Carpetas (separadas por coma)', default='INBOX')
    fecha_desde = DateField('Fecha desde', format='%Y-%m-%d')
    fecha_hasta = DateField('Fecha hasta', format='%Y-%m-%d')
    submit = SubmitField('Iniciar Escaneo')


@extractor_bp.route('/')
@login_required
def index():
    """Página principal del extractor."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    form_cuenta = CuentaGmailForm()
    form_escaneo = ConfigEscaneoForm()

    # Valores por defecto del formulario
    if not form_escaneo.fecha_desde.data:
        form_escaneo.fecha_desde.data = datetime.now() - timedelta(days=365)
    if not form_escaneo.fecha_hasta.data:
        form_escaneo.fecha_hasta.data = datetime.now()
    if not form_escaneo.palabras_clave.data:
        form_escaneo.palabras_clave.data = '\n'.join([
            'poliza', 'póliza', 'rio', 'uruguay',
            'mercantil', 'andina', 'berkley'
        ])

    # Obtener cuentas del usuario
    cuentas = current_user.cuentas_gmail.filter_by(activa=True).all()

    # Limpiar escaneos huérfanos (en_progreso sin motor activo)
    escaneos_pendientes = current_user.escaneos.filter_by(estado='en_progreso').all()
    for escaneo in escaneos_pendientes:
        motor = obtener_motor(escaneo.id)
        if not motor:
            # No hay motor activo, marcar como cancelado
            escaneo.estado = 'cancelado'
            escaneo.fecha_fin = datetime.utcnow()
            escaneo.cuenta_actual = None
            db.session.commit()

    # Verificar si hay escaneo activo (después de la limpieza)
    escaneo_activo = current_user.escaneos.filter_by(estado='en_progreso').first()

    # Historial de escaneos
    historial = current_user.escaneos.order_by(
        Escaneo.fecha_inicio.desc()
    ).limit(10).all()

    return render_template('extractor/index.html',
                          form_cuenta=form_cuenta,
                          form_escaneo=form_escaneo,
                          cuentas=cuentas,
                          escaneo_activo=escaneo_activo,
                          historial=historial)


@extractor_bp.route('/cuenta/agregar', methods=['POST'])
@login_required
def agregar_cuenta():
    """Agrega una nueva cuenta de Gmail."""
    form = CuentaGmailForm()

    if form.validate_on_submit():
        # Verificar que no exista ya
        existente = CuentaGmail.query.filter_by(
            usuario_id=current_user.id,
            correo_gmail=form.correo_gmail.data.lower()
        ).first()

        if existente:
            flash('Esta cuenta de Gmail ya está registrada.', 'warning')
            return redirect(url_for('extractor.index'))

        # Probar conexión primero
        motor = MotorExtractorWeb(None, current_app._get_current_object())
        exito, mensaje = motor.probar_conexion(
            form.correo_gmail.data,
            form.contrasena_app.data
        )

        if not exito:
            flash(f'Error de conexión: {mensaje}', 'danger')
            return redirect(url_for('extractor.index'))

        # Crear cuenta
        cuenta = CuentaGmail(
            usuario_id=current_user.id,
            correo_gmail=form.correo_gmail.data.lower()
        )
        cuenta.establecer_contrasena_app(form.contrasena_app.data)

        db.session.add(cuenta)
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'cuenta_gmail_agregada',
            f'Cuenta Gmail agregada: {cuenta.correo_gmail}',
            request
        )

        flash('Cuenta de Gmail agregada correctamente.', 'success')

    return redirect(url_for('extractor.index'))


@extractor_bp.route('/cuenta/eliminar/<int:cuenta_id>', methods=['POST'])
@login_required
def eliminar_cuenta(cuenta_id):
    """Elimina una cuenta de Gmail."""
    cuenta = CuentaGmail.query.filter_by(
        id=cuenta_id,
        usuario_id=current_user.id
    ).first_or_404()

    correo = cuenta.correo_gmail
    db.session.delete(cuenta)
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'cuenta_gmail_eliminada',
        f'Cuenta Gmail eliminada: {correo}',
        request
    )

    flash('Cuenta eliminada correctamente.', 'success')
    return redirect(url_for('extractor.index'))


@extractor_bp.route('/cuenta/probar/<int:cuenta_id>', methods=['POST'])
@login_required
def probar_cuenta(cuenta_id):
    """Prueba la conexión de una cuenta de Gmail."""
    cuenta = CuentaGmail.query.filter_by(
        id=cuenta_id,
        usuario_id=current_user.id
    ).first_or_404()

    motor = MotorExtractorWeb(None, current_app._get_current_object())
    exito, mensaje = motor.probar_conexion(
        cuenta.correo_gmail,
        cuenta.obtener_contrasena_app()
    )

    return jsonify({
        'exito': exito,
        'mensaje': mensaje
    })


@extractor_bp.route('/iniciar', methods=['POST'])
@login_required
def iniciar_escaneo():
    """Inicia un nuevo escaneo (soporta múltiples cuentas)."""
    # Verificar que no haya escaneo activo
    escaneo_activo = current_user.escaneos.filter_by(estado='en_progreso').first()
    if escaneo_activo:
        flash('Ya hay un escaneo en progreso.', 'warning')
        return redirect(url_for('extractor.index'))

    # Obtener cuentas seleccionadas (puede ser una o varias)
    cuenta_ids = request.form.getlist('cuenta_ids')

    if not cuenta_ids:
        flash('Selecciona al menos una cuenta de Gmail.', 'warning')
        return redirect(url_for('extractor.index'))

    # Limitar a 5 cuentas máximo
    if len(cuenta_ids) > 5:
        flash('Máximo 5 cuentas por escaneo.', 'warning')
        return redirect(url_for('extractor.index'))

    # Obtener las cuentas
    cuentas = CuentaGmail.query.filter(
        CuentaGmail.id.in_(cuenta_ids),
        CuentaGmail.usuario_id == current_user.id,
        CuentaGmail.activa == True
    ).all()

    if not cuentas:
        flash('No se encontraron cuentas válidas.', 'warning')
        return redirect(url_for('extractor.index'))

    # Procesar configuración
    palabras_clave_texto = request.form.get('palabras_clave', '')
    palabras_clave = [p.strip() for p in palabras_clave_texto.split('\n') if p.strip()]

    carpetas_texto = request.form.get('carpetas', 'INBOX')
    carpetas = [c.strip() for c in carpetas_texto.split(',') if c.strip()]

    fecha_desde = None
    fecha_hasta = None
    try:
        if request.form.get('fecha_desde'):
            fecha_desde = datetime.strptime(request.form.get('fecha_desde'), '%Y-%m-%d')
        if request.form.get('fecha_hasta'):
            fecha_hasta = datetime.strptime(request.form.get('fecha_hasta'), '%Y-%m-%d')
    except ValueError:
        pass

    # Crear directorio de salida para el usuario
    directorio_usuario = os.path.join(
        current_app.config['UPLOAD_FOLDER'],
        str(current_user.id)
    )
    if not os.path.exists(directorio_usuario):
        os.makedirs(directorio_usuario)

    # Determinar si es multi-cuenta
    es_multi = len(cuentas) > 1

    # Crear registro de escaneo
    escaneo = Escaneo(
        usuario_id=current_user.id,
        cuenta_gmail_id=cuentas[0].id if len(cuentas) == 1 else None,
        estado='en_progreso',
        palabras_clave=','.join(palabras_clave),
        carpetas=','.join(carpetas),
        fecha_desde=fecha_desde.date() if fecha_desde else None,
        fecha_hasta=fecha_hasta.date() if fecha_hasta else None,
        es_multi_cuenta=es_multi,
        cuentas_escaneadas=','.join([str(c.id) for c in cuentas])
    )
    db.session.add(escaneo)
    db.session.commit()

    # Crear y ejecutar motor
    motor = crear_motor(escaneo.id, current_app._get_current_object())

    # Opcion para forzar escaneo completo (ignorar memoria)
    forzar_escaneo = request.form.get('forzar_escaneo') == 'on'

    config = {
        'palabras_clave': palabras_clave,
        'carpetas': carpetas,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'forzar_escaneo': forzar_escaneo
    }

    motor.ejecutar_escaneo_multi(cuentas, config, directorio_usuario)

    # Log
    cuentas_str = ', '.join([c.correo_gmail for c in cuentas])
    LogActividad.registrar(
        current_user.id, 'escaneo_iniciado',
        f'Escaneo iniciado para {len(cuentas)} cuenta(s): {cuentas_str}',
        request
    )

    flash(f'Escaneo iniciado para {len(cuentas)} cuenta(s).', 'success')
    return redirect(url_for('extractor.index'))


@extractor_bp.route('/detener/<int:escaneo_id>', methods=['POST'])
@login_required
def detener_escaneo(escaneo_id):
    """Detiene un escaneo en progreso."""
    escaneo = Escaneo.query.filter_by(
        id=escaneo_id,
        usuario_id=current_user.id,
        estado='en_progreso'
    ).first_or_404()

    # Detener el motor si existe
    motor = obtener_motor(escaneo_id)
    if motor:
        motor.detener()
        # Eliminar motor de la lista de activos
        eliminar_motor(escaneo_id)

    # Actualizar estado inmediatamente en la base de datos
    escaneo.estado = 'cancelado'
    escaneo.fecha_fin = datetime.utcnow()
    escaneo.cuenta_actual = None
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'escaneo_detenido',
        f'Escaneo {escaneo_id} detenido por el usuario',
        request
    )

    flash('Escaneo detenido correctamente.', 'success')
    return redirect(url_for('extractor.index'))


@extractor_bp.route('/pausar/<int:escaneo_id>', methods=['POST'])
@login_required
def pausar_escaneo(escaneo_id):
    """Pausa un escaneo en progreso."""
    escaneo = Escaneo.query.filter_by(
        id=escaneo_id,
        usuario_id=current_user.id,
        estado='en_progreso'
    ).first_or_404()

    motor = obtener_motor(escaneo_id)
    if motor:
        if motor.pausar():
            LogActividad.registrar(
                current_user.id, 'escaneo_pausado',
                f'Escaneo {escaneo_id} pausado por el usuario',
                request
            )
            return jsonify({'exito': True, 'mensaje': 'Escaneo pausado'})

    return jsonify({'exito': False, 'mensaje': 'No se pudo pausar el escaneo'})


@extractor_bp.route('/reanudar/<int:escaneo_id>', methods=['POST'])
@login_required
def reanudar_escaneo(escaneo_id):
    """Reanuda un escaneo pausado."""
    escaneo = Escaneo.query.filter_by(
        id=escaneo_id,
        usuario_id=current_user.id,
        estado='en_progreso'
    ).first_or_404()

    motor = obtener_motor(escaneo_id)
    if motor:
        if motor.reanudar():
            LogActividad.registrar(
                current_user.id, 'escaneo_reanudado',
                f'Escaneo {escaneo_id} reanudado por el usuario',
                request
            )
            return jsonify({'exito': True, 'mensaje': 'Escaneo reanudado'})

    return jsonify({'exito': False, 'mensaje': 'No se pudo reanudar el escaneo'})


@extractor_bp.route('/estado/<int:escaneo_id>')
@login_required
def estado_escaneo(escaneo_id):
    """Obtiene el estado actual de un escaneo (para AJAX)."""
    escaneo = Escaneo.query.filter_by(
        id=escaneo_id,
        usuario_id=current_user.id
    ).first_or_404()

    motor = obtener_motor(escaneo_id)
    logs = motor.logs[-20:] if motor else []

    # Si el escaneo terminó, limpiar el motor
    if escaneo.estado != 'en_progreso' and motor:
        eliminar_motor(escaneo_id)

    # Info adicional para multi-cuenta
    cuenta_actual = escaneo.cuenta_actual
    total_cuentas = len(escaneo.obtener_lista_cuentas()) if escaneo.es_multi_cuenta else 1
    cuenta_index = motor.cuenta_index if motor else 0

    # Estado del motor (pausado, etc.)
    estado_motor = None
    pausado = False
    correo_actual = 0
    total_correos_carpeta = 0

    if motor:
        estado_detallado = motor.obtener_estado_detallado()
        estado_motor = estado_detallado['estado_motor']
        pausado = estado_detallado['pausado']
        correo_actual = estado_detallado['correo_actual']
        total_correos_carpeta = estado_detallado['total_correos_carpeta']

    return jsonify({
        'estado': escaneo.estado,
        'estado_motor': estado_motor,
        'pausado': pausado,
        'correos_escaneados': escaneo.correos_escaneados or 0,
        'pdfs_descargados': escaneo.pdfs_descargados or 0,
        'correo_actual': correo_actual,
        'total_correos_carpeta': total_correos_carpeta,
        'logs': logs,
        'es_multi_cuenta': escaneo.es_multi_cuenta,
        'cuenta_actual': cuenta_actual,
        'total_cuentas': total_cuentas,
        'cuenta_index': cuenta_index,
        'mensaje_error': escaneo.mensaje_error
    })


@extractor_bp.route('/historial')
@login_required
def historial():
    """Muestra el historial completo de escaneos."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    escaneos = current_user.escaneos.order_by(
        Escaneo.fecha_inicio.desc()
    ).all()

    return render_template('extractor/historial.html', escaneos=escaneos)


@extractor_bp.route('/memoria')
@login_required
def memoria_escaneo():
    """Muestra estadísticas de la memoria de escaneo por cuenta."""
    cuentas = current_user.cuentas_gmail.filter_by(activa=True).all()

    estadisticas = []
    for cuenta in cuentas:
        # Obtener historial de carpetas
        historial_carpetas = HistorialEscaneoCarpeta.query.filter_by(
            cuenta_gmail_id=cuenta.id
        ).all()

        # Contar correos procesados
        total_correos = CorreoProcesado.query.filter_by(
            cuenta_gmail_id=cuenta.id
        ).count()

        correos_con_pdf = CorreoProcesado.query.filter_by(
            cuenta_gmail_id=cuenta.id,
            tiene_pdfs=True
        ).count()

        estadisticas.append({
            'cuenta': cuenta,
            'historial_carpetas': historial_carpetas,
            'total_correos_procesados': total_correos,
            'correos_con_pdf': correos_con_pdf
        })

    return render_template('extractor/memoria.html', estadisticas=estadisticas)


@extractor_bp.route('/memoria/limpiar/<int:cuenta_id>', methods=['POST'])
@login_required
def limpiar_memoria(cuenta_id):
    """Limpia la memoria de escaneo de una cuenta específica."""
    cuenta = CuentaGmail.query.filter_by(
        id=cuenta_id,
        usuario_id=current_user.id
    ).first_or_404()

    # Eliminar correos procesados
    CorreoProcesado.query.filter_by(cuenta_gmail_id=cuenta_id).delete()

    # Eliminar historial de carpetas
    HistorialEscaneoCarpeta.query.filter_by(cuenta_gmail_id=cuenta_id).delete()

    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'memoria_limpiada',
        f'Memoria de escaneo limpiada para: {cuenta.correo_gmail}',
        request
    )

    flash(f'Memoria de escaneo limpiada para {cuenta.correo_gmail}. El próximo escaneo revisará todos los correos.', 'success')
    return redirect(url_for('extractor.memoria_escaneo'))


@extractor_bp.route('/memoria/limpiar-todo', methods=['POST'])
@login_required
def limpiar_toda_memoria():
    """Limpia toda la memoria de escaneo del usuario."""
    cuentas = current_user.cuentas_gmail.all()

    for cuenta in cuentas:
        CorreoProcesado.query.filter_by(cuenta_gmail_id=cuenta.id).delete()
        HistorialEscaneoCarpeta.query.filter_by(cuenta_gmail_id=cuenta.id).delete()

    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'memoria_total_limpiada',
        'Toda la memoria de escaneo fue limpiada',
        request
    )

    flash('Toda la memoria de escaneo fue limpiada. Los próximos escaneos revisarán todos los correos.', 'success')
    return redirect(url_for('extractor.memoria_escaneo'))
