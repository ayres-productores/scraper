"""
Rutas del módulo de distribución de pólizas
"""

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, jsonify, current_app)
from flask_login import login_required, current_user
from app import db
from app.models import (Cliente, PolizaCliente, EnvioWhatsApp, PlantillaMensaje,
                        ArchivoDescargado, Escaneo, Compania, LogActividad,
                        Pago, Interaccion, AlertaVencimiento, Siniestro)
from app.distribucion.forms import (ClienteForm, AsignarPolizaForm, PlantillaMensajeForm,
                                     EnvioForm, FiltroClientesForm, PolizaCompletaForm,
                                     InteraccionForm, PagoForm, GenerarCuotasForm,
                                     SiniestroForm, FiltroAlertasForm)
from app.distribucion.whatsapp_sender import WhatsAppSender
from datetime import datetime, timedelta

distribucion_bp = Blueprint('distribucion', __name__)


@distribucion_bp.route('/')
@login_required
def index():
    """Panel principal de distribución."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    # Estadísticas
    total_clientes = current_user.clientes.filter_by(activo=True).count()
    total_polizas = PolizaCliente.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id
    ).count()
    envios_pendientes = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        EnvioWhatsApp.estado == 'pendiente'
    ).count()

    # Enviados hoy
    hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    envios_enviados = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        EnvioWhatsApp.estado == 'enviado',
        EnvioWhatsApp.fecha_envio >= hoy
    ).count()

    # Últimos envíos
    ultimos_envios = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id
    ).order_by(EnvioWhatsApp.id.desc()).limit(10).all()

    return render_template('distribucion/index.html',
                          total_clientes=total_clientes,
                          total_polizas=total_polizas,
                          envios_pendientes=envios_pendientes,
                          envios_enviados=envios_enviados,
                          ultimos_envios=ultimos_envios)


# ============================================================================
# GESTIÓN DE CLIENTES
# ============================================================================

@distribucion_bp.route('/clientes')
@login_required
def clientes():
    """Listado de clientes."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    busqueda = request.args.get('busqueda', '')
    solo_activos = request.args.get('solo_activos', '1') == '1'

    query = current_user.clientes

    if solo_activos:
        query = query.filter_by(activo=True)

    if busqueda:
        query = query.filter(
            db.or_(
                Cliente.nombre.ilike(f'%{busqueda}%'),
                Cliente.apellido.ilike(f'%{busqueda}%'),
                Cliente.telefono_whatsapp.ilike(f'%{busqueda}%'),
                Cliente.documento_identidad.ilike(f'%{busqueda}%')
            )
        )

    clientes = query.order_by(Cliente.nombre).all()

    return render_template('distribucion/clientes.html',
                          clientes=clientes,
                          busqueda=busqueda,
                          solo_activos=solo_activos)


@distribucion_bp.route('/clientes/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_cliente():
    """Crear nuevo cliente."""
    form = ClienteForm()

    if form.validate_on_submit():
        cliente = Cliente(
            usuario_id=current_user.id,
            nombre=form.nombre.data,
            apellido=form.apellido.data,
            telefono_whatsapp=form.telefono_whatsapp.data,
            email=form.email.data,
            documento_identidad=form.documento_identidad.data,
            notas=form.notas.data,
            usar_mensaje_estandar=form.usar_mensaje_estandar.data,
            mensaje_personalizado=form.mensaje_personalizado.data if not form.usar_mensaje_estandar.data else None
        )
        db.session.add(cliente)
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'cliente_creado',
            f'Cliente creado: {cliente.nombre_completo}',
            request
        )

        flash('Cliente creado correctamente.', 'success')
        return redirect(url_for('distribucion.cliente_detalle', cliente_id=cliente.id))

    return render_template('distribucion/cliente_form.html', form=form, titulo='Nuevo Cliente')


@distribucion_bp.route('/clientes/<int:cliente_id>')
@login_required
def cliente_detalle(cliente_id):
    """Detalle de un cliente."""
    cliente = Cliente.query.filter_by(
        id=cliente_id,
        usuario_id=current_user.id
    ).first_or_404()

    # Pólizas del cliente
    polizas = cliente.polizas.order_by(PolizaCliente.fecha_asignacion.desc()).all()

    # Historial de envíos
    envios = cliente.envios.order_by(EnvioWhatsApp.id.desc()).limit(20).all()

    return render_template('distribucion/cliente_detalle.html',
                          cliente=cliente,
                          polizas=polizas,
                          envios=envios)


@distribucion_bp.route('/clientes/<int:cliente_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_cliente(cliente_id):
    """Editar cliente."""
    cliente = Cliente.query.filter_by(
        id=cliente_id,
        usuario_id=current_user.id
    ).first_or_404()

    form = ClienteForm(obj=cliente)

    if form.validate_on_submit():
        cliente.nombre = form.nombre.data
        cliente.apellido = form.apellido.data
        cliente.telefono_whatsapp = form.telefono_whatsapp.data
        cliente.email = form.email.data
        cliente.documento_identidad = form.documento_identidad.data
        cliente.notas = form.notas.data
        cliente.usar_mensaje_estandar = form.usar_mensaje_estandar.data
        cliente.mensaje_personalizado = form.mensaje_personalizado.data if not form.usar_mensaje_estandar.data else None

        db.session.commit()

        flash('Cliente actualizado correctamente.', 'success')
        return redirect(url_for('distribucion.cliente_detalle', cliente_id=cliente.id))

    return render_template('distribucion/cliente_form.html',
                          form=form,
                          titulo='Editar Cliente',
                          cliente=cliente)


@distribucion_bp.route('/clientes/<int:cliente_id>/eliminar', methods=['POST'])
@login_required
def eliminar_cliente(cliente_id):
    """Eliminar (desactivar) cliente."""
    cliente = Cliente.query.filter_by(
        id=cliente_id,
        usuario_id=current_user.id
    ).first_or_404()

    cliente.activo = False
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'cliente_eliminado',
        f'Cliente desactivado: {cliente.nombre_completo}',
        request
    )

    flash('Cliente eliminado correctamente.', 'success')
    return redirect(url_for('distribucion.clientes'))


# ============================================================================
# ASIGNACIÓN DE PÓLIZAS
# ============================================================================

@distribucion_bp.route('/asignar', methods=['GET', 'POST'])
@login_required
def asignar_poliza():
    """Asignar póliza a cliente."""
    form = AsignarPolizaForm()

    # Cargar opciones de clientes
    clientes = current_user.clientes.filter_by(activo=True).order_by(Cliente.nombre).all()
    form.cliente_id.choices = [(0, 'Seleccionar cliente...')] + [
        (c.id, c.nombre_completo) for c in clientes
    ]

    # Cargar opciones de archivos
    archivos = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    ).order_by(ArchivoDescargado.fecha_descarga.desc()).all()
    form.archivo_id.choices = [(0, 'Seleccionar archivo...')] + [
        (a.id, f"{a.nombre_archivo[:50]} ({a.fecha_correo.strftime('%d/%m/%Y') if a.fecha_correo else 'Sin fecha'})")
        for a in archivos
    ]

    if form.validate_on_submit():
        # Obtener archivo para detectar compañía
        archivo = ArchivoDescargado.query.get(form.archivo_id.data)

        poliza = PolizaCliente(
            cliente_id=form.cliente_id.data,
            archivo_id=form.archivo_id.data,
            compania_id=archivo.compania_id if archivo else None,
            numero_poliza=form.numero_poliza.data,
            tipo_seguro=form.tipo_seguro.data,
            fecha_vigencia_desde=form.fecha_vigencia_desde.data,
            fecha_vigencia_hasta=form.fecha_vigencia_hasta.data,
            prima_anual=form.prima_anual.data,
            notas=form.notas.data
        )
        db.session.add(poliza)
        db.session.commit()

        cliente = Cliente.query.get(form.cliente_id.data)
        LogActividad.registrar(
            current_user.id, 'poliza_asignada',
            f'Póliza asignada a {cliente.nombre_completo}',
            request
        )

        # Enviar inmediatamente si se solicitó
        if form.enviar_inmediatamente.data:
            return redirect(url_for('distribucion.enviar_poliza', poliza_id=poliza.id))

        flash('Póliza asignada correctamente.', 'success')
        return redirect(url_for('distribucion.cliente_detalle', cliente_id=form.cliente_id.data))

    # Pre-seleccionar cliente si viene en URL
    cliente_id = request.args.get('cliente_id', type=int)
    if cliente_id:
        form.cliente_id.data = cliente_id

    return render_template('distribucion/asignar_poliza.html', form=form)


@distribucion_bp.route('/poliza/<int:poliza_id>/eliminar', methods=['POST'])
@login_required
def eliminar_poliza(poliza_id):
    """Eliminar asignación de póliza."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    cliente_id = poliza.cliente_id
    db.session.delete(poliza)
    db.session.commit()

    flash('Póliza eliminada correctamente.', 'success')
    return redirect(url_for('distribucion.cliente_detalle', cliente_id=cliente_id))


# ============================================================================
# ENVÍO POR WHATSAPP
# ============================================================================

@distribucion_bp.route('/enviar/<int:poliza_id>', methods=['GET', 'POST'])
@login_required
def enviar_poliza(poliza_id):
    """Enviar póliza por WhatsApp (se encola para envío en background)."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    cliente = poliza.cliente
    form = EnvioForm()

    # Obtener mensaje
    if cliente.usar_mensaje_estandar:
        plantilla = PlantillaMensaje.obtener_predeterminada(current_user.id)
        if plantilla:
            mensaje_default = plantilla.renderizar(cliente, poliza)
        else:
            mensaje_default = f"Estimado/a {cliente.nombre},\n\nLe adjunto su póliza.\n\nSaludos cordiales."
    else:
        mensaje_default = cliente.mensaje_personalizado or ''
        # Renderizar variables si las hay
        plantilla_temp = PlantillaMensaje(mensaje=mensaje_default)
        mensaje_default = plantilla_temp.renderizar(cliente, poliza)

    if not form.mensaje.data:
        form.mensaje.data = mensaje_default

    if form.validate_on_submit():
        # Crear registro de envío (se procesará en background)
        envio = EnvioWhatsApp(
            cliente_id=cliente.id,
            poliza_cliente_id=poliza.id,
            archivo_id=poliza.archivo_id,
            mensaje_enviado=form.mensaje.data,
            estado='pendiente'
        )
        db.session.add(envio)
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'envio_whatsapp_encolado',
            f'Póliza encolada para envío a {cliente.nombre_completo}',
            request
        )

        # Verificar modo de envío
        sender = WhatsAppSender(current_app.config)
        if sender.modo == 'api' and sender.api_key:
            flash(f'Mensaje encolado para envío automático a {cliente.nombre_completo}. Se procesará en segundo plano.', 'success')
            return redirect(url_for('distribucion.cliente_detalle', cliente_id=cliente.id))
        else:
            # Modo manual: generar enlace
            enlace = sender.generar_enlace_manual(
                cliente.telefono_formateado,
                form.mensaje.data
            )
            flash('Mensaje encolado. Usa el enlace para enviar manualmente por WhatsApp.', 'info')
            return render_template('distribucion/enviar_resultado.html',
                                  enlace=enlace,
                                  cliente=cliente,
                                  poliza=poliza,
                                  envio=envio)

    return render_template('distribucion/enviar_poliza.html',
                          form=form,
                          cliente=cliente,
                          poliza=poliza)


@distribucion_bp.route('/enviar-directo/<int:cliente_id>')
@login_required
def enviar_directo(cliente_id):
    """Enviar mensaje directo a cliente sin póliza específica."""
    cliente = Cliente.query.filter_by(
        id=cliente_id,
        usuario_id=current_user.id
    ).first_or_404()

    # Obtener mensaje
    if cliente.usar_mensaje_estandar:
        plantilla = PlantillaMensaje.obtener_predeterminada(current_user.id)
        mensaje = plantilla.renderizar(cliente) if plantilla else f"Hola {cliente.nombre}"
    else:
        mensaje = cliente.mensaje_personalizado or f"Hola {cliente.nombre}"

    sender = WhatsAppSender(current_app.config)
    enlace = sender.generar_enlace_manual(cliente.telefono_formateado, mensaje)

    return redirect(enlace)


# ============================================================================
# PLANTILLAS DE MENSAJES
# ============================================================================

@distribucion_bp.route('/plantillas')
@login_required
def plantillas():
    """Listado de plantillas de mensaje."""
    plantillas = PlantillaMensaje.query.filter_by(
        usuario_id=current_user.id
    ).order_by(PlantillaMensaje.es_predeterminada.desc(), PlantillaMensaje.nombre_plantilla).all()

    return render_template('distribucion/plantillas.html',
                          plantillas=plantillas,
                          variables=PlantillaMensaje.VARIABLES_DISPONIBLES)


@distribucion_bp.route('/plantillas/nueva', methods=['GET', 'POST'])
@login_required
def nueva_plantilla():
    """Crear nueva plantilla de mensaje."""
    form = PlantillaMensajeForm()

    if form.validate_on_submit():
        # Si es predeterminada, quitar la marca de las otras
        if form.es_predeterminada.data:
            PlantillaMensaje.query.filter_by(
                usuario_id=current_user.id,
                es_predeterminada=True
            ).update({'es_predeterminada': False})

        plantilla = PlantillaMensaje(
            usuario_id=current_user.id,
            nombre_plantilla=form.nombre_plantilla.data,
            mensaje=form.mensaje.data,
            es_predeterminada=form.es_predeterminada.data
        )
        db.session.add(plantilla)
        db.session.commit()

        flash('Plantilla creada correctamente.', 'success')
        return redirect(url_for('distribucion.plantillas'))

    return render_template('distribucion/plantilla_form.html',
                          form=form,
                          titulo='Nueva Plantilla',
                          variables=PlantillaMensaje.VARIABLES_DISPONIBLES)


@distribucion_bp.route('/plantillas/<int:plantilla_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_plantilla(plantilla_id):
    """Editar plantilla de mensaje."""
    plantilla = PlantillaMensaje.query.filter_by(
        id=plantilla_id,
        usuario_id=current_user.id
    ).first_or_404()

    form = PlantillaMensajeForm(obj=plantilla)

    if form.validate_on_submit():
        # Si es predeterminada, quitar la marca de las otras
        if form.es_predeterminada.data:
            PlantillaMensaje.query.filter_by(
                usuario_id=current_user.id,
                es_predeterminada=True
            ).update({'es_predeterminada': False})

        plantilla.nombre_plantilla = form.nombre_plantilla.data
        plantilla.mensaje = form.mensaje.data
        plantilla.es_predeterminada = form.es_predeterminada.data

        db.session.commit()

        flash('Plantilla actualizada correctamente.', 'success')
        return redirect(url_for('distribucion.plantillas'))

    return render_template('distribucion/plantilla_form.html',
                          form=form,
                          titulo='Editar Plantilla',
                          plantilla=plantilla,
                          variables=PlantillaMensaje.VARIABLES_DISPONIBLES)


@distribucion_bp.route('/plantillas/<int:plantilla_id>/eliminar', methods=['POST'])
@login_required
def eliminar_plantilla(plantilla_id):
    """Eliminar plantilla de mensaje."""
    plantilla = PlantillaMensaje.query.filter_by(
        id=plantilla_id,
        usuario_id=current_user.id
    ).first_or_404()

    db.session.delete(plantilla)
    db.session.commit()

    flash('Plantilla eliminada correctamente.', 'success')
    return redirect(url_for('distribucion.plantillas'))


# ============================================================================
# HISTORIAL DE ENVÍOS
# ============================================================================

@distribucion_bp.route('/envios')
@login_required
def historial_envios():
    """Historial de envíos de WhatsApp."""
    estado = request.args.get('estado', '')

    query = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id
    )

    if estado:
        query = query.filter(EnvioWhatsApp.estado == estado)

    envios = query.order_by(EnvioWhatsApp.id.desc()).limit(100).all()

    return render_template('distribucion/envios.html',
                          envios=envios,
                          estado_filtro=estado)


# ============================================================================
# API ENDPOINTS
# ============================================================================

@distribucion_bp.route('/api/clientes/buscar')
@login_required
def api_buscar_clientes():
    """API para buscar clientes (autocompletado)."""
    q = request.args.get('q', '')

    if len(q) < 2:
        return jsonify([])

    clientes = current_user.clientes.filter(
        Cliente.activo == True,
        db.or_(
            Cliente.nombre.ilike(f'%{q}%'),
            Cliente.apellido.ilike(f'%{q}%'),
            Cliente.telefono_whatsapp.ilike(f'%{q}%')
        )
    ).limit(10).all()

    return jsonify([{
        'id': c.id,
        'nombre': c.nombre_completo,
        'telefono': c.telefono_whatsapp
    } for c in clientes])


@distribucion_bp.route('/api/archivos/por-compania/<int:compania_id>')
@login_required
def api_archivos_por_compania(compania_id):
    """API para obtener archivos filtrados por compañía."""
    archivos = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id,
        ArchivoDescargado.compania_id == compania_id
    ).order_by(ArchivoDescargado.fecha_descarga.desc()).all()

    return jsonify([{
        'id': a.id,
        'nombre': a.nombre_archivo,
        'fecha': a.fecha_correo.strftime('%d/%m/%Y') if a.fecha_correo else None
    } for a in archivos])


@distribucion_bp.route('/api/estado-cola')
@login_required
def estado_cola():
    """API para obtener el estado de la cola de envíos (para actualización en tiempo real)."""
    pendientes = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        EnvioWhatsApp.estado == 'pendiente'
    ).count()

    # Enviados hoy
    hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    enviados_hoy = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        EnvioWhatsApp.estado == 'enviado',
        EnvioWhatsApp.fecha_envio >= hoy
    ).count()

    # Errores recientes (último día)
    ayer = datetime.utcnow() - timedelta(days=1)
    errores = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        EnvioWhatsApp.estado == 'error',
        EnvioWhatsApp.id >= db.session.query(db.func.max(EnvioWhatsApp.id)).scalar() - 100  # últimos 100 registros aprox
    ).count()

    # Último envío procesado
    ultimo_envio = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        EnvioWhatsApp.estado == 'enviado'
    ).order_by(EnvioWhatsApp.fecha_envio.desc()).first()

    return jsonify({
        'pendientes': pendientes,
        'enviados_hoy': enviados_hoy,
        'errores': errores,
        'ultimo_envio': ultimo_envio.fecha_envio.strftime('%H:%M') if ultimo_envio and ultimo_envio.fecha_envio else None,
        'procesando': pendientes > 0
    })


# ============================================================================
# CRM - DASHBOARD
# ============================================================================

@distribucion_bp.route('/crm')
@login_required
def crm_dashboard():
    """Panel principal CRM con alertas y resumen."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    from datetime import date

    # Estadísticas generales
    total_clientes = current_user.clientes.filter_by(activo=True).count()
    total_polizas = PolizaCliente.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        PolizaCliente.estado == 'activa'
    ).count()

    # Pólizas por vencer (próximos 30 días)
    fecha_limite = date.today() + timedelta(days=30)
    polizas_por_vencer = PolizaCliente.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        PolizaCliente.estado == 'activa',
        PolizaCliente.fecha_vigencia_hasta.isnot(None),
        PolizaCliente.fecha_vigencia_hasta <= fecha_limite,
        PolizaCliente.fecha_vigencia_hasta >= date.today()
    ).order_by(PolizaCliente.fecha_vigencia_hasta).all()

    # Pagos pendientes
    pagos_pendientes = Pago.query.join(PolizaCliente).join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        Pago.estado.in_(['pendiente', 'vencido'])
    ).order_by(Pago.fecha_vencimiento).limit(10).all()

    # Alertas pendientes
    alertas_pendientes = AlertaVencimiento.query.filter(
        AlertaVencimiento.usuario_id == current_user.id,
        AlertaVencimiento.estado == 'pendiente',
        AlertaVencimiento.fecha_alerta <= date.today() + timedelta(days=7)
    ).order_by(AlertaVencimiento.fecha_alerta).limit(10).all()

    # Seguimientos pendientes
    seguimientos = Interaccion.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        Interaccion.requiere_seguimiento == True,
        Interaccion.seguimiento_completado == False
    ).order_by(Interaccion.fecha_seguimiento).limit(10).all()

    # Siniestros activos
    siniestros_activos = Siniestro.query.join(PolizaCliente).join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        Siniestro.estado.in_(['denunciado', 'en_proceso', 'documentacion', 'peritaje'])
    ).count()

    return render_template('distribucion/crm_dashboard.html',
                          total_clientes=total_clientes,
                          total_polizas=total_polizas,
                          polizas_por_vencer=polizas_por_vencer,
                          pagos_pendientes=pagos_pendientes,
                          alertas_pendientes=alertas_pendientes,
                          seguimientos=seguimientos,
                          siniestros_activos=siniestros_activos)


# ============================================================================
# CRM - PÓLIZAS COMPLETAS
# ============================================================================

@distribucion_bp.route('/poliza/<int:poliza_id>/completa', methods=['GET', 'POST'])
@login_required
def poliza_completa(poliza_id):
    """Ver/editar póliza con todos los datos."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    form = PolizaCompletaForm(obj=poliza)

    # Cargar opciones
    clientes = current_user.clientes.filter_by(activo=True).order_by(Cliente.nombre).all()
    form.cliente_id.choices = [(c.id, c.nombre_completo) for c in clientes]

    archivos = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    ).order_by(ArchivoDescargado.fecha_descarga.desc()).all()
    form.archivo_id.choices = [(0, 'Sin archivo')] + [
        (a.id, f"{a.nombre_archivo[:40]}...") for a in archivos
    ]

    companias = Compania.query.order_by(Compania.nombre).all()
    form.compania_id.choices = [(0, 'Seleccionar...')] + [(c.id, c.nombre) for c in companias]

    # Cargar polizas del cliente para selector
    form.poliza_cliente_id = poliza.id

    if form.validate_on_submit():
        # Actualizar campos básicos
        poliza.cliente_id = form.cliente_id.data
        poliza.archivo_id = form.archivo_id.data if form.archivo_id.data else None
        poliza.compania_id = form.compania_id.data if form.compania_id.data else None
        poliza.numero_poliza = form.numero_poliza.data
        poliza.tipo_seguro = form.tipo_seguro.data
        poliza.fecha_vigencia_desde = form.fecha_vigencia_desde.data
        poliza.fecha_vigencia_hasta = form.fecha_vigencia_hasta.data
        poliza.prima_anual = form.prima_anual.data

        # Datos del asegurado
        poliza.asegurado_nombre = form.asegurado_nombre.data
        poliza.asegurado_documento = form.asegurado_documento.data
        poliza.asegurado_direccion = form.asegurado_direccion.data
        poliza.asegurado_telefono = form.asegurado_telefono.data
        poliza.asegurado_email = form.asegurado_email.data

        # Bien asegurado
        poliza.bien_asegurado_tipo = form.bien_asegurado_tipo.data
        poliza.bien_asegurado_descripcion = form.bien_asegurado_descripcion.data
        poliza.bien_asegurado_valor = form.bien_asegurado_valor.data

        # Vehículo
        poliza.vehiculo_marca = form.vehiculo_marca.data
        poliza.vehiculo_modelo = form.vehiculo_modelo.data
        poliza.vehiculo_anio = form.vehiculo_anio.data
        poliza.vehiculo_patente = form.vehiculo_patente.data
        poliza.vehiculo_chasis = form.vehiculo_chasis.data
        poliza.vehiculo_motor = form.vehiculo_motor.data
        poliza.vehiculo_color = form.vehiculo_color.data
        poliza.vehiculo_uso = form.vehiculo_uso.data

        # Inmueble
        poliza.inmueble_direccion = form.inmueble_direccion.data
        poliza.inmueble_tipo = form.inmueble_tipo.data
        poliza.inmueble_superficie = form.inmueble_superficie.data
        poliza.inmueble_construccion = form.inmueble_construccion.data

        # Coberturas
        poliza.suma_asegurada = form.suma_asegurada.data
        poliza.deducible = form.deducible.data
        poliza.franquicia = form.franquicia.data
        if form.coberturas_texto.data:
            coberturas_lista = [c.strip() for c in form.coberturas_texto.data.split('\n') if c.strip()]
            poliza.establecer_coberturas(coberturas_lista)

        # Beneficiarios
        if form.beneficiarios_texto.data:
            import json
            beneficiarios_lista = []
            for linea in form.beneficiarios_texto.data.split('\n'):
                if '-' in linea:
                    partes = linea.split('-')
                    beneficiarios_lista.append({
                        'nombre': partes[0].strip(),
                        'porcentaje': partes[1].strip() if len(partes) > 1 else ''
                    })
            poliza.beneficiarios = json.dumps(beneficiarios_lista)

        # Estado
        poliza.estado = form.estado.data
        poliza.renovacion_automatica = form.renovacion_automatica.data

        # Forma de pago
        poliza.forma_pago = form.forma_pago.data
        poliza.cantidad_cuotas = form.cantidad_cuotas.data
        poliza.dia_vencimiento_cuota = form.dia_vencimiento_cuota.data
        poliza.medio_pago = form.medio_pago.data

        # Productor
        poliza.productor_nombre = form.productor_nombre.data
        poliza.productor_telefono = form.productor_telefono.data
        poliza.productor_email = form.productor_email.data
        poliza.sucursal = form.sucursal.data

        poliza.notas = form.notas.data
        poliza.modificado_por_id = current_user.id

        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'poliza_actualizada',
            f'Póliza {poliza.numero_poliza or poliza.id} actualizada',
            request
        )

        flash('Póliza actualizada correctamente.', 'success')
        return redirect(url_for('distribucion.poliza_completa', poliza_id=poliza.id))

    # Pre-cargar datos en el formulario
    if poliza.coberturas:
        form.coberturas_texto.data = '\n'.join(poliza.obtener_coberturas_lista())
    if poliza.beneficiarios:
        beneficiarios = poliza.obtener_beneficiarios_lista()
        form.beneficiarios_texto.data = '\n'.join([f"{b.get('nombre', '')} - {b.get('porcentaje', '')}" for b in beneficiarios])

    # Obtener pagos y siniestros de esta póliza
    pagos = poliza.pagos.order_by(Pago.fecha_vencimiento).all()
    siniestros = poliza.siniestros.order_by(Siniestro.fecha_ocurrencia.desc()).all()
    interacciones = poliza.interacciones.order_by(Interaccion.fecha.desc()).limit(10).all()

    return render_template('distribucion/poliza_completa.html',
                          form=form,
                          poliza=poliza,
                          pagos=pagos,
                          siniestros=siniestros,
                          interacciones=interacciones)


# ============================================================================
# CRM - PAGOS
# ============================================================================

@distribucion_bp.route('/poliza/<int:poliza_id>/pagos')
@login_required
def pagos_poliza(poliza_id):
    """Lista de pagos de una póliza."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    pagos = poliza.pagos.order_by(Pago.numero_cuota, Pago.fecha_vencimiento).all()

    # Actualizar estados automáticamente
    for pago in pagos:
        pago.actualizar_estado_automatico()
    db.session.commit()

    return render_template('distribucion/pagos.html',
                          poliza=poliza,
                          pagos=pagos)


@distribucion_bp.route('/poliza/<int:poliza_id>/pagos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_pago(poliza_id):
    """Registrar nuevo pago."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    form = PagoForm()

    if form.validate_on_submit():
        pago = Pago(
            poliza_cliente_id=poliza.id,
            numero_cuota=form.numero_cuota.data,
            monto=form.monto.data,
            fecha_vencimiento=form.fecha_vencimiento.data,
            fecha_pago=form.fecha_pago.data,
            estado=form.estado.data,
            metodo_pago=form.metodo_pago.data,
            comprobante=form.comprobante.data,
            notas=form.notas.data
        )
        db.session.add(pago)
        db.session.commit()

        flash('Pago registrado correctamente.', 'success')
        return redirect(url_for('distribucion.pagos_poliza', poliza_id=poliza.id))

    return render_template('distribucion/pago_form.html',
                          form=form,
                          poliza=poliza,
                          titulo='Nuevo Pago')


@distribucion_bp.route('/pago/<int:pago_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_pago(pago_id):
    """Editar pago existente."""
    pago = Pago.query.join(PolizaCliente).join(Cliente).filter(
        Pago.id == pago_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    form = PagoForm(obj=pago)

    if form.validate_on_submit():
        pago.numero_cuota = form.numero_cuota.data
        pago.monto = form.monto.data
        pago.fecha_vencimiento = form.fecha_vencimiento.data
        pago.fecha_pago = form.fecha_pago.data
        pago.estado = form.estado.data
        pago.metodo_pago = form.metodo_pago.data
        pago.comprobante = form.comprobante.data
        pago.notas = form.notas.data

        db.session.commit()

        flash('Pago actualizado correctamente.', 'success')
        return redirect(url_for('distribucion.pagos_poliza', poliza_id=pago.poliza_cliente_id))

    return render_template('distribucion/pago_form.html',
                          form=form,
                          poliza=pago.poliza,
                          pago=pago,
                          titulo='Editar Pago')


@distribucion_bp.route('/pago/<int:pago_id>/marcar-pagado', methods=['POST'])
@login_required
def marcar_pago_pagado(pago_id):
    """Marcar pago como pagado rápidamente."""
    pago = Pago.query.join(PolizaCliente).join(Cliente).filter(
        Pago.id == pago_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    from datetime import date
    pago.marcar_pagado(fecha=date.today())
    db.session.commit()

    flash('Pago marcado como pagado.', 'success')
    return redirect(request.referrer or url_for('distribucion.pagos_poliza', poliza_id=pago.poliza_cliente_id))


@distribucion_bp.route('/poliza/<int:poliza_id>/pagos/generar', methods=['GET', 'POST'])
@login_required
def generar_cuotas(poliza_id):
    """Generar cuotas automáticamente."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    form = GenerarCuotasForm()

    # Pre-llenar con datos de la póliza
    if not form.is_submitted():
        if poliza.cantidad_cuotas:
            form.cantidad_cuotas.data = poliza.cantidad_cuotas
        if poliza.prima_anual and poliza.cantidad_cuotas:
            form.monto_cuota.data = poliza.prima_anual / poliza.cantidad_cuotas
        if poliza.fecha_vigencia_desde:
            form.fecha_primera_cuota.data = poliza.fecha_vigencia_desde

    if form.validate_on_submit():
        from dateutil.relativedelta import relativedelta

        cantidad = form.cantidad_cuotas.data
        monto = form.monto_cuota.data
        fecha = form.fecha_primera_cuota.data
        periodicidad = form.periodicidad.data

        # Calcular delta según periodicidad
        deltas = {
            'mensual': relativedelta(months=1),
            'bimestral': relativedelta(months=2),
            'trimestral': relativedelta(months=3),
            'semestral': relativedelta(months=6),
            'anual': relativedelta(years=1)
        }
        delta = deltas.get(periodicidad, relativedelta(months=1))

        # Crear cuotas
        for i in range(cantidad):
            pago = Pago(
                poliza_cliente_id=poliza.id,
                numero_cuota=i + 1,
                monto=monto,
                fecha_vencimiento=fecha,
                estado='pendiente'
            )
            db.session.add(pago)
            fecha = fecha + delta

        db.session.commit()

        flash(f'{cantidad} cuotas generadas correctamente.', 'success')
        return redirect(url_for('distribucion.pagos_poliza', poliza_id=poliza.id))

    return render_template('distribucion/generar_cuotas.html',
                          form=form,
                          poliza=poliza)


@distribucion_bp.route('/pagos/pendientes')
@login_required
def pagos_pendientes_todos():
    """Lista de todos los pagos pendientes/vencidos."""
    estado = request.args.get('estado', '')

    query = Pago.query.join(PolizaCliente).join(Cliente).filter(
        Cliente.usuario_id == current_user.id
    )

    if estado:
        query = query.filter(Pago.estado == estado)
    else:
        query = query.filter(Pago.estado.in_(['pendiente', 'vencido']))

    pagos = query.order_by(Pago.fecha_vencimiento).all()

    # Actualizar estados
    for pago in pagos:
        pago.actualizar_estado_automatico()
    db.session.commit()

    return render_template('distribucion/pagos_pendientes.html',
                          pagos=pagos,
                          estado_filtro=estado)


# ============================================================================
# CRM - INTERACCIONES
# ============================================================================

@distribucion_bp.route('/clientes/<int:cliente_id>/interacciones')
@login_required
def interacciones_cliente(cliente_id):
    """Historial de interacciones con un cliente."""
    cliente = Cliente.query.filter_by(
        id=cliente_id,
        usuario_id=current_user.id
    ).first_or_404()

    interacciones = cliente.interacciones.order_by(Interaccion.fecha.desc()).all()

    return render_template('distribucion/interacciones.html',
                          cliente=cliente,
                          interacciones=interacciones)


@distribucion_bp.route('/clientes/<int:cliente_id>/interacciones/nueva', methods=['GET', 'POST'])
@login_required
def nueva_interaccion(cliente_id):
    """Registrar nueva interacción con cliente."""
    cliente = Cliente.query.filter_by(
        id=cliente_id,
        usuario_id=current_user.id
    ).first_or_404()

    form = InteraccionForm()

    # Cargar pólizas del cliente
    polizas = cliente.polizas.all()
    form.poliza_cliente_id.choices = [(0, 'General (sin póliza específica)')] + [
        (p.id, f"{p.numero_poliza or 'Sin número'} - {p.tipo_seguro or 'Sin tipo'}") for p in polizas
    ]

    if form.validate_on_submit():
        interaccion = Interaccion(
            cliente_id=cliente.id,
            poliza_cliente_id=form.poliza_cliente_id.data if form.poliza_cliente_id.data else None,
            usuario_id=current_user.id,
            tipo=form.tipo.data,
            direccion=form.direccion.data,
            asunto=form.asunto.data,
            descripcion=form.descripcion.data,
            duracion_minutos=form.duracion_minutos.data,
            requiere_seguimiento=form.requiere_seguimiento.data,
            fecha_seguimiento=form.fecha_seguimiento.data if form.requiere_seguimiento.data else None
        )
        db.session.add(interaccion)
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'interaccion_registrada',
            f'Interacción ({form.tipo.data}) con {cliente.nombre_completo}',
            request
        )

        flash('Interacción registrada correctamente.', 'success')
        return redirect(url_for('distribucion.interacciones_cliente', cliente_id=cliente.id))

    return render_template('distribucion/interaccion_form.html',
                          form=form,
                          cliente=cliente,
                          titulo='Nueva Interacción')


@distribucion_bp.route('/interaccion/<int:interaccion_id>/seguimiento', methods=['POST'])
@login_required
def completar_seguimiento(interaccion_id):
    """Marcar seguimiento como completado."""
    interaccion = Interaccion.query.join(Cliente).filter(
        Interaccion.id == interaccion_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    notas = request.form.get('notas', '')
    interaccion.marcar_seguimiento_completado(notas)
    db.session.commit()

    flash('Seguimiento marcado como completado.', 'success')
    return redirect(request.referrer or url_for('distribucion.interacciones_cliente', cliente_id=interaccion.cliente_id))


# ============================================================================
# CRM - ALERTAS
# ============================================================================

@distribucion_bp.route('/alertas')
@login_required
def alertas():
    """Panel de alertas."""
    from datetime import date

    tipo = request.args.get('tipo', '')
    estado = request.args.get('estado', 'pendiente')

    query = AlertaVencimiento.query.filter(
        AlertaVencimiento.usuario_id == current_user.id
    )

    if tipo:
        query = query.filter(AlertaVencimiento.tipo == tipo)
    if estado:
        query = query.filter(AlertaVencimiento.estado == estado)

    alertas = query.order_by(AlertaVencimiento.fecha_alerta).all()

    return render_template('distribucion/alertas.html',
                          alertas=alertas,
                          tipo_filtro=tipo,
                          estado_filtro=estado)


@distribucion_bp.route('/alertas/generar', methods=['POST'])
@login_required
def generar_alertas():
    """Generar alertas de vencimiento manualmente."""
    cantidad = AlertaVencimiento.generar_alertas_vencimiento_polizas(current_user.id)
    flash(f'Se generaron {cantidad} alertas nuevas.', 'success')
    return redirect(url_for('distribucion.alertas'))


@distribucion_bp.route('/alerta/<int:alerta_id>/resolver', methods=['POST'])
@login_required
def resolver_alerta(alerta_id):
    """Marcar alerta como resuelta."""
    alerta = AlertaVencimiento.query.filter_by(
        id=alerta_id,
        usuario_id=current_user.id
    ).first_or_404()

    alerta.marcar_resuelta()
    db.session.commit()

    flash('Alerta marcada como resuelta.', 'success')
    return redirect(request.referrer or url_for('distribucion.alertas'))


@distribucion_bp.route('/alerta/<int:alerta_id>/descartar', methods=['POST'])
@login_required
def descartar_alerta(alerta_id):
    """Descartar alerta."""
    alerta = AlertaVencimiento.query.filter_by(
        id=alerta_id,
        usuario_id=current_user.id
    ).first_or_404()

    alerta.descartar()
    db.session.commit()

    flash('Alerta descartada.', 'info')
    return redirect(request.referrer or url_for('distribucion.alertas'))


# ============================================================================
# CRM - SINIESTROS
# ============================================================================

@distribucion_bp.route('/poliza/<int:poliza_id>/siniestros')
@login_required
def siniestros_poliza(poliza_id):
    """Lista de siniestros de una póliza."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    siniestros = poliza.siniestros.order_by(Siniestro.fecha_ocurrencia.desc()).all()

    return render_template('distribucion/siniestros.html',
                          poliza=poliza,
                          siniestros=siniestros)


@distribucion_bp.route('/poliza/<int:poliza_id>/siniestros/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_siniestro(poliza_id):
    """Registrar nuevo siniestro."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    form = SiniestroForm()

    if form.validate_on_submit():
        # Procesar terceros
        terceros_json = None
        if form.terceros_texto.data:
            import json
            terceros_lista = []
            for linea in form.terceros_texto.data.split('\n'):
                if '-' in linea:
                    partes = linea.split('-')
                    terceros_lista.append({
                        'nombre': partes[0].strip(),
                        'telefono': partes[1].strip() if len(partes) > 1 else ''
                    })
            terceros_json = json.dumps(terceros_lista)

        siniestro = Siniestro(
            poliza_cliente_id=poliza.id,
            numero_siniestro=form.numero_siniestro.data,
            numero_siniestro_compania=form.numero_siniestro_compania.data,
            fecha_ocurrencia=form.fecha_ocurrencia.data,
            fecha_denuncia=form.fecha_denuncia.data,
            tipo_siniestro=form.tipo_siniestro.data,
            descripcion=form.descripcion.data,
            ubicacion=form.ubicacion.data,
            hay_lesionados=form.hay_lesionados.data,
            descripcion_lesiones=form.descripcion_lesiones.data if form.hay_lesionados.data else None,
            terceros_involucrados=terceros_json,
            monto_reclamado=form.monto_reclamado.data,
            estado=form.estado.data,
            notas=form.notas.data
        )
        db.session.add(siniestro)
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'siniestro_registrado',
            f'Siniestro registrado para póliza {poliza.numero_poliza or poliza.id}',
            request
        )

        flash('Siniestro registrado correctamente.', 'success')
        return redirect(url_for('distribucion.siniestros_poliza', poliza_id=poliza.id))

    return render_template('distribucion/siniestro_form.html',
                          form=form,
                          poliza=poliza,
                          titulo='Nuevo Siniestro')


@distribucion_bp.route('/siniestro/<int:siniestro_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_siniestro(siniestro_id):
    """Editar siniestro existente."""
    siniestro = Siniestro.query.join(PolizaCliente).join(Cliente).filter(
        Siniestro.id == siniestro_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    form = SiniestroForm(obj=siniestro)

    # Pre-cargar terceros
    if not form.is_submitted() and siniestro.terceros_involucrados:
        import json
        try:
            terceros = json.loads(siniestro.terceros_involucrados)
            form.terceros_texto.data = '\n'.join([f"{t.get('nombre', '')} - {t.get('telefono', '')}" for t in terceros])
        except:
            pass

    if form.validate_on_submit():
        siniestro.numero_siniestro = form.numero_siniestro.data
        siniestro.numero_siniestro_compania = form.numero_siniestro_compania.data
        siniestro.fecha_ocurrencia = form.fecha_ocurrencia.data
        siniestro.fecha_denuncia = form.fecha_denuncia.data
        siniestro.tipo_siniestro = form.tipo_siniestro.data
        siniestro.descripcion = form.descripcion.data
        siniestro.ubicacion = form.ubicacion.data
        siniestro.hay_lesionados = form.hay_lesionados.data
        siniestro.descripcion_lesiones = form.descripcion_lesiones.data if form.hay_lesionados.data else None
        siniestro.monto_reclamado = form.monto_reclamado.data
        siniestro.estado = form.estado.data
        siniestro.notas = form.notas.data

        # Procesar terceros
        if form.terceros_texto.data:
            import json
            terceros_lista = []
            for linea in form.terceros_texto.data.split('\n'):
                if '-' in linea:
                    partes = linea.split('-')
                    terceros_lista.append({
                        'nombre': partes[0].strip(),
                        'telefono': partes[1].strip() if len(partes) > 1 else ''
                    })
            siniestro.terceros_involucrados = json.dumps(terceros_lista)

        db.session.commit()

        flash('Siniestro actualizado correctamente.', 'success')
        return redirect(url_for('distribucion.siniestros_poliza', poliza_id=siniestro.poliza_cliente_id))

    return render_template('distribucion/siniestro_form.html',
                          form=form,
                          poliza=siniestro.poliza,
                          siniestro=siniestro,
                          titulo='Editar Siniestro')


@distribucion_bp.route('/siniestros')
@login_required
def todos_siniestros():
    """Lista de todos los siniestros."""
    estado = request.args.get('estado', '')

    query = Siniestro.query.join(PolizaCliente).join(Cliente).filter(
        Cliente.usuario_id == current_user.id
    )

    if estado:
        query = query.filter(Siniestro.estado == estado)

    siniestros = query.order_by(Siniestro.fecha_registro.desc()).all()

    return render_template('distribucion/todos_siniestros.html',
                          siniestros=siniestros,
                          estado_filtro=estado)


# ============================================================================
# INTERPRETE DE POLIZAS PDF
# ============================================================================

@distribucion_bp.route('/interprete-pdf')
@login_required
def interprete_pdf():
    """Panel principal del intérprete de pólizas PDF."""
    from app.extractor.pdf_parser import ExtractorDatosPoliza

    # Obtener archivos del usuario
    archivos = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    ).order_by(ArchivoDescargado.fecha_descarga.desc()).all()

    # Clasificar archivos
    pendientes = []  # Sin póliza asociada
    procesados = []  # Con póliza asociada

    for archivo in archivos:
        poliza_asociada = PolizaCliente.query.filter_by(archivo_id=archivo.id).first()
        if poliza_asociada:
            procesados.append({
                'archivo': archivo,
                'poliza': poliza_asociada,
                'confianza': poliza_asociada.confianza_extraccion
            })
        else:
            pendientes.append(archivo)

    # Estadísticas
    stats = {
        'total': len(archivos),
        'pendientes': len(pendientes),
        'procesados': len(procesados),
        'requieren_revision': sum(1 for p in procesados if p['poliza'].requiere_revision)
    }

    return render_template('distribucion/interprete_pdf.html',
                          pendientes=pendientes,
                          procesados=procesados,
                          stats=stats)


@distribucion_bp.route('/interprete-pdf/extraer/<int:archivo_id>')
@login_required
def extraer_pdf(archivo_id):
    """Extrae y muestra los datos de un PDF para revisión."""
    import os
    from app.extractor.pdf_parser import ExtractorDatosPoliza

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Verificar si ya tiene póliza asociada
    poliza_existente = PolizaCliente.query.filter_by(archivo_id=archivo.id).first()

    # Extraer datos del PDF
    datos_extraidos = {}
    error_extraccion = None

    if os.path.exists(archivo.ruta_archivo):
        try:
            extractor = ExtractorDatosPoliza()
            datos_extraidos = extractor.extraer_datos(archivo.ruta_archivo)
        except Exception as e:
            error_extraccion = str(e)
    else:
        error_extraccion = "Archivo no encontrado en el sistema"

    # Obtener clientes para asignar
    clientes = current_user.clientes.filter_by(activo=True).order_by(Cliente.nombre).all()

    # Obtener compañías
    companias = Compania.query.order_by(Compania.nombre).all()

    return render_template('distribucion/extraer_pdf.html',
                          archivo=archivo,
                          datos=datos_extraidos,
                          poliza_existente=poliza_existente,
                          clientes=clientes,
                          companias=companias,
                          error=error_extraccion,
                          tipos_seguro=PolizaCliente.TIPOS_SEGURO,
                          tipos_bien=PolizaCliente.TIPOS_BIEN,
                          formas_pago=PolizaCliente.FORMAS_PAGO)


@distribucion_bp.route('/interprete-pdf/guardar/<int:archivo_id>', methods=['POST'])
@login_required
def guardar_extraccion(archivo_id):
    """Guarda los datos extraídos/editados en la base de datos."""
    from datetime import datetime

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Verificar si ya existe póliza
    poliza_existente = PolizaCliente.query.filter_by(archivo_id=archivo.id).first()
    accion = request.form.get('accion', 'crear')  # crear, actualizar, omitir

    if accion == 'omitir':
        flash('Archivo omitido.', 'info')
        return redirect(url_for('distribucion.interprete_pdf'))

    # Obtener datos del formulario
    cliente_id = request.form.get('cliente_id')
    if not cliente_id:
        flash('Debe seleccionar un cliente.', 'warning')
        return redirect(url_for('distribucion.extraer_pdf', archivo_id=archivo_id))

    # Verificar que el cliente pertenece al usuario
    cliente = Cliente.query.filter_by(id=cliente_id, usuario_id=current_user.id).first()
    if not cliente:
        flash('Cliente no válido.', 'danger')
        return redirect(url_for('distribucion.extraer_pdf', archivo_id=archivo_id))

    # Parsear fechas
    def parsear_fecha(valor):
        if not valor:
            return None
        try:
            return datetime.strptime(valor, '%Y-%m-%d').date()
        except:
            return None

    # Parsear decimales
    def parsear_decimal(valor):
        if not valor:
            return None
        try:
            return float(valor.replace(',', '.'))
        except:
            return None

    # Parsear entero
    def parsear_int(valor):
        if not valor:
            return None
        try:
            return int(valor)
        except:
            return None

    # Datos a guardar
    datos_poliza = {
        'cliente_id': cliente.id,
        'archivo_id': archivo.id,
        'compania_id': parsear_int(request.form.get('compania_id')) or archivo.compania_id,
        'numero_poliza': request.form.get('numero_poliza'),
        'tipo_seguro': request.form.get('tipo_seguro'),
        'fecha_vigencia_desde': parsear_fecha(request.form.get('fecha_vigencia_desde')),
        'fecha_vigencia_hasta': parsear_fecha(request.form.get('fecha_vigencia_hasta')),
        'prima_anual': parsear_decimal(request.form.get('prima_anual')),
        'suma_asegurada': parsear_decimal(request.form.get('suma_asegurada')),
        'deducible': parsear_decimal(request.form.get('deducible')),
        'asegurado_nombre': request.form.get('asegurado_nombre'),
        'asegurado_documento': request.form.get('asegurado_documento'),
        'asegurado_direccion': request.form.get('asegurado_direccion'),
        'asegurado_telefono': request.form.get('asegurado_telefono'),
        'asegurado_email': request.form.get('asegurado_email'),
        'bien_asegurado_tipo': request.form.get('bien_asegurado_tipo'),
        'bien_asegurado_descripcion': request.form.get('bien_asegurado_descripcion'),
        'vehiculo_marca': request.form.get('vehiculo_marca'),
        'vehiculo_modelo': request.form.get('vehiculo_modelo'),
        'vehiculo_anio': parsear_int(request.form.get('vehiculo_anio')),
        'vehiculo_patente': request.form.get('vehiculo_patente'),
        'vehiculo_chasis': request.form.get('vehiculo_chasis'),
        'vehiculo_motor': request.form.get('vehiculo_motor'),
        'forma_pago': request.form.get('forma_pago'),
        'cantidad_cuotas': parsear_int(request.form.get('cantidad_cuotas')),
        'productor_nombre': request.form.get('productor_nombre'),
        'productor_telefono': request.form.get('productor_telefono'),
        'notas': request.form.get('notas'),
        'confianza_extraccion': parsear_decimal(request.form.get('confianza')),
        'requiere_revision': request.form.get('requiere_revision') == 'on',
        'fecha_extraccion': datetime.utcnow(),
    }

    if accion == 'actualizar' and poliza_existente:
        # Actualizar póliza existente
        for campo, valor in datos_poliza.items():
            if valor is not None:
                setattr(poliza_existente, campo, valor)
        poliza_existente.fecha_ultima_modificacion = datetime.utcnow()
        poliza_existente.modificado_por_id = current_user.id
        db.session.commit()
        flash(f'Póliza {poliza_existente.numero_poliza or poliza_existente.id} actualizada.', 'success')
    else:
        # Crear nueva póliza
        nueva_poliza = PolizaCliente(**datos_poliza)
        db.session.add(nueva_poliza)
        db.session.commit()
        flash(f'Póliza {nueva_poliza.numero_poliza or nueva_poliza.id} creada correctamente.', 'success')

    # Registrar actividad
    LogActividad.registrar(
        current_user.id,
        'poliza_desde_pdf',
        f'Póliza {"actualizada" if accion == "actualizar" else "creada"} desde PDF: {archivo.nombre_archivo}',
        request
    )

    # Verificar si hay más pendientes
    siguiente = request.form.get('siguiente')
    if siguiente == 'continuar':
        # Buscar siguiente PDF pendiente
        siguiente_archivo = ArchivoDescargado.query.join(Escaneo).outerjoin(
            PolizaCliente, PolizaCliente.archivo_id == ArchivoDescargado.id
        ).filter(
            Escaneo.usuario_id == current_user.id,
            PolizaCliente.id == None,
            ArchivoDescargado.id != archivo_id
        ).first()

        if siguiente_archivo:
            return redirect(url_for('distribucion.extraer_pdf', archivo_id=siguiente_archivo.id))

    return redirect(url_for('distribucion.interprete_pdf'))


@distribucion_bp.route('/interprete-pdf/lote', methods=['POST'])
@login_required
def procesar_lote_pdf():
    """Procesa múltiples PDFs automáticamente."""
    import os
    from app.extractor.pdf_parser import ExtractorDatosPoliza

    cliente_id = request.form.get('cliente_id')
    archivo_ids = request.form.getlist('archivo_ids')

    if not cliente_id:
        flash('Debe seleccionar un cliente para asignar las pólizas.', 'warning')
        return redirect(url_for('distribucion.interprete_pdf'))

    if not archivo_ids:
        flash('Debe seleccionar al menos un archivo.', 'warning')
        return redirect(url_for('distribucion.interprete_pdf'))

    cliente = Cliente.query.filter_by(id=cliente_id, usuario_id=current_user.id).first()
    if not cliente:
        flash('Cliente no válido.', 'danger')
        return redirect(url_for('distribucion.interprete_pdf'))

    procesados = 0
    errores = 0

    for archivo_id in archivo_ids:
        archivo = ArchivoDescargado.query.join(Escaneo).filter(
            ArchivoDescargado.id == archivo_id,
            Escaneo.usuario_id == current_user.id
        ).first()

        if not archivo:
            errores += 1
            continue

        # Verificar que no tenga póliza
        if PolizaCliente.query.filter_by(archivo_id=archivo.id).first():
            continue

        # Extraer datos
        if not os.path.exists(archivo.ruta_archivo):
            errores += 1
            continue

        try:
            extractor = ExtractorDatosPoliza()
            datos = extractor.extraer_datos(archivo.ruta_archivo)
            datos_poliza = extractor.datos_para_poliza(datos)

            # Crear póliza
            nueva_poliza = PolizaCliente(
                cliente_id=cliente.id,
                archivo_id=archivo.id,
                compania_id=archivo.compania_id,
                fecha_extraccion=datetime.utcnow(),
                **datos_poliza
            )
            db.session.add(nueva_poliza)
            procesados += 1

        except Exception as e:
            errores += 1
            continue

    db.session.commit()

    if procesados > 0:
        flash(f'{procesados} póliza(s) creada(s) correctamente.', 'success')
    if errores > 0:
        flash(f'{errores} archivo(s) con errores.', 'warning')

    return redirect(url_for('distribucion.interprete_pdf'))


@distribucion_bp.route('/interprete-pdf/reextraer/<int:poliza_id>')
@login_required
def reextraer_pdf(poliza_id):
    """Re-extrae datos de un PDF ya procesado para comparación."""
    import os
    from app.extractor.pdf_parser import ExtractorDatosPoliza

    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    if not poliza.archivo_id:
        flash('Esta póliza no tiene archivo PDF asociado.', 'warning')
        return redirect(url_for('distribucion.interprete_pdf'))

    archivo = ArchivoDescargado.query.get(poliza.archivo_id)
    if not archivo or not os.path.exists(archivo.ruta_archivo):
        flash('Archivo PDF no encontrado.', 'danger')
        return redirect(url_for('distribucion.interprete_pdf'))

    # Re-extraer datos
    extractor = ExtractorDatosPoliza()
    datos_nuevos = extractor.extraer_datos(archivo.ruta_archivo)

    return render_template('distribucion/comparar_extraccion.html',
                          poliza=poliza,
                          archivo=archivo,
                          datos_nuevos=datos_nuevos,
                          tipos_seguro=PolizaCliente.TIPOS_SEGURO)
