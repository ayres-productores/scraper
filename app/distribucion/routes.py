"""
Rutas del módulo de distribución de pólizas
"""

import os
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, jsonify, current_app, Response)
import json
import time
import uuid
import threading
from flask_login import login_required, current_user
from app import db
from app.models import (Cliente, PolizaCliente, EnvioWhatsApp, PlantillaMensaje,
                        ArchivoDescargado, Escaneo, Compania, LogActividad,
                        Pago, Interaccion, AlertaVencimiento, Siniestro,
                        RegistroAnalisisPDF, CuentaGmail, Inmobiliaria,
                        NotificacionInmobiliaria, WhatsAppSession)
from app.distribucion.forms import (ClienteForm, AsignarPolizaForm, PlantillaMensajeForm,
                                     EnvioForm, FiltroClientesForm, PolizaCompletaForm,
                                     InteraccionForm, PagoForm, GenerarCuotasForm,
                                     SiniestroForm, FiltroAlertasForm, InmobiliariaForm,
                                     AsignarInmobiliariaForm, PolizaEdicionRapidaForm)
from app.distribucion.whatsapp_sender import WhatsAppSender
from datetime import datetime, timedelta
import requests

distribucion_bp = Blueprint('distribucion', __name__)

# Almacenamiento de progreso para análisis en lote (en memoria)
# Estructura: {task_id: {status, total, procesados, errores, actual, log, finalizado}}
_progreso_analisis = {}
_progreso_lock = threading.Lock()


def sincronizar_sesion_whatsapp(usuario_id):
    """
    Sincroniza el estado de la sesión WhatsApp entre el servicio Node.js y la DB.
    Retorna la sesión actualizada o None si hay error.
    """
    from flask import current_app

    session = WhatsAppSession.query.filter_by(usuario_id=usuario_id).first()
    if not session:
        return None

    try:
        service_url = current_app.config.get('WHATSAPP_SERVICE_URL', 'http://localhost:3001')
        response = requests.get(
            f"{service_url}/session/{usuario_id}/status",
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            nuevo_estado = data.get('status', 'disconnected')

            # Solo actualizar si el estado cambió
            if nuevo_estado != session.estado:
                session.estado = nuevo_estado

                if nuevo_estado == 'ready':
                    session.telefono_conectado = data.get('phone')
                    if not session.fecha_conexion:
                        session.fecha_conexion = datetime.utcnow()
                elif nuevo_estado == 'disconnected':
                    session.fecha_desconexion = datetime.utcnow()

                session.mensaje_error = None
                db.session.commit()

        elif response.status_code == 404:
            # No hay sesión en el servicio, marcar como desconectada
            if session.estado not in ['disconnected', 'error']:
                session.estado = 'disconnected'
                db.session.commit()

    except requests.exceptions.RequestException:
        # Servicio no disponible - mantener estado actual
        pass
    except Exception as e:
        session.mensaje_error = str(e)
        db.session.commit()

    return session


@distribucion_bp.route('/')
@login_required
def index():
    """Panel principal de distribución."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    # Estadísticas
    total_clientes = Cliente.query.filter_by(activo=True).count()
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
    """Listado de clientes con filtro opcional por pólizas vigentes."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    from datetime import date

    busqueda = request.args.get('busqueda', '')
    ordenar = request.args.get('ordenar', 'nombre_asc')
    solo_vigentes = request.args.get('solo_vigentes', '0') == '1'

    # Query base: todos los clientes (visibles para todos los usuarios)
    query = Cliente.query

    # Filtrar solo clientes con pólizas vigentes si está activado
    if solo_vigentes:
        clientes_con_poliza_vigente = db.session.query(
            PolizaCliente.cliente_id
        ).filter(
            PolizaCliente.estado.in_(['activa', 'en_renovacion']),
            PolizaCliente.fecha_vigencia_hasta >= date.today()
        ).distinct().subquery()

        query = query.filter(
            Cliente.id.in_(db.session.query(clientes_con_poliza_vigente.c.cliente_id))
        )

    # Aplicar búsqueda si existe
    if busqueda:
        query = query.filter(
            db.or_(
                Cliente.nombre.ilike(f'%{busqueda}%'),
                Cliente.apellido.ilike(f'%{busqueda}%'),
                Cliente.telefono_whatsapp.ilike(f'%{busqueda}%'),
                Cliente.documento_identidad.ilike(f'%{busqueda}%')
            )
        )

    # Opciones de ordenamiento
    if ordenar == 'nombre_desc':
        clientes = query.order_by(Cliente.nombre.desc()).all()
    elif ordenar == 'mayor_vigencia':
        # Subconsulta: máxima fecha de vigencia por cliente (solo pólizas activas)
        from sqlalchemy import func
        subq = db.session.query(
            PolizaCliente.cliente_id,
            func.max(PolizaCliente.fecha_vigencia_hasta).label('max_vigencia')
        ).filter(
            PolizaCliente.estado.in_(['activa', 'en_renovacion'])
        ).group_by(PolizaCliente.cliente_id).subquery()

        # JOIN con la subconsulta y ordenar
        clientes = query.outerjoin(
            subq, Cliente.id == subq.c.cliente_id
        ).order_by(
            subq.c.max_vigencia.desc().nullslast(),
            Cliente.nombre
        ).all()
    elif ordenar == 'proximo_vencer':
        # Similar pero orden ascendente (más próximo a vencer primero)
        from sqlalchemy import func
        subq = db.session.query(
            PolizaCliente.cliente_id,
            func.min(PolizaCliente.fecha_vigencia_hasta).label('min_vigencia')
        ).filter(
            PolizaCliente.estado.in_(['activa', 'en_renovacion']),
            PolizaCliente.fecha_vigencia_hasta >= date.today()
        ).group_by(PolizaCliente.cliente_id).subquery()

        clientes = query.outerjoin(
            subq, Cliente.id == subq.c.cliente_id
        ).order_by(
            subq.c.min_vigencia.asc().nullslast(),
            Cliente.nombre
        ).all()
    else:  # nombre_asc (default)
        clientes = query.order_by(Cliente.nombre).all()

    return render_template('distribucion/clientes.html',
                          clientes=clientes,
                          busqueda=busqueda,
                          ordenar=ordenar,
                          solo_vigentes=solo_vigentes)


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


@distribucion_bp.route('/clientes-reactivar')
@login_required
def clientes_reactivar():
    """Lista de clientes que necesitan reactivación."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    from app.tasks.clientes_actuales import obtener_clientes_a_reactivar, obtener_estadisticas_reactivacion

    clientes = obtener_clientes_a_reactivar(current_user.id)
    estadisticas = obtener_estadisticas_reactivacion(current_user.id)

    return render_template('distribucion/clientes_reactivar.html',
                          clientes=clientes,
                          estadisticas=estadisticas)


@distribucion_bp.route('/clientes-reactivar/evaluar', methods=['POST'])
@login_required
def evaluar_clientes():
    """Ejecuta la evaluación de clientes actuales manualmente."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    from app.tasks.clientes_actuales import evaluar_clientes_actuales

    resultados = evaluar_clientes_actuales(current_user.id)

    flash(f'Evaluación completada: {resultados["total_evaluados"]} clientes evaluados, '
          f'{resultados["no_actuales"]} requieren reactivación.', 'success')

    return redirect(url_for('distribucion.clientes_reactivar'))


@distribucion_bp.route('/cliente/<int:cliente_id>/marcar-gestionado', methods=['POST'])
@login_required
def marcar_cliente_gestionado(cliente_id):
    """Marca un cliente como gestionado (resuelve alerta de reactivación)."""
    cliente = Cliente.query.filter_by(
        id=cliente_id,
        usuario_id=current_user.id
    ).first_or_404()

    # Resolver alertas de reactivación pendientes
    alertas = AlertaVencimiento.query.filter_by(
        usuario_id=current_user.id,
        tipo='reactivacion_cliente',
        estado='pendiente'
    ).filter(
        AlertaVencimiento.mensaje.contains(f"Cliente: {cliente.nombre_completo}")
    ).all()

    for alerta in alertas:
        alerta.estado = 'resuelta'
        alerta.fecha_notificacion = datetime.utcnow()

    db.session.commit()

    flash(f'Cliente {cliente.nombre_completo} marcado como gestionado.', 'success')
    return redirect(url_for('distribucion.clientes_reactivar'))


# ============================================================================
# ASIGNACIÓN DE PÓLIZAS
# ============================================================================

@distribucion_bp.route('/asignar', methods=['GET', 'POST'])
@login_required
def asignar_poliza():
    """Asignar póliza a cliente."""
    form = AsignarPolizaForm()

    # Cargar opciones de clientes
    clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
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
    """Enviar mensaje directo a cliente sin póliza específica (fallback a wa.me)."""
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


@distribucion_bp.route('/api/cliente/<int:cliente_id>/polizas', methods=['GET'])
@login_required
def api_cliente_polizas(cliente_id):
    """
    Obtiene las pólizas de un cliente para el modal de selección.
    Retorna pólizas con información de vigencia y disponibilidad de PDF.
    """
    from datetime import date

    cliente = Cliente.query.filter_by(
        id=cliente_id,
        usuario_id=current_user.id
    ).first()

    if not cliente:
        return jsonify({'success': False, 'error': 'Cliente no encontrado'}), 404

    hoy = date.today()
    polizas_data = []

    for poliza in cliente.polizas.order_by(PolizaCliente.fecha_vigencia_hasta.desc()).all():
        # Verificar si tiene PDF disponible
        tiene_pdf = False
        if poliza.ruta_pdf_backup and os.path.exists(poliza.ruta_pdf_backup):
            tiene_pdf = True
        elif poliza.archivo and poliza.archivo.ruta_archivo and os.path.exists(poliza.archivo.ruta_archivo):
            tiene_pdf = True

        # Verificar vigencia
        esta_vigente = False
        if poliza.fecha_vigencia_hasta:
            esta_vigente = poliza.fecha_vigencia_hasta >= hoy

        polizas_data.append({
            'id': poliza.id,
            'numero_poliza': poliza.numero_poliza or f'Póliza #{poliza.id}',
            'tipo_seguro': poliza.tipo_seguro or 'Sin tipo',
            'compania': poliza.compania.nombre if poliza.compania else 'Sin compañía',
            'fecha_vigencia_hasta': poliza.fecha_vigencia_hasta.strftime('%d/%m/%Y') if poliza.fecha_vigencia_hasta else 'Sin fecha',
            'tiene_pdf': tiene_pdf,
            'esta_vigente': esta_vigente
        })

    return jsonify({
        'success': True,
        'cliente': {
            'id': cliente.id,
            'nombre': cliente.nombre_completo,
            'telefono': cliente.telefono_whatsapp
        },
        'polizas': polizas_data
    })


@distribucion_bp.route('/whatsapp/enviar-mensaje', methods=['POST'])
@login_required
def whatsapp_enviar_mensaje():
    """
    Enviar mensaje de WhatsApp en background (AJAX).
    Soporta envío de texto y múltiples documentos PDF.
    """
    try:
        data = request.get_json()
        cliente_id = data.get('cliente_id')
        poliza_id = data.get('poliza_id')  # Compatibilidad: una sola póliza
        poliza_ids = data.get('poliza_ids', [])  # Nueva: múltiples pólizas
        mensaje = data.get('mensaje')

        if not cliente_id:
            return jsonify({'success': False, 'error': 'Cliente no especificado'}), 400

        # Obtener cliente
        cliente = Cliente.query.filter_by(
            id=cliente_id,
            usuario_id=current_user.id
        ).first()

        if not cliente:
            return jsonify({'success': False, 'error': 'Cliente no encontrado'}), 404

        if not cliente.telefono_whatsapp:
            return jsonify({'success': False, 'error': 'Cliente sin número de WhatsApp'}), 400

        # Sincronizar y verificar sesión de WhatsApp activa
        wa_session = sincronizar_sesion_whatsapp(current_user.id)

        if not wa_session or wa_session.estado != 'ready':
            return jsonify({
                'success': False,
                'error': 'No tienes una sesión de WhatsApp activa. Configura tu WhatsApp primero.',
                'redirect': url_for('distribucion.whatsapp_configurar')
            }), 400

        # Obtener mensaje si no viene en el request
        if not mensaje:
            if cliente.usar_mensaje_estandar:
                plantilla = PlantillaMensaje.obtener_predeterminada(current_user.id)
                mensaje = plantilla.renderizar(cliente) if plantilla else f"Hola {cliente.nombre}"
            else:
                mensaje = cliente.mensaje_personalizado or f"Hola {cliente.nombre}"

        # Preparar lista de PDFs a enviar
        pdfs_a_enviar = []

        # Compatibilidad: si viene poliza_id único, agregarlo a la lista
        if poliza_id and poliza_id not in poliza_ids:
            poliza_ids = [poliza_id] + poliza_ids

        if poliza_ids:
            # Pólizas específicas seleccionadas
            for pid in poliza_ids:
                poliza = PolizaCliente.query.filter_by(
                    id=pid,
                    cliente_id=cliente_id
                ).first()

                if poliza:
                    ruta_pdf = None
                    nombre_pdf = None

                    if poliza.ruta_pdf_backup and os.path.exists(poliza.ruta_pdf_backup):
                        ruta_pdf = poliza.ruta_pdf_backup
                        nombre_pdf = f"Poliza_{poliza.numero_poliza or poliza.id}.pdf"
                    elif poliza.archivo and poliza.archivo.ruta_archivo and os.path.exists(poliza.archivo.ruta_archivo):
                        ruta_pdf = poliza.archivo.ruta_archivo
                        nombre_pdf = poliza.archivo.nombre_archivo or f'poliza_{poliza.id}.pdf'

                    if ruta_pdf:
                        pdfs_a_enviar.append({
                            'poliza': poliza,
                            'ruta': ruta_pdf,
                            'nombre': nombre_pdf
                        })
        else:
            # Buscar automáticamente la mejor póliza con PDF
            from datetime import date
            hoy = date.today()

            polizas_vigentes = PolizaCliente.query.filter(
                PolizaCliente.cliente_id == cliente_id,
                PolizaCliente.fecha_vigencia_hasta >= hoy
            ).order_by(PolizaCliente.fecha_vigencia_hasta.desc()).all()

            for p in polizas_vigentes:
                if p.ruta_pdf_backup and os.path.exists(p.ruta_pdf_backup):
                    pdfs_a_enviar.append({
                        'poliza': p,
                        'ruta': p.ruta_pdf_backup,
                        'nombre': f"Poliza_{p.numero_poliza or p.id}.pdf"
                    })
                    break
                elif p.archivo and p.archivo.ruta_archivo and os.path.exists(p.archivo.ruta_archivo):
                    pdfs_a_enviar.append({
                        'poliza': p,
                        'ruta': p.archivo.ruta_archivo,
                        'nombre': p.archivo.nombre_archivo or f'poliza_{p.id}.pdf'
                    })
                    break

        # Enviar vía servicio WhatsApp Web
        service_url = current_app.config.get('WHATSAPP_SERVICE_URL', 'http://localhost:3001')
        timeout = current_app.config.get('WHATSAPP_SERVICE_TIMEOUT', 30)
        telefono = cliente.telefono_formateado.replace('+', '').replace(' ', '').replace('-', '')

        pdfs_enviados = 0
        primer_mensaje_id = None

        if pdfs_a_enviar:
            # Enviar primer PDF con el mensaje como caption
            primer_pdf = pdfs_a_enviar[0]
            response = requests.post(
                f"{service_url}/session/{current_user.id}/send-document",
                json={
                    'phone': telefono,
                    'filePath': primer_pdf['ruta'],
                    'filename': primer_pdf['nombre'],
                    'caption': mensaje
                },
                timeout=timeout
            )

            if response.status_code == 200 and response.json().get('success'):
                pdfs_enviados = 1
                primer_mensaje_id = response.json().get('messageId')

                # Enviar PDFs adicionales sin mensaje (con pausa entre envíos)
                for pdf_info in pdfs_a_enviar[1:]:
                    try:
                        # Pausa para evitar error de frame desconectado en WhatsApp Web
                        time.sleep(2)

                        resp = requests.post(
                            f"{service_url}/session/{current_user.id}/send-document",
                            json={
                                'phone': telefono,
                                'filePath': pdf_info['ruta'],
                                'filename': pdf_info['nombre'],
                                'caption': ''
                            },
                            timeout=timeout
                        )
                        if resp.status_code == 200 and resp.json().get('success'):
                            pdfs_enviados += 1
                    except:
                        pass  # Continuar con los demás si uno falla
            else:
                return jsonify({
                    'success': False,
                    'error': response.json().get('error', 'Error al enviar documento')
                }), 500
        else:
            # Enviar solo texto
            response = requests.post(
                f"{service_url}/session/{current_user.id}/send",
                json={
                    'phone': telefono,
                    'message': mensaje
                },
                timeout=timeout
            )

            if response.status_code != 200 or not response.json().get('success'):
                return jsonify({
                    'success': False,
                    'error': response.json().get('error', 'Error al enviar mensaje')
                }), 500

            primer_mensaje_id = response.json().get('messageId')

        # Registrar envío
        envio = EnvioWhatsApp(
            cliente_id=cliente.id,
            poliza_cliente_id=pdfs_a_enviar[0]['poliza'].id if pdfs_a_enviar else None,
            archivo_id=pdfs_a_enviar[0]['poliza'].archivo_id if pdfs_a_enviar and pdfs_a_enviar[0]['poliza'].archivo_id else None,
            mensaje_enviado=mensaje,
            estado='enviado',
            fecha_envio=datetime.utcnow(),
            wamid=primer_mensaje_id
        )
        db.session.add(envio)

        # Actualizar último envío del cliente
        cliente.ultimo_envio = datetime.utcnow()

        # Actualizar uso de sesión
        wa_session.actualizar_uso()

        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'whatsapp_enviado',
            f'Mensaje enviado a {cliente.nombre_completo} con {pdfs_enviados} PDF(s)',
            request
        )

        return jsonify({
            'success': True,
            'message': f'Mensaje enviado a {cliente.nombre_completo}',
            'pdfs_enviados': pdfs_enviados
        })

    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'error': 'Servicio de WhatsApp no disponible. Verifica que esté corriendo.'
        }), 503
    except requests.exceptions.Timeout:
        return jsonify({
            'success': False,
            'error': 'Timeout al conectar con el servicio de WhatsApp'
        }), 504
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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
# BÚSQUEDA DE PÓLIZAS
# ============================================================================

@distribucion_bp.route('/buscar-polizas')
@login_required
def buscar_polizas():
    """Búsqueda y listado de pólizas con filtros."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    # Parámetros de búsqueda
    busqueda = request.args.get('busqueda', '').strip()
    compania_id = request.args.get('compania', '', type=str)
    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 50

    # Query base: archivos del usuario actual
    query = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    )

    # Filtro por compañía
    if compania_id and compania_id.isdigit():
        query = query.filter(ArchivoDescargado.compania_id == int(compania_id))

    # Búsqueda por texto (nombre archivo, asunto, patente en nombre)
    if busqueda:
        patron_busqueda = f'%{busqueda}%'
        query = query.filter(
            db.or_(
                ArchivoDescargado.nombre_archivo.ilike(patron_busqueda),
                ArchivoDescargado.asunto.ilike(patron_busqueda),
                ArchivoDescargado.remitente.ilike(patron_busqueda)
            )
        )

    # Ordenar por fecha de descarga (más recientes primero)
    query = query.order_by(ArchivoDescargado.fecha_descarga.desc())

    # Paginación
    total = query.count()
    polizas = query.offset((pagina - 1) * por_pagina).limit(por_pagina).all()
    total_paginas = (total + por_pagina - 1) // por_pagina

    # Obtener lista de compañías para el filtro
    companias = Compania.query.filter(
        Compania.id.in_(
            db.session.query(ArchivoDescargado.compania_id).join(Escaneo).filter(
                Escaneo.usuario_id == current_user.id,
                ArchivoDescargado.compania_id.isnot(None)
            ).distinct()
        )
    ).order_by(Compania.nombre).all()

    return render_template('distribucion/buscar_polizas.html',
                          polizas=polizas,
                          companias=companias,
                          busqueda=busqueda,
                          compania_id=compania_id,
                          pagina=pagina,
                          total_paginas=total_paginas,
                          total=total)


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

    clientes = Cliente.query.filter(
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
    total_clientes = Cliente.query.filter_by(activo=True).count()
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

    # Clientes a reactivar
    clientes_a_reactivar = Cliente.query.filter_by(
        usuario_id=current_user.id,
        activo=True,
        es_cliente_actual=False
    ).count()

    return render_template('distribucion/crm_dashboard.html',
                          total_clientes=total_clientes,
                          total_polizas=total_polizas,
                          polizas_por_vencer=polizas_por_vencer,
                          pagos_pendientes=pagos_pendientes,
                          alertas_pendientes=alertas_pendientes,
                          seguimientos=seguimientos,
                          siniestros_activos=siniestros_activos,
                          clientes_a_reactivar=clientes_a_reactivar)


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
    clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
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


@distribucion_bp.route('/poliza/<int:poliza_id>/editar', methods=['GET', 'POST'])
@login_required
def poliza_edicion_rapida(poliza_id):
    """Edición rápida de póliza con campos esenciales."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    form = PolizaEdicionRapidaForm(obj=poliza)

    # Cargar opciones de compañías
    companias = Compania.query.order_by(Compania.nombre).all()
    form.compania_id.choices = [(0, 'Seleccionar...')] + [(c.id, c.nombre) for c in companias]

    if form.validate_on_submit():
        # Actualizar campos esenciales
        poliza.numero_poliza = form.numero_poliza.data
        poliza.tipo_seguro = form.tipo_seguro.data
        poliza.compania_id = form.compania_id.data if form.compania_id.data else None
        poliza.fecha_vigencia_desde = form.fecha_vigencia_desde.data
        poliza.fecha_vigencia_hasta = form.fecha_vigencia_hasta.data
        poliza.prima_anual = form.prima_anual.data
        poliza.estado = form.estado.data
        poliza.asegurado_nombre = form.asegurado_nombre.data
        poliza.asegurado_documento = form.asegurado_documento.data
        poliza.forma_pago = form.forma_pago.data
        poliza.notas = form.notas.data
        poliza.modificado_por_id = current_user.id

        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'poliza_editada_rapida',
            f'Póliza {poliza.numero_poliza or poliza.id} editada (edición rápida)',
            request
        )

        flash('Póliza actualizada correctamente.', 'success')
        return redirect(url_for('distribucion.cliente_detalle', cliente_id=poliza.cliente_id))

    return render_template('distribucion/poliza_edicion_rapida.html',
                          form=form,
                          poliza=poliza)


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

    # Obtener todos los clientes activos (visibles para todos los usuarios)
    clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()

    return render_template('distribucion/interprete_pdf.html',
                          pendientes=pendientes,
                          procesados=procesados,
                          stats=stats,
                          clientes=clientes)


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
    clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()

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


# ============================================================================
# ASIGNACION INTELIGENTE DE POLIZAS
# ============================================================================

@distribucion_bp.route('/asignar-inteligente')
@login_required
def asignar_poliza_inteligente():
    """Panel de asignacion inteligente de polizas con extraccion automatica."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    # Obtener archivos del usuario que no tienen poliza asociada
    archivos_pendientes = ArchivoDescargado.query.join(Escaneo).outerjoin(
        PolizaCliente, PolizaCliente.archivo_id == ArchivoDescargado.id
    ).filter(
        Escaneo.usuario_id == current_user.id,
        PolizaCliente.id == None
    ).order_by(ArchivoDescargado.fecha_descarga.desc()).all()

    # Obtener clientes activos
    clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()

    # Obtener companias
    companias = Compania.query.order_by(Compania.nombre).all()

    # Obtener inmobiliarias activas
    inmobiliarias_lista = Inmobiliaria.query.filter_by(
        usuario_id=current_user.id,
        activa=True
    ).order_by(Inmobiliaria.nombre).all()

    # Estadisticas - contar PDFs reales en disco
    import os
    carpeta_usuario = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'archivos_usuarios'), str(current_user.id))
    pdfs_en_disco = 0
    if os.path.exists(carpeta_usuario):
        for root, dirs, files in os.walk(carpeta_usuario):
            pdfs_en_disco += len([f for f in files if f.lower().endswith('.pdf')])

    total_asignados = PolizaCliente.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        PolizaCliente.archivo_id.isnot(None)
    ).count()

    return render_template('distribucion/asignar_poliza_inteligente.html',
                          archivos=archivos_pendientes,
                          clientes=clientes,
                          companias=companias,
                          inmobiliarias=inmobiliarias_lista,
                          total_archivos=pdfs_en_disco,
                          total_asignados=total_asignados,
                          pendientes=len(archivos_pendientes),
                          tipos_seguro=PolizaCliente.TIPOS_SEGURO,
                          tipos_bien=PolizaCliente.TIPOS_BIEN,
                          formas_pago=PolizaCliente.FORMAS_PAGO)


@distribucion_bp.route('/api/extraer-pdf/<int:archivo_id>')
@login_required
def api_extraer_datos_pdf(archivo_id):
    """API que extrae datos de un PDF y los devuelve en JSON."""
    import os
    from app.extractor.pdf_parser import ExtractorDatosPoliza

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first()

    if not archivo:
        return jsonify({
            'exito': False,
            'error': 'Archivo no encontrado'
        }), 404

    if not os.path.exists(archivo.ruta_archivo):
        return jsonify({
            'exito': False,
            'error': 'El archivo PDF no existe en el servidor'
        }), 404

    try:
        extractor = ExtractorDatosPoliza()
        datos = extractor.extraer_datos(archivo.ruta_archivo)
        resumen = extractor.resumen_extraccion()

        # Agregar informacion del archivo
        datos['archivo_id'] = archivo.id
        datos['archivo_nombre'] = archivo.nombre_archivo
        datos['archivo_fecha'] = archivo.fecha_correo.strftime('%Y-%m-%d') if archivo.fecha_correo else None
        datos['archivo_remitente'] = archivo.remitente
        datos['archivo_asunto'] = archivo.asunto

        # Si el archivo ya tiene compania detectada, usar esa
        if archivo.compania_id and not datos.get('compania_detectada'):
            compania = Compania.query.get(archivo.compania_id)
            if compania:
                datos['compania_nombre_formal'] = compania.nombre
                datos['compania_id_sugerida'] = compania.id

        # Formatear fechas para JSON
        if datos.get('fecha_vigencia_desde'):
            datos['fecha_vigencia_desde'] = datos['fecha_vigencia_desde'].isoformat()
        if datos.get('fecha_vigencia_hasta'):
            datos['fecha_vigencia_hasta'] = datos['fecha_vigencia_hasta'].isoformat()

        # Formatear montos para JSON
        if datos.get('prima_anual'):
            datos['prima_anual'] = float(datos['prima_anual'])
        if datos.get('suma_asegurada'):
            datos['suma_asegurada'] = float(datos['suma_asegurada'])
        if datos.get('deducible'):
            datos['deducible'] = float(datos['deducible'])

        # Quitar texto muestra del JSON (muy grande)
        datos.pop('texto_muestra', None)

        return jsonify({
            'exito': True,
            'datos': datos,
            'resumen': resumen
        })

    except Exception as e:
        return jsonify({
            'exito': False,
            'error': str(e)
        }), 500


@distribucion_bp.route('/asignar-inteligente/guardar', methods=['POST'])
@login_required
def guardar_asignacion_inteligente():
    """Guarda la poliza con los datos extraidos/editados."""
    from datetime import datetime
    import json as json_module

    # Obtener datos del formulario
    archivo_id = request.form.get('archivo_id')
    cliente_id = request.form.get('cliente_id')
    crear_cliente = request.form.get('crear_cliente') == '1'

    if not archivo_id:
        flash('Debe seleccionar un archivo.', 'warning')
        return redirect(url_for('distribucion.asignar_poliza_inteligente'))

    # Verificar archivo
    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first()

    if not archivo:
        flash('Archivo no encontrado.', 'danger')
        return redirect(url_for('distribucion.asignar_poliza_inteligente'))

    # Manejar cliente: crear nuevo o usar existente
    cliente = None

    if crear_cliente:
        # Crear nuevo cliente con los datos del formulario
        nombre_completo = request.form.get('cliente_nombre', '').strip()
        telefono = request.form.get('telefono_whatsapp', '').strip()

        if not nombre_completo:
            flash('El nombre del cliente es requerido.', 'warning')
            return redirect(url_for('distribucion.asignar_poliza_inteligente'))

        # Parsear nombre
        nombre = nombre_completo
        apellido = ''
        if ',' in nombre_completo:
            partes = nombre_completo.split(',', 1)
            apellido = partes[0].strip()
            nombre = partes[1].strip() if len(partes) > 1 else ''
        elif ' ' in nombre_completo:
            partes = nombre_completo.split(' ', 1)
            nombre = partes[0].strip()
            apellido = partes[1].strip() if len(partes) > 1 else ''

        cliente = Cliente(
            usuario_id=current_user.id,
            nombre=nombre,
            apellido=apellido,
            telefono_whatsapp=telefono,
            email=request.form.get('cliente_email'),
            documento_identidad=request.form.get('cliente_documento'),
            usar_mensaje_estandar=True
        )
        db.session.add(cliente)
        db.session.flush()  # Para obtener el ID

    else:
        # Usar cliente existente
        if not cliente_id:
            flash('Debe seleccionar un cliente.', 'warning')
            return redirect(url_for('distribucion.asignar_poliza_inteligente'))

        cliente = Cliente.query.filter_by(id=cliente_id, usuario_id=current_user.id).first()
        if not cliente:
            flash('Cliente no valido.', 'danger')
            return redirect(url_for('distribucion.asignar_poliza_inteligente'))

    # Verificar si ya existe poliza para este archivo
    poliza_existente = PolizaCliente.query.filter_by(archivo_id=archivo.id).first()
    if poliza_existente:
        flash('Este archivo ya tiene una poliza asignada.', 'warning')
        return redirect(url_for('distribucion.asignar_poliza_inteligente'))

    # Funciones auxiliares de parseo
    def parsear_fecha(valor):
        if not valor:
            return None
        try:
            return datetime.strptime(valor, '%Y-%m-%d').date()
        except:
            return None

    def parsear_decimal(valor):
        if not valor:
            return None
        try:
            return float(str(valor).replace(',', '.'))
        except:
            return None

    def parsear_int(valor):
        if not valor:
            return None
        try:
            return int(valor)
        except:
            return None

    # Crear poliza con todos los datos
    poliza = PolizaCliente(
        cliente_id=cliente.id,
        archivo_id=archivo.id,
        compania_id=parsear_int(request.form.get('compania_id')) or archivo.compania_id,
        numero_poliza=request.form.get('numero_poliza'),
        tipo_seguro=request.form.get('tipo_seguro'),
        fecha_vigencia_desde=parsear_fecha(request.form.get('fecha_vigencia_desde')),
        fecha_vigencia_hasta=parsear_fecha(request.form.get('fecha_vigencia_hasta')),
        prima_anual=parsear_decimal(request.form.get('prima_anual')),
        suma_asegurada=parsear_decimal(request.form.get('suma_asegurada')),
        deducible=parsear_decimal(request.form.get('deducible')),

        # Asegurado
        asegurado_nombre=request.form.get('asegurado_nombre'),
        asegurado_documento=request.form.get('asegurado_documento'),
        asegurado_direccion=request.form.get('asegurado_direccion'),
        asegurado_telefono=request.form.get('asegurado_telefono'),
        asegurado_email=request.form.get('asegurado_email'),

        # Bien asegurado
        bien_asegurado_tipo=request.form.get('bien_asegurado_tipo'),
        bien_asegurado_descripcion=request.form.get('bien_asegurado_descripcion'),
        bien_asegurado_valor=parsear_decimal(request.form.get('bien_asegurado_valor')),

        # Vehiculo
        vehiculo_marca=request.form.get('vehiculo_marca'),
        vehiculo_modelo=request.form.get('vehiculo_modelo'),
        vehiculo_anio=parsear_int(request.form.get('vehiculo_anio')),
        vehiculo_patente=request.form.get('vehiculo_patente'),
        vehiculo_chasis=request.form.get('vehiculo_chasis'),
        vehiculo_motor=request.form.get('vehiculo_motor'),
        vehiculo_color=request.form.get('vehiculo_color'),
        vehiculo_uso=request.form.get('vehiculo_uso'),

        # Inmueble
        inmueble_direccion=request.form.get('inmueble_direccion'),
        inmueble_tipo=request.form.get('inmueble_tipo'),
        inmueble_superficie=parsear_decimal(request.form.get('inmueble_superficie')),

        # Inmobiliaria (solo para incendio/hogar)
        inmobiliaria_id=parsear_int(request.form.get('inmobiliaria_id')),

        # Pago
        forma_pago=request.form.get('forma_pago'),
        cantidad_cuotas=parsear_int(request.form.get('cantidad_cuotas')),

        # Productor
        productor_nombre=request.form.get('productor_nombre'),
        productor_telefono=request.form.get('productor_telefono'),
        productor_email=request.form.get('productor_email'),

        # Metadatos de extraccion
        confianza_extraccion=parsear_decimal(request.form.get('confianza')),
        requiere_revision=request.form.get('requiere_revision') == 'on',
        fecha_extraccion=datetime.utcnow(),

        # Notas
        notas=request.form.get('notas'),
    )

    db.session.add(poliza)
    db.session.flush()  # Para obtener poliza.id antes del commit

    # Registrar correcciones para aprendizaje
    correcciones_json = request.form.get('correcciones_json', '[]')
    tiempo_edicion = request.form.get('tiempo_edicion', '0')

    try:
        correcciones = json_module.loads(correcciones_json)
        if correcciones:
            from app.extractor.aprendizaje import registrar_lote_correcciones

            contexto = {
                'archivo_id': archivo.id,
                'usuario_id': current_user.id,
                'poliza_id': poliza.id,
                'cliente_id': cliente.id,
                'compania': archivo.compania.nombre if archivo.compania else None,
                'tipo_seguro': poliza.tipo_seguro,
                'tiempo_edicion': int(tiempo_edicion) if tiempo_edicion else 0
            }

            correcciones_registradas, _ = registrar_lote_correcciones(correcciones, contexto)
            current_app.logger.info(f'Registradas {correcciones_registradas} correcciones para poliza {poliza.id}')
    except Exception as e:
        current_app.logger.warning(f'Error registrando correcciones: {e}')

    db.session.commit()

    # Crear backup del PDF automaticamente
    from app.distribucion.backup_polizas import crear_backup_poliza
    crear_backup_poliza(poliza)

    # Registrar actividad
    tipo_actividad = 'poliza_asignada_inteligente_cliente_nuevo' if crear_cliente else 'poliza_asignada_inteligente'
    LogActividad.registrar(
        current_user.id,
        tipo_actividad,
        f'Poliza {poliza.numero_poliza or poliza.id} asignada a {cliente.nombre_completo}',
        request
    )

    flash(f'Poliza asignada correctamente a {cliente.nombre_completo}.', 'success')

    # Verificar si continuar con el siguiente
    if request.form.get('continuar') == '1':
        return redirect(url_for('distribucion.asignar_poliza_inteligente'))

    return redirect(url_for('distribucion.cliente_detalle', cliente_id=cliente.id))


@distribucion_bp.route('/api/vista-previa-pdf/<int:archivo_id>')
@login_required
def api_vista_previa_pdf(archivo_id):
    """Devuelve la URL o ruta para vista previa del PDF."""
    import os
    from flask import send_file

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first()

    if not archivo or not os.path.exists(archivo.ruta_archivo):
        return jsonify({'error': 'Archivo no encontrado'}), 404

    return send_file(archivo.ruta_archivo, mimetype='application/pdf')


@distribucion_bp.route('/api/crear-cliente-rapido', methods=['POST'])
@login_required
def api_crear_cliente_rapido():
    """Crea un cliente rapidamente desde el formulario de asignacion."""
    data = request.get_json()

    nombre = data.get('nombre', '').strip()
    telefono = data.get('telefono', '').strip()

    if not nombre:
        return jsonify({'exito': False, 'error': 'El nombre es requerido'}), 400

    # Separar nombre y apellido si es posible
    partes = nombre.split(' ', 1)
    nombre_cliente = partes[0]
    apellido_cliente = partes[1] if len(partes) > 1 else ''

    cliente = Cliente(
        usuario_id=current_user.id,
        nombre=nombre_cliente,
        apellido=apellido_cliente,
        telefono_whatsapp=telefono or None,
        usar_mensaje_estandar=True
    )

    db.session.add(cliente)
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'cliente_creado_rapido',
        f'Cliente creado rapidamente: {cliente.nombre_completo}',
        request
    )

    return jsonify({
        'exito': True,
        'cliente': {
            'id': cliente.id,
            'nombre': cliente.nombre_completo
        }
    })


# =============================================================================
# API V2 - ASIGNACION INTELIGENTE CON EXTRACCION PREDICTIVA
# =============================================================================

@distribucion_bp.route('/api/extraer-pdf-v2/<int:archivo_id>')
@login_required
def api_extraer_datos_pdf_v2(archivo_id):
    """
    API V2: Extrae datos del PDF con formato estructurado y aprendizaje aplicado.

    Retorna JSON con metadata por campo incluyendo:
    - valor: Valor procesado/limpio
    - texto_original: Texto tal como fue extraido del PDF
    - confianza: Nivel de confianza de la extraccion (0-1)
    - fuente: Identificador del patron que lo extrajo

    Tambien incluye clientes sugeridos basados en documento/nombre.
    """
    from app.distribucion.asignacion_service import obtener_servicio_asignacion

    try:
        servicio = obtener_servicio_asignacion(current_user.id)
        datos = servicio.extraer_datos_pdf(archivo_id)

        if 'error' in datos:
            return jsonify({
                'exito': False,
                'error': datos['error']
            }), 404 if 'no encontrado' in datos['error'].lower() else 500

        return jsonify({
            'exito': True,
            'datos': datos,
            'aprendizaje': {
                'correcciones_aplicadas': len(datos.get('aprendizaje_aplicado', [])),
                'patrones_usados': [a.get('transformacion') for a in datos.get('aprendizaje_aplicado', []) if a.get('transformacion')]
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error en api_extraer_datos_pdf_v2: {str(e)}")
        return jsonify({
            'exito': False,
            'error': str(e)
        }), 500


@distribucion_bp.route('/api/guardar-asignacion-v2', methods=['POST'])
@login_required
def api_guardar_asignacion_v2():
    """
    API V2: Guarda cliente y poliza, registra correcciones para aprendizaje.

    Espera JSON con:
    - archivo_id: int
    - crear_cliente: bool
    - cliente_id: int (si no crear_cliente)
    - datos_cliente: dict (si crear_cliente)
    - datos_poliza: dict
    - correcciones: list de correcciones detectadas
    - tiempo_edicion: int (segundos)

    Retorna resultado con IDs creados y cantidad de correcciones registradas.
    """
    from app.distribucion.asignacion_service import obtener_servicio_asignacion

    data = request.get_json()

    if not data:
        return jsonify({
            'exito': False,
            'error': 'Datos JSON requeridos'
        }), 400

    if not data.get('archivo_id'):
        return jsonify({
            'exito': False,
            'error': 'archivo_id es requerido'
        }), 400

    if not data.get('crear_cliente') and not data.get('cliente_id'):
        return jsonify({
            'exito': False,
            'error': 'Debe especificar cliente_id o crear_cliente=true'
        }), 400

    try:
        servicio = obtener_servicio_asignacion(current_user.id)
        resultado = servicio.guardar_asignacion(data)

        if resultado.get('exito'):
            # Registrar actividad
            LogActividad.registrar(
                current_user.id,
                'poliza_asignada_inteligente_v2',
                f'Poliza {resultado.get("poliza_id")} asignada a cliente {resultado.get("cliente_id")} '
                f'({resultado.get("correcciones_registradas", 0)} correcciones registradas)',
                request
            )

        status_code = 200 if resultado.get('exito') else 400
        return jsonify(resultado), status_code

    except Exception as e:
        current_app.logger.error(f"Error en api_guardar_asignacion_v2: {str(e)}")
        return jsonify({
            'exito': False,
            'error': str(e)
        }), 500


@distribucion_bp.route('/api/buscar-cliente-similar')
@login_required
def api_buscar_cliente_similar():
    """
    Busca clientes existentes que coincidan con documento o nombre.

    Query params:
    - documento: DNI/CUIT a buscar
    - nombre: Nombre a buscar (coincidencia fuzzy)
    - limite: Maximo de resultados (default 5)
    """
    from difflib import SequenceMatcher

    documento = request.args.get('documento', '').strip()
    nombre = request.args.get('nombre', '').strip()
    limite = min(int(request.args.get('limite', 5)), 20)

    if not documento and not nombre:
        return jsonify({
            'exito': False,
            'error': 'Debe proporcionar documento o nombre'
        }), 400

    sugeridos = []

    # Buscar por documento
    if documento:
        doc_limpio = ''.join(c for c in documento if c.isdigit())
        if len(doc_limpio) >= 7:
            clientes = Cliente.query.filter(
                Cliente.usuario_id == current_user.id,
                Cliente.activo == True
            ).all()

            for c in clientes:
                if c.documento_identidad:
                    doc_cliente = ''.join(x for x in c.documento_identidad if x.isdigit())
                    if doc_limpio == doc_cliente:
                        sugeridos.append({
                            'id': c.id,
                            'nombre': c.nombre_completo,
                            'documento': c.documento_identidad,
                            'telefono': c.telefono_whatsapp,
                            'email': c.email,
                            'score': 1.0,
                            'razon': 'documento_coincide'
                        })

    # Buscar por nombre si no hay resultados por documento
    if not sugeridos and nombre:
        clientes = Cliente.query.filter(
            Cliente.usuario_id == current_user.id,
            Cliente.activo == True
        ).limit(200).all()

        for c in clientes:
            ratio = SequenceMatcher(None, nombre.upper(), c.nombre_completo.upper()).ratio()
            if ratio > 0.75:
                sugeridos.append({
                    'id': c.id,
                    'nombre': c.nombre_completo,
                    'documento': c.documento_identidad,
                    'telefono': c.telefono_whatsapp,
                    'email': c.email,
                    'score': ratio,
                    'razon': 'nombre_similar'
                })

    # Ordenar y limitar
    sugeridos = sorted(sugeridos, key=lambda x: x['score'], reverse=True)[:limite]

    return jsonify({
        'exito': True,
        'clientes': sugeridos,
        'total': len(sugeridos)
    })


@distribucion_bp.route('/api/estadisticas-aprendizaje')
@login_required
def api_estadisticas_aprendizaje():
    """
    Retorna estadisticas del motor de aprendizaje.

    Incluye:
    - Total de correcciones registradas
    - Campos con mas errores
    - Distribucion por tipo de cambio
    - Distribucion por compania
    """
    from app.extractor.aprendizaje import obtener_estadisticas_aprendizaje

    try:
        stats = obtener_estadisticas_aprendizaje()
        return jsonify({
            'exito': True,
            'estadisticas': stats
        })
    except Exception as e:
        return jsonify({
            'exito': False,
            'error': str(e)
        }), 500


# =============================================================================
# ANÁLISIS DE PDFs - Dashboard de Procesamiento
# =============================================================================

@distribucion_bp.route('/analisis-pdf')
@login_required
def analisis_pdf():
    """Dashboard de análisis y procesamiento de PDFs."""
    from app.models import RegistroAnalisisPDF, ArchivoDescargado, CuentaGmail
    from datetime import date

    # Obtener filtros
    cuenta_id = request.args.get('cuenta', type=int)
    estado = request.args.get('estado', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    solo_vigentes = request.args.get('solo_vigentes', '') == '1'
    ordenar_por = request.args.get('ordenar', 'fecha_correo')  # fecha_correo, vigencia_prox, vigencia_lejana

    # Estadísticas generales
    stats = RegistroAnalisisPDF.obtener_estadisticas()

    # Obtener cuentas para filtro
    cuentas = CuentaGmail.query.filter_by(activa=True).all()

    # Archivos sin registro de análisis (pendientes de inicializar)
    archivos_sin_registro = db.session.query(ArchivoDescargado).outerjoin(
        RegistroAnalisisPDF
    ).filter(RegistroAnalisisPDF.id == None).count()

    # Construir query de registros
    query = RegistroAnalisisPDF.query

    if cuenta_id:
        query = query.filter_by(cuenta_gmail_id=cuenta_id)
    if estado:
        query = query.filter_by(estado=estado)
    if fecha_desde:
        try:
            desde = datetime.strptime(fecha_desde, '%Y-%m-%d')
            query = query.filter(RegistroAnalisisPDF.fecha_correo >= desde)
        except:
            pass
    if fecha_hasta:
        try:
            hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d')
            query = query.filter(RegistroAnalisisPDF.fecha_correo <= hasta)
        except:
            pass

    # Filtro de solo pólizas vigentes (fecha_vigencia_hasta >= hoy)
    if solo_vigentes:
        query = query.filter(
            RegistroAnalisisPDF.fecha_vigencia_hasta_detectada.isnot(None),
            RegistroAnalisisPDF.fecha_vigencia_hasta_detectada >= date.today()
        )

    # Ordenamiento
    if ordenar_por == 'vigencia_prox':
        # Pólizas más próximas a vencer primero (solo las que tienen fecha)
        query = query.order_by(
            db.case((RegistroAnalisisPDF.fecha_vigencia_hasta_detectada.is_(None), 1), else_=0),
            RegistroAnalisisPDF.fecha_vigencia_hasta_detectada.asc()
        )
    elif ordenar_por == 'vigencia_lejana':
        # Pólizas con vigencia más lejana primero
        query = query.order_by(
            db.case((RegistroAnalisisPDF.fecha_vigencia_hasta_detectada.is_(None), 1), else_=0),
            RegistroAnalisisPDF.fecha_vigencia_hasta_detectada.desc()
        )
    else:
        # Por defecto: fecha de correo (más recientes primero)
        query = query.order_by(RegistroAnalisisPDF.fecha_correo.desc())

    registros = query.limit(100).all()

    # Estadísticas por cuenta
    stats_por_cuenta = db.session.query(
        CuentaGmail.correo_gmail,
        db.func.count(RegistroAnalisisPDF.id).label('total'),
        db.func.sum(db.case((RegistroAnalisisPDF.estado == 'procesado', 1), else_=0)).label('procesados'),
        db.func.sum(db.case((RegistroAnalisisPDF.estado == 'pendiente', 1), else_=0)).label('pendientes')
    ).outerjoin(RegistroAnalisisPDF).group_by(CuentaGmail.id).all()

    # Estadísticas de vigencia
    hoy = date.today()
    stats_vigencia = {
        'vigentes': RegistroAnalisisPDF.query.filter(
            RegistroAnalisisPDF.fecha_vigencia_hasta_detectada >= hoy,
            RegistroAnalisisPDF.estado.in_(['analizado', 'pendiente'])
        ).count(),
        'vencidas': RegistroAnalisisPDF.query.filter(
            RegistroAnalisisPDF.fecha_vigencia_hasta_detectada < hoy,
            RegistroAnalisisPDF.estado.in_(['analizado', 'pendiente'])
        ).count(),
        'sin_fecha': RegistroAnalisisPDF.query.filter(
            RegistroAnalisisPDF.fecha_vigencia_hasta_detectada.is_(None),
            RegistroAnalisisPDF.estado.in_(['analizado', 'pendiente'])
        ).count()
    }

    return render_template('distribucion/analisis_pdf.html',
                          stats=stats,
                          cuentas=cuentas,
                          registros=registros,
                          archivos_sin_registro=archivos_sin_registro,
                          stats_por_cuenta=stats_por_cuenta,
                          stats_vigencia=stats_vigencia,
                          today=hoy,
                          filtro_cuenta=cuenta_id,
                          filtro_estado=estado,
                          filtro_fecha_desde=fecha_desde,
                          filtro_fecha_hasta=fecha_hasta,
                          filtro_solo_vigentes=solo_vigentes,
                          filtro_ordenar=ordenar_por)


@distribucion_bp.route('/analisis-pdf/inicializar', methods=['POST'])
@login_required
def inicializar_registros_analisis():
    """Crea registros de análisis para todos los PDFs que no tienen."""
    from app.models import RegistroAnalisisPDF, ArchivoDescargado

    # Obtener archivos sin registro
    archivos = db.session.query(ArchivoDescargado).outerjoin(
        RegistroAnalisisPDF
    ).filter(RegistroAnalisisPDF.id == None).all()

    creados = 0
    for archivo in archivos:
        registro = RegistroAnalisisPDF.obtener_o_crear(archivo.id)
        if registro:
            creados += 1

    db.session.commit()

    flash(f'Se inicializaron {creados} registros de análisis.', 'success')
    return redirect(url_for('distribucion.analisis_pdf'))


@distribucion_bp.route('/analisis-pdf/procesar/<int:archivo_id>')
@login_required
def procesar_pdf(archivo_id):
    """Muestra la interfaz para procesar un PDF individual."""
    from app.models import RegistroAnalisisPDF, ArchivoDescargado, Cliente
    from app.extractor.pdf_parser import ExtractorDatosPoliza
    import json

    archivo = ArchivoDescargado.query.get_or_404(archivo_id)
    registro = RegistroAnalisisPDF.obtener_o_crear(archivo_id)

    # Extraer datos del PDF
    datos_extraidos = {}
    resumen = {}
    error_extraccion = None

    try:
        if os.path.exists(archivo.ruta_archivo):
            extractor = ExtractorDatosPoliza()
            datos_extraidos = extractor.extraer_datos(archivo.ruta_archivo)
            resumen = extractor.resumen_extraccion()

            # Actualizar registro con datos extraídos
            registro.marcar_analizado(
                datos_json=json.dumps(datos_extraidos, default=str, ensure_ascii=False),
                confianza=resumen.get('confianza', 0),
                compania=resumen.get('compania'),
                tipo_seguro=resumen.get('tipo_seguro'),
                numero_poliza=datos_extraidos.get('numero_poliza'),
                fecha_vigencia_desde=datos_extraidos.get('fecha_vigencia_desde'),
                fecha_vigencia_hasta=datos_extraidos.get('fecha_vigencia_hasta'),
                asegurado=datos_extraidos.get('asegurado_nombre')
            )
            db.session.commit()
        else:
            error_extraccion = 'Archivo no encontrado en disco'
    except Exception as e:
        error_extraccion = str(e)
        registro.marcar_error(notas=error_extraccion)
        db.session.commit()

    # Obtener clientes para selector
    clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()

    # Obtener siguiente archivo pendiente
    siguiente = RegistroAnalisisPDF.query.filter(
        RegistroAnalisisPDF.estado == 'pendiente',
        RegistroAnalisisPDF.archivo_id != archivo_id
    ).first()

    return render_template('distribucion/procesar_pdf.html',
                          archivo=archivo,
                          registro=registro,
                          datos_extraidos=datos_extraidos,
                          resumen=resumen,
                          error_extraccion=error_extraccion,
                          clientes=clientes,
                          siguiente_id=siguiente.archivo_id if siguiente else None)


@distribucion_bp.route('/analisis-pdf/guardar/<int:archivo_id>', methods=['POST'])
@login_required
def guardar_analisis_pdf(archivo_id):
    """Guarda el resultado del análisis (crea cliente/póliza o marca como omitido)."""
    from app.models import RegistroAnalisisPDF, ArchivoDescargado, Cliente, PolizaCliente
    import json

    archivo = ArchivoDescargado.query.get_or_404(archivo_id)
    registro = RegistroAnalisisPDF.obtener_o_crear(archivo_id)

    accion = request.form.get('accion')
    continuar = request.form.get('continuar') == '1'

    if accion == 'omitir':
        motivo = request.form.get('motivo_omision', 'Sin especificar')
        registro.marcar_omitido(motivo=motivo, usuario_id=current_user.id)
        db.session.commit()
        flash('PDF marcado como omitido.', 'info')

    elif accion == 'procesar':
        cliente_id = request.form.get('cliente_id', type=int)
        crear_cliente = request.form.get('crear_cliente') == '1'
        cliente_nuevo = False

        # Crear cliente nuevo si se solicitó
        if crear_cliente:
            nuevo_cliente = Cliente(
                usuario_id=current_user.id,
                nombre=request.form.get('cliente_nombre', 'Sin nombre'),
                apellido=request.form.get('cliente_apellido', ''),
                telefono_whatsapp=request.form.get('cliente_telefono', ''),
                email=request.form.get('cliente_email', ''),
                documento_identidad=request.form.get('cliente_documento', ''),
            )
            db.session.add(nuevo_cliente)
            db.session.flush()
            cliente_id = nuevo_cliente.id
            cliente_nuevo = True

        if not cliente_id:
            flash('Debe seleccionar o crear un cliente.', 'danger')
            return redirect(url_for('distribucion.procesar_pdf', archivo_id=archivo_id))

        # Crear póliza
        poliza = PolizaCliente(
            cliente_id=cliente_id,
            archivo_id=archivo.id,
            numero_poliza=request.form.get('numero_poliza', ''),
            tipo_seguro=request.form.get('tipo_seguro', 'otro'),
            fecha_vigencia_desde=datetime.strptime(request.form.get('fecha_desde'), '%Y-%m-%d').date() if request.form.get('fecha_desde') else None,
            fecha_vigencia_hasta=datetime.strptime(request.form.get('fecha_hasta'), '%Y-%m-%d').date() if request.form.get('fecha_hasta') else None,
            prima_anual=request.form.get('prima', type=float),
            asegurado_nombre=request.form.get('asegurado_nombre', ''),
            asegurado_documento=request.form.get('asegurado_documento', ''),
            vehiculo_marca=request.form.get('vehiculo_marca', ''),
            vehiculo_modelo=request.form.get('vehiculo_modelo', ''),
            vehiculo_patente=request.form.get('vehiculo_patente', ''),
            vehiculo_anio=request.form.get('vehiculo_anio', type=int),
            estado='vigente',
            datos_extraidos=registro.datos_extraidos,
            confianza_extraccion=registro.confianza_extraccion,
            fecha_extraccion=datetime.utcnow()
        )
        db.session.add(poliza)
        db.session.flush()

        # Actualizar registro
        registro.marcar_procesado(
            cliente_id=cliente_id,
            poliza_id=poliza.id,
            cliente_nuevo=cliente_nuevo,
            poliza_nueva=True,
            usuario_id=current_user.id
        )
        db.session.commit()

        LogActividad.registrar(
            current_user.id,
            'analisis_pdf_procesado',
            f'PDF {archivo.id_documento} procesado. Cliente: {cliente_id}, Póliza: {poliza.id}',
            request
        )

        if cliente_nuevo:
            flash(f'Cliente "{nuevo_cliente.nombre_completo}" creado exitosamente.', 'success')
        flash(f'Póliza creada exitosamente (ID: {poliza.id}).', 'success')

    # Redirigir
    if continuar:
        siguiente = RegistroAnalisisPDF.query.filter(
            RegistroAnalisisPDF.estado == 'pendiente',
            RegistroAnalisisPDF.archivo_id != archivo_id
        ).first()
        if siguiente:
            return redirect(url_for('distribucion.procesar_pdf', archivo_id=siguiente.archivo_id))
        else:
            flash('No hay más PDFs pendientes.', 'info')

    return redirect(url_for('distribucion.analisis_pdf'))


@distribucion_bp.route('/analisis-pdf/lote', methods=['POST'])
@login_required
def analisis_lote():
    """Inicia el análisis en lote y retorna task_id para seguimiento SSE."""
    task_id = str(uuid.uuid4())

    # Inicializar estado de progreso
    with _progreso_lock:
        _progreso_analisis[task_id] = {
            'status': 'iniciando',
            'total': 0,
            'procesados': 0,
            'errores': 0,
            'actual': None,
            'log': [],
            'finalizado': False
        }

    # Iniciar procesamiento en hilo separado
    from flask import current_app
    app = current_app._get_current_object()

    thread = threading.Thread(
        target=_ejecutar_analisis_lote,
        args=(app, task_id)
    )
    thread.daemon = True
    thread.start()

    # Retornar página con progreso
    return render_template('distribucion/analisis_pdf_progreso.html', task_id=task_id)


def _commit_con_reintentos(max_intentos=5):
    """Intenta commit con reintentos para manejar bloqueo de SQLite."""
    for intento in range(max_intentos):
        try:
            db.session.commit()
            return True
        except Exception as e:
            if 'database is locked' in str(e).lower() and intento < max_intentos - 1:
                db.session.rollback()
                time.sleep(0.5 * (intento + 1))  # Espera incremental
            else:
                raise
    return False


def _ejecutar_analisis_lote(app, task_id):
    """Ejecuta el análisis en lote en background, actualizando progreso."""
    from app.models import RegistroAnalisisPDF
    from app.extractor.pdf_parser import ExtractorDatosPoliza

    with app.app_context():
        # Limpiar sesión para evitar conflictos
        db.session.remove()

        try:
            # Obtener IDs de archivos pendientes (solo IDs para evitar objetos detached)
            pendientes_ids = [r.id for r in RegistroAnalisisPDF.query.filter_by(
                estado='pendiente'
            ).limit(50).all()]
            total = len(pendientes_ids)

            with _progreso_lock:
                _progreso_analisis[task_id]['total'] = total
                _progreso_analisis[task_id]['status'] = 'procesando'
                if total == 0:
                    _progreso_analisis[task_id]['log'].append({
                        'tipo': 'info',
                        'mensaje': 'No hay PDFs pendientes para analizar'
                    })
                    _progreso_analisis[task_id]['finalizado'] = True
                    return

            analizados = 0
            errores = 0

            for i, registro_id in enumerate(pendientes_ids):
                # Re-consultar el registro en cada iteración para evitar objetos detached
                registro = RegistroAnalisisPDF.query.get(registro_id)
                if not registro:
                    continue

                archivo = registro.archivo
                nombre_archivo = archivo.nombre_archivo if archivo else f'Registro {registro.id}'

                # Actualizar archivo actual
                with _progreso_lock:
                    _progreso_analisis[task_id]['actual'] = {
                        'indice': i + 1,
                        'nombre': nombre_archivo[:50],
                        'id': registro.archivo_id
                    }

                try:
                    if archivo and os.path.exists(archivo.ruta_archivo):
                        extractor = ExtractorDatosPoliza()
                        datos = extractor.extraer_datos(archivo.ruta_archivo)
                        resumen = extractor.resumen_extraccion()

                        registro.marcar_analizado(
                            datos_json=json.dumps(datos, default=str, ensure_ascii=False),
                            confianza=resumen.get('confianza', 0),
                            compania=resumen.get('compania'),
                            tipo_seguro=resumen.get('tipo_seguro'),
                            numero_poliza=datos.get('numero_poliza'),
                            fecha_vigencia_desde=datos.get('fecha_vigencia_desde'),
                            fecha_vigencia_hasta=datos.get('fecha_vigencia_hasta'),
                            asegurado=datos.get('asegurado_nombre')
                        )

                        _commit_con_reintentos()
                        analizados += 1

                        with _progreso_lock:
                            _progreso_analisis[task_id]['procesados'] = analizados
                            _progreso_analisis[task_id]['log'].append({
                                'tipo': 'exito',
                                'mensaje': f'{nombre_archivo[:40]} - {resumen.get("compania", "?")} ({int(resumen.get("confianza", 0)*100)}%)'
                            })
                    else:
                        registro.marcar_error('Archivo no encontrado')
                        _commit_con_reintentos()
                        errores += 1
                        with _progreso_lock:
                            _progreso_analisis[task_id]['errores'] = errores
                            _progreso_analisis[task_id]['log'].append({
                                'tipo': 'error',
                                'mensaje': f'{nombre_archivo[:40]} - Archivo no encontrado'
                            })
                except Exception as e:
                    db.session.rollback()
                    try:
                        registro = RegistroAnalisisPDF.query.get(registro_id)
                        if registro:
                            registro.marcar_error(str(e)[:200])
                            _commit_con_reintentos()
                    except:
                        pass
                    errores += 1
                    with _progreso_lock:
                        _progreso_analisis[task_id]['errores'] = errores
                        _progreso_analisis[task_id]['log'].append({
                            'tipo': 'error',
                            'mensaje': f'{nombre_archivo[:40]} - {str(e)[:50]}'
                        })

                # Pequeña pausa entre archivos para reducir contención
                time.sleep(0.1)

            # Marcar como finalizado
            with _progreso_lock:
                _progreso_analisis[task_id]['status'] = 'completado'
                _progreso_analisis[task_id]['finalizado'] = True
                _progreso_analisis[task_id]['log'].append({
                    'tipo': 'info',
                    'mensaje': f'Completado: {analizados} analizados, {errores} errores'
                })

        except Exception as e:
            db.session.rollback()
            with _progreso_lock:
                _progreso_analisis[task_id]['status'] = 'error'
                _progreso_analisis[task_id]['finalizado'] = True
                _progreso_analisis[task_id]['log'].append({
                    'tipo': 'error',
                    'mensaje': f'Error general: {str(e)[:100]}'
                })
        finally:
            db.session.remove()


@distribucion_bp.route('/analisis-pdf/progreso/<task_id>')
@login_required
def analisis_progreso_stream(task_id):
    """Stream SSE del progreso del análisis en lote."""

    def generar_eventos():
        ultimo_log_idx = 0

        while True:
            with _progreso_lock:
                progreso = _progreso_analisis.get(task_id)

            if not progreso:
                yield f"data: {json.dumps({'error': 'Tarea no encontrada'})}\n\n"
                break

            # Preparar datos para enviar
            nuevos_logs = progreso['log'][ultimo_log_idx:]
            ultimo_log_idx = len(progreso['log'])

            evento = {
                'status': progreso['status'],
                'total': progreso['total'],
                'procesados': progreso['procesados'],
                'errores': progreso['errores'],
                'actual': progreso['actual'],
                'nuevos_logs': nuevos_logs,
                'finalizado': progreso['finalizado']
            }

            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"

            if progreso['finalizado']:
                # Limpiar progreso después de un delay
                time.sleep(1)
                with _progreso_lock:
                    if task_id in _progreso_analisis:
                        del _progreso_analisis[task_id]
                break

            time.sleep(0.5)  # Actualizar cada 500ms

    return Response(
        generar_eventos(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


# ============================================================================
# GESTIÓN DE INMOBILIARIAS
# ============================================================================

@distribucion_bp.route('/inmobiliarias')
@login_required
def inmobiliarias():
    """Listado de inmobiliarias."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    busqueda = request.args.get('busqueda', '')
    solo_activas = request.args.get('solo_activas', '1') == '1'

    query = Inmobiliaria.query.filter_by(usuario_id=current_user.id)

    if solo_activas:
        query = query.filter_by(activa=True)

    if busqueda:
        query = query.filter(
            db.or_(
                Inmobiliaria.nombre.ilike(f'%{busqueda}%'),
                Inmobiliaria.email.ilike(f'%{busqueda}%'),
                Inmobiliaria.persona_contacto.ilike(f'%{busqueda}%')
            )
        )

    inmobiliarias_lista = query.order_by(Inmobiliaria.nombre).all()

    return render_template('distribucion/inmobiliarias/lista.html',
                          inmobiliarias=inmobiliarias_lista,
                          busqueda=busqueda,
                          solo_activas=solo_activas)


@distribucion_bp.route('/inmobiliarias/nueva', methods=['GET', 'POST'])
@login_required
def nueva_inmobiliaria():
    """Crear nueva inmobiliaria."""
    form = InmobiliariaForm()

    if form.validate_on_submit():
        inmobiliaria = Inmobiliaria(
            usuario_id=current_user.id,
            nombre=form.nombre.data,
            telefono_whatsapp=form.telefono_whatsapp.data,
            email=form.email.data,
            persona_contacto=form.persona_contacto.data,
            notas=form.notas.data
        )
        db.session.add(inmobiliaria)
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'inmobiliaria_creada',
            f'Inmobiliaria creada: {inmobiliaria.nombre}',
            request
        )

        flash('Inmobiliaria creada correctamente.', 'success')
        return redirect(url_for('distribucion.inmobiliaria_detalle', inmobiliaria_id=inmobiliaria.id))

    return render_template('distribucion/inmobiliarias/form.html',
                          form=form,
                          titulo='Nueva Inmobiliaria')


@distribucion_bp.route('/inmobiliarias/<int:inmobiliaria_id>')
@login_required
def inmobiliaria_detalle(inmobiliaria_id):
    """Detalle de una inmobiliaria."""
    inmobiliaria = Inmobiliaria.query.filter_by(
        id=inmobiliaria_id,
        usuario_id=current_user.id
    ).first_or_404()

    # Pólizas asignadas a esta inmobiliaria
    polizas = PolizaCliente.query.filter_by(inmobiliaria_id=inmobiliaria.id).order_by(
        PolizaCliente.fecha_vigencia_hasta.desc()
    ).all()

    # Notificaciones recientes
    notificaciones = NotificacionInmobiliaria.query.filter_by(
        inmobiliaria_id=inmobiliaria.id
    ).order_by(NotificacionInmobiliaria.fecha_creacion.desc()).limit(20).all()

    # Estadísticas
    polizas_activas = sum(1 for p in polizas if p.estado == 'activa')
    polizas_por_vencer = sum(1 for p in polizas if p.estado == 'activa' and p.esta_por_vencer(30))

    return render_template('distribucion/inmobiliarias/detalle.html',
                          inmobiliaria=inmobiliaria,
                          polizas=polizas,
                          notificaciones=notificaciones,
                          polizas_activas=polizas_activas,
                          polizas_por_vencer=polizas_por_vencer)


@distribucion_bp.route('/inmobiliarias/<int:inmobiliaria_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_inmobiliaria(inmobiliaria_id):
    """Editar inmobiliaria."""
    inmobiliaria = Inmobiliaria.query.filter_by(
        id=inmobiliaria_id,
        usuario_id=current_user.id
    ).first_or_404()

    form = InmobiliariaForm(obj=inmobiliaria)

    if form.validate_on_submit():
        inmobiliaria.nombre = form.nombre.data
        inmobiliaria.telefono_whatsapp = form.telefono_whatsapp.data
        inmobiliaria.email = form.email.data
        inmobiliaria.persona_contacto = form.persona_contacto.data
        inmobiliaria.notas = form.notas.data

        db.session.commit()

        flash('Inmobiliaria actualizada correctamente.', 'success')
        return redirect(url_for('distribucion.inmobiliaria_detalle', inmobiliaria_id=inmobiliaria.id))

    return render_template('distribucion/inmobiliarias/form.html',
                          form=form,
                          titulo='Editar Inmobiliaria',
                          inmobiliaria=inmobiliaria)


@distribucion_bp.route('/inmobiliarias/<int:inmobiliaria_id>/eliminar', methods=['POST'])
@login_required
def eliminar_inmobiliaria(inmobiliaria_id):
    """Desactivar inmobiliaria."""
    inmobiliaria = Inmobiliaria.query.filter_by(
        id=inmobiliaria_id,
        usuario_id=current_user.id
    ).first_or_404()

    inmobiliaria.activa = False
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'inmobiliaria_eliminada',
        f'Inmobiliaria desactivada: {inmobiliaria.nombre}',
        request
    )

    flash('Inmobiliaria desactivada correctamente.', 'success')
    return redirect(url_for('distribucion.inmobiliarias'))


@distribucion_bp.route('/poliza/<int:poliza_id>/asignar-inmobiliaria', methods=['POST'])
@login_required
def asignar_inmobiliaria_poliza(poliza_id):
    """Asigna o cambia la inmobiliaria de una póliza."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    # Solo permitir para pólizas de incendio y hogar
    if poliza.tipo_seguro not in ('incendio', 'hogar'):
        flash('Solo se puede asignar inmobiliaria a pólizas de tipo Incendio o Hogar.', 'warning')
        return redirect(request.referrer or url_for('distribucion.poliza_completa', poliza_id=poliza_id))

    inmobiliaria_id = request.form.get('inmobiliaria_id', type=int)

    if inmobiliaria_id:
        # Verificar que la inmobiliaria pertenece al usuario
        inmobiliaria = Inmobiliaria.query.filter_by(
            id=inmobiliaria_id,
            usuario_id=current_user.id
        ).first()

        if not inmobiliaria:
            flash('Inmobiliaria no válida.', 'danger')
            return redirect(request.referrer or url_for('distribucion.poliza_completa', poliza_id=poliza_id))

        poliza.inmobiliaria_id = inmobiliaria.id
        flash(f'Póliza asignada a {inmobiliaria.nombre}.', 'success')
    else:
        poliza.inmobiliaria_id = None
        flash('Inmobiliaria removida de la póliza.', 'info')

    db.session.commit()

    return redirect(request.referrer or url_for('distribucion.poliza_completa', poliza_id=poliza_id))


@distribucion_bp.route('/api/inmobiliarias')
@login_required
def api_inmobiliarias():
    """API que devuelve lista de inmobiliarias para selectores."""
    inmobiliarias_lista = Inmobiliaria.query.filter_by(
        usuario_id=current_user.id,
        activa=True
    ).order_by(Inmobiliaria.nombre).all()

    return jsonify([{
        'id': i.id,
        'nombre': i.nombre,
        'telefono': i.telefono_whatsapp,
        'email': i.email
    } for i in inmobiliarias_lista])


# ============================================================================
# ACCESO A PDFs DE POLIZAS (BACKUP)
# ============================================================================

@distribucion_bp.route('/poliza/<int:poliza_id>/pdf')
@login_required
def ver_pdf_poliza(poliza_id):
    """Devuelve el PDF de una poliza (backup o archivo original)."""
    from flask import send_file
    from app.distribucion.backup_polizas import obtener_pdf_poliza

    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    ruta_pdf, es_backup = obtener_pdf_poliza(poliza)

    if not ruta_pdf:
        flash('No se encontro el PDF de esta poliza.', 'warning')
        return redirect(request.referrer or url_for('distribucion.cliente_detalle', cliente_id=poliza.cliente_id))

    nombre_descarga = f"poliza_{poliza.numero_poliza or poliza.id}.pdf"
    return send_file(ruta_pdf, mimetype='application/pdf', download_name=nombre_descarga)


@distribucion_bp.route('/poliza/<int:poliza_id>/crear-backup', methods=['POST'])
@login_required
def crear_backup_poliza_manual(poliza_id):
    """Crea backup del PDF de una poliza manualmente."""
    from app.distribucion.backup_polizas import crear_backup_poliza

    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    if poliza.ruta_pdf_backup and os.path.exists(poliza.ruta_pdf_backup):
        flash('Esta poliza ya tiene un backup.', 'info')
    elif not poliza.archivo:
        flash('Esta poliza no tiene archivo PDF asociado.', 'warning')
    else:
        resultado = crear_backup_poliza(poliza)
        if resultado:
            flash('Backup creado correctamente.', 'success')
        else:
            flash('No se pudo crear el backup.', 'danger')

    return redirect(request.referrer or url_for('distribucion.cliente_detalle', cliente_id=poliza.cliente_id))


@distribucion_bp.route('/backups')
@login_required
def estadisticas_backup():
    """Muestra estadisticas de backups y permite crear backups pendientes."""
    from app.distribucion.backup_polizas import obtener_estadisticas_backup

    stats = obtener_estadisticas_backup(current_user.id)

    # Polizas sin backup pero con archivo
    polizas_sin_backup = PolizaCliente.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        PolizaCliente.archivo_id.isnot(None),
        PolizaCliente.ruta_pdf_backup.is_(None)
    ).all()

    return render_template('distribucion/backups.html',
                          stats=stats,
                          polizas_sin_backup=polizas_sin_backup)


@distribucion_bp.route('/backups/crear-todos', methods=['POST'])
@login_required
def crear_backups_todos():
    """Crea backups para todas las polizas pendientes."""
    from app.distribucion.backup_polizas import crear_backups_pendientes

    creados, errores = crear_backups_pendientes(current_user.id)

    if creados > 0:
        flash(f'Se crearon {creados} backup(s) correctamente.', 'success')
    if errores > 0:
        flash(f'{errores} poliza(s) no pudieron respaldarse.', 'warning')
    if creados == 0 and errores == 0:
        flash('No hay polizas pendientes de backup.', 'info')

    return redirect(url_for('distribucion.estadisticas_backup'))


# ============================================================================
# CONFIRMACIÓN DE ENVÍOS (MANUAL)
# ============================================================================

@distribucion_bp.route('/poliza/<int:poliza_id>/confirmar', methods=['POST'])
@login_required
def confirmar_poliza(poliza_id):
    """Marca una póliza como definitiva/confirmada manualmente."""
    poliza = PolizaCliente.query.join(Cliente).filter(
        PolizaCliente.id == poliza_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    poliza.marcar_definitivo('manual')

    # También marcar el archivo si existe
    if poliza.archivo:
        poliza.archivo.estado_confirmacion = 'definitivo'
        poliza.archivo.fecha_confirmacion = datetime.utcnow()
        poliza.archivo.confirmado_por = 'manual'

    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'poliza_confirmada',
        f'Póliza {poliza.numero_poliza or poliza.id} marcada como definitiva',
        request
    )

    flash('Póliza marcada como definitiva.', 'success')
    return redirect(request.referrer or url_for('distribucion.cliente_detalle', cliente_id=poliza.cliente_id))


@distribucion_bp.route('/envio/<int:envio_id>/confirmar', methods=['POST'])
@login_required
def confirmar_envio(envio_id):
    """Marca un envío como leído/confirmado manualmente."""
    envio = EnvioWhatsApp.query.join(Cliente).filter(
        EnvioWhatsApp.id == envio_id,
        Cliente.usuario_id == current_user.id
    ).first_or_404()

    envio.actualizar_estado_mensaje('read', datetime.utcnow())
    db.session.commit()

    LogActividad.registrar(
        current_user.id, 'envio_confirmado',
        f'Envío a {envio.cliente.nombre_completo} marcado como leído',
        request
    )

    flash('Envío marcado como leído. Póliza confirmada.', 'success')
    return redirect(request.referrer or url_for('distribucion.historial_envios'))


@distribucion_bp.route('/api/envios/pendientes-confirmacion')
@login_required
def envios_pendientes_confirmacion():
    """API: Obtiene envíos enviados pero sin confirmación de lectura."""
    envios = EnvioWhatsApp.query.join(Cliente).filter(
        Cliente.usuario_id == current_user.id,
        EnvioWhatsApp.estado == 'enviado',
        db.or_(
            EnvioWhatsApp.estado_mensaje.is_(None),
            EnvioWhatsApp.estado_mensaje.in_(['sent', 'delivered'])
        )
    ).order_by(EnvioWhatsApp.fecha_envio.desc()).limit(50).all()

    return jsonify([{
        'id': e.id,
        'cliente': e.cliente.nombre_completo,
        'telefono': e.cliente.telefono_whatsapp,
        'fecha_envio': e.fecha_envio.isoformat() if e.fecha_envio else None,
        'estado_mensaje': e.estado_mensaje or 'enviado',
        'poliza_numero': e.poliza.numero_poliza if e.poliza else None
    } for e in envios])


# ============================================================================
# CONFIGURACIÓN DE WHATSAPP WEB (Sesiones personales por usuario)
# ============================================================================

@distribucion_bp.route('/whatsapp/configurar')
@login_required
def whatsapp_configurar():
    """Página de configuración de WhatsApp Web personal."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    # Obtener o crear sesión del usuario
    session = WhatsAppSession.obtener_o_crear(current_user.id)

    # Sincronizar estado con el servicio
    sincronizar_sesion_whatsapp(current_user.id)

    # Recargar sesión después de sincronizar
    session = WhatsAppSession.query.filter_by(usuario_id=current_user.id).first()

    return render_template('distribucion/whatsapp_config.html', session=session)


@distribucion_bp.route('/whatsapp/conectar', methods=['POST'])
@login_required
def whatsapp_conectar():
    """Inicia el proceso de conexión de WhatsApp."""
    try:
        service_url = current_app.config.get('WHATSAPP_SERVICE_URL', 'http://localhost:3001')
        timeout = current_app.config.get('WHATSAPP_SERVICE_TIMEOUT', 30)

        response = requests.post(
            f"{service_url}/session/{current_user.id}/start",
            timeout=timeout
        )

        if response.status_code == 200:
            data = response.json()

            # Actualizar estado en BD
            session = WhatsAppSession.obtener_o_crear(current_user.id)
            session.estado = data.get('status', 'qr_pending')
            session.mensaje_error = None
            db.session.commit()

            return jsonify(data)
        else:
            return jsonify({
                'success': False,
                'error': 'Error conectando con el servicio de WhatsApp'
            }), 500

    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'error': 'El servicio de WhatsApp no está disponible. Verifique que esté ejecutándose.'
        }), 503
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@distribucion_bp.route('/whatsapp/qr')
@login_required
def whatsapp_qr():
    """Obtiene el código QR actual para el usuario."""
    try:
        service_url = current_app.config.get('WHATSAPP_SERVICE_URL', 'http://localhost:3001')

        response = requests.get(
            f"{service_url}/session/{current_user.id}/qr",
            timeout=10
        )

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({'success': False, 'message': 'QR no disponible'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@distribucion_bp.route('/whatsapp/estado')
@login_required
def whatsapp_estado():
    """Obtiene el estado actual de la sesión de WhatsApp."""
    try:
        service_url = current_app.config.get('WHATSAPP_SERVICE_URL', 'http://localhost:3001')

        response = requests.get(
            f"{service_url}/session/{current_user.id}/status",
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()

            # Actualizar estado en BD si cambió
            if data.get('success'):
                session = WhatsAppSession.obtener_o_crear(current_user.id)
                nuevo_estado = data.get('status', 'disconnected')

                if nuevo_estado != session.estado:
                    session.estado = nuevo_estado
                    if nuevo_estado == 'ready':
                        session.telefono_conectado = data.get('phone')
                        session.fecha_conexion = datetime.utcnow()
                    elif nuevo_estado == 'disconnected':
                        session.fecha_desconexion = datetime.utcnow()
                    db.session.commit()

            return jsonify(data)
        else:
            return jsonify({'success': False, 'status': 'disconnected'})

    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'status': 'service_unavailable',
            'error': 'Servicio no disponible'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@distribucion_bp.route('/whatsapp/desconectar', methods=['POST'])
@login_required
def whatsapp_desconectar():
    """Cierra la sesión de WhatsApp del usuario."""
    try:
        service_url = current_app.config.get('WHATSAPP_SERVICE_URL', 'http://localhost:3001')

        response = requests.post(
            f"{service_url}/session/{current_user.id}/disconnect",
            timeout=30
        )

        # Actualizar estado en BD
        session = WhatsAppSession.obtener_o_crear(current_user.id)
        session.marcar_desconectado()
        db.session.commit()

        if response.status_code == 200:
            flash('WhatsApp desconectado correctamente', 'success')
            return jsonify({'success': True, 'message': 'Sesión cerrada'})
        else:
            return jsonify({'success': True, 'message': 'Sesión cerrada localmente'})

    except Exception as e:
        # Igual marcar como desconectado localmente
        session = WhatsAppSession.obtener_o_crear(current_user.id)
        session.marcar_desconectado()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Sesión cerrada localmente'})


@distribucion_bp.route('/whatsapp/webhook', methods=['POST'])
def whatsapp_webhook():
    """
    Webhook para recibir notificaciones de cambio de estado desde el servicio WhatsApp.
    El servicio Node.js llama a este endpoint cuando cambia el estado de una sesión.
    """
    try:
        data = request.get_json()
        usuario_id = data.get('userId')
        nuevo_estado = data.get('status')
        telefono = data.get('phone')

        if not usuario_id:
            return jsonify({'success': False, 'error': 'userId requerido'}), 400

        session = WhatsAppSession.query.filter_by(usuario_id=usuario_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Sesión no encontrada'}), 404

        # Actualizar estado
        if nuevo_estado:
            session.estado = nuevo_estado

            if nuevo_estado == 'ready':
                session.telefono_conectado = telefono
                session.fecha_conexion = datetime.utcnow()
                session.mensaje_error = None
            elif nuevo_estado == 'disconnected':
                session.fecha_desconexion = datetime.utcnow()
            elif nuevo_estado == 'error':
                session.mensaje_error = data.get('error')

            db.session.commit()

        return jsonify({'success': True, 'message': 'Estado actualizado'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
