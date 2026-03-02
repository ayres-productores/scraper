"""
Rutas del módulo Representante.

Vista especializada para el rol collaborator que permite ver
todas las pólizas del sistema y gestionar el contacto con clientes.
"""

from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, func

from app import db
from app.representante import representante_bp
from app.models import (
    PolizaCliente, Cliente, ArchivoDescargado, Escaneo, Compania,
    EnvioWhatsApp, PlantillaMensaje, LogActividad, Usuario, WhatsAppSession
)
from app.utils.decoradores import collaborator_requerido
from app.distribucion.whatsapp_sender import WhatsAppSender


@representante_bp.route('/')
@login_required
@collaborator_requerido
def index():
    """Dashboard del representante con todas las pólizas del sistema."""
    # Parámetros de filtro
    busqueda = request.args.get('q', '').strip()
    compania_id = request.args.get('compania', type=int)
    estado = request.args.get('estado', '')
    tipo_seguro = request.args.get('tipo', '')
    descargado_por = request.args.get('usuario', type=int)
    cuenta_gmail = request.args.get('cuenta', '')
    fecha_descarga_desde = request.args.get('fecha_desde', '')
    fecha_descarga_hasta = request.args.get('fecha_hasta', '')
    solo_sin_envio = request.args.get('sin_envio', '') == '1'
    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 25

    # Query base con joins para obtener info de descarga
    query = PolizaCliente.query.options(
        joinedload(PolizaCliente.cliente),
        joinedload(PolizaCliente.compania),
        joinedload(PolizaCliente.archivo).joinedload(ArchivoDescargado.escaneo).joinedload(Escaneo.usuario)
    )

    # Aplicar filtros
    if busqueda:
        query = query.join(PolizaCliente.cliente).filter(
            or_(
                PolizaCliente.numero_poliza.ilike(f'%{busqueda}%'),
                Cliente.nombre.ilike(f'%{busqueda}%'),
                Cliente.apellido.ilike(f'%{busqueda}%'),
                PolizaCliente.vehiculo_patente.ilike(f'%{busqueda}%'),
                PolizaCliente.asegurado_documento.ilike(f'%{busqueda}%')
            )
        )

    if compania_id:
        query = query.filter(PolizaCliente.compania_id == compania_id)

    if estado:
        query = query.filter(PolizaCliente.estado == estado)

    if tipo_seguro:
        query = query.filter(PolizaCliente.tipo_seguro == tipo_seguro)

    if descargado_por:
        query = query.join(PolizaCliente.archivo).join(ArchivoDescargado.escaneo).filter(
            Escaneo.usuario_id == descargado_por
        )

    if cuenta_gmail:
        query = query.join(PolizaCliente.archivo).filter(
            ArchivoDescargado.cuenta_origen == cuenta_gmail
        )

    if fecha_descarga_desde:
        try:
            fecha_desde = datetime.strptime(fecha_descarga_desde, '%Y-%m-%d')
            query = query.join(PolizaCliente.archivo).filter(
                ArchivoDescargado.fecha_descarga >= fecha_desde
            )
        except ValueError:
            pass

    if fecha_descarga_hasta:
        try:
            fecha_hasta = datetime.strptime(fecha_descarga_hasta, '%Y-%m-%d')
            fecha_hasta = fecha_hasta + timedelta(days=1)  # Incluir todo el día
            query = query.join(PolizaCliente.archivo).filter(
                ArchivoDescargado.fecha_descarga < fecha_hasta
            )
        except ValueError:
            pass

    if solo_sin_envio:
        # Subquery para pólizas con envíos
        polizas_con_envio = db.session.query(EnvioWhatsApp.poliza_cliente_id).distinct()
        query = query.filter(~PolizaCliente.id.in_(polizas_con_envio))

    # Ordenar por fecha de asignación descendente
    query = query.order_by(PolizaCliente.fecha_asignacion.desc())

    # Paginación
    paginacion = query.paginate(page=pagina, per_page=por_pagina, error_out=False)
    polizas = paginacion.items

    # Estadísticas
    hoy = datetime.now().date()
    en_30_dias = hoy + timedelta(days=30)

    stats = {
        'total': PolizaCliente.query.count(),
        'activas': PolizaCliente.query.filter_by(estado='activa').count(),
        'por_vencer': PolizaCliente.query.filter(
            PolizaCliente.estado == 'activa',
            PolizaCliente.fecha_vigencia_hasta.between(hoy, en_30_dias)
        ).count(),
        'vencidas': PolizaCliente.query.filter_by(estado='vencida').count(),
        'sin_contactar': PolizaCliente.query.filter(
            ~PolizaCliente.id.in_(
                db.session.query(EnvioWhatsApp.poliza_cliente_id).distinct()
            )
        ).count()
    }

    # Opciones para filtros
    companias = Compania.query.order_by(Compania.nombre).all()
    usuarios = Usuario.query.filter(Usuario.activo == True).order_by(Usuario.nombre).all()
    cuentas = db.session.query(ArchivoDescargado.cuenta_origen).distinct().all()
    cuentas = [c[0] for c in cuentas if c[0]]

    tipos_seguro = db.session.query(PolizaCliente.tipo_seguro).distinct().all()
    tipos_seguro = [t[0] for t in tipos_seguro if t[0]]

    # Estado de sesión WhatsApp del usuario actual
    sesion_whatsapp = WhatsAppSession.query.filter_by(usuario_id=current_user.id).first()

    return render_template('representante/dashboard.html',
                           polizas=polizas,
                           paginacion=paginacion,
                           stats=stats,
                           companias=companias,
                           usuarios=usuarios,
                           cuentas=cuentas,
                           tipos_seguro=tipos_seguro,
                           sesion_whatsapp=sesion_whatsapp,
                           filtros={
                               'q': busqueda,
                               'compania': compania_id,
                               'estado': estado,
                               'tipo': tipo_seguro,
                               'usuario': descargado_por,
                               'cuenta': cuenta_gmail,
                               'fecha_desde': fecha_descarga_desde,
                               'fecha_hasta': fecha_descarga_hasta,
                               'sin_envio': solo_sin_envio
                           })


@representante_bp.route('/poliza/<int:poliza_id>')
@login_required
@collaborator_requerido
def poliza_detalle(poliza_id):
    """Ver detalle de una póliza."""
    poliza = PolizaCliente.query.options(
        joinedload(PolizaCliente.cliente),
        joinedload(PolizaCliente.compania),
        joinedload(PolizaCliente.archivo).joinedload(ArchivoDescargado.escaneo).joinedload(Escaneo.usuario)
    ).get_or_404(poliza_id)

    # Obtener historial de envíos
    envios = EnvioWhatsApp.query.filter_by(poliza_cliente_id=poliza_id).order_by(
        EnvioWhatsApp.fecha_envio.desc()
    ).all()

    return render_template('representante/poliza_detalle.html',
                           poliza=poliza,
                           envios=envios)


@representante_bp.route('/cliente/<int:cliente_id>/enviar', methods=['GET', 'POST'])
@login_required
@collaborator_requerido
def enviar_documentos(cliente_id):
    """Enviar todos los documentos pendientes del cliente por WhatsApp."""
    cliente = Cliente.query.get_or_404(cliente_id)

    # Verificar que el cliente tenga teléfono
    if not cliente.telefono_whatsapp:
        flash('El cliente no tiene teléfono de WhatsApp configurado.', 'danger')
        return redirect(url_for('representante.index'))

    # Obtener pólizas del cliente que NO tienen envío previo
    polizas_con_envio = db.session.query(EnvioWhatsApp.poliza_cliente_id).filter(
        EnvioWhatsApp.poliza_cliente_id.isnot(None)
    ).distinct()

    polizas_pendientes = PolizaCliente.query.filter(
        PolizaCliente.cliente_id == cliente_id,
        PolizaCliente.archivo_id.isnot(None),  # Solo las que tienen PDF
        ~PolizaCliente.id.in_(polizas_con_envio)
    ).all()

    if not polizas_pendientes:
        flash('No hay documentos pendientes de envío para este cliente.', 'info')
        return redirect(url_for('representante.index'))

    # Obtener plantilla predeterminada
    plantilla = PlantillaMensaje.obtener_predeterminada(current_user.id)

    # Verificar modo de envío antes de procesar
    sender = WhatsAppSender(current_app.config)
    modo_api = sender.modo == 'api' and sender.api_key

    # Verificar si hay sesión de WhatsApp Web activa
    sesion_web = WhatsAppSession.query.filter_by(
        usuario_id=current_user.id,
        estado='ready',
        activo=True
    ).first()

    # Modo automático si hay API o sesión web activa
    envio_automatico = modo_api or sesion_web is not None

    if request.method == 'POST':
        envios_creados = []

        for poliza in polizas_pendientes:
            # Generar mensaje para esta póliza
            if plantilla:
                mensaje = plantilla.renderizar(cliente, poliza)
            else:
                mensaje = f"Hola {cliente.nombre}, te envío tu póliza {poliza.numero_poliza or ''} de {poliza.obtener_nombre_compania() or 'tu aseguradora'}. Saludos!"

            item = {
                'poliza': poliza,
                'mensaje': mensaje
            }

            # Crear EnvioWhatsApp si hay envío automático (API o sesión web)
            if envio_automatico:
                envio = EnvioWhatsApp(
                    cliente_id=cliente.id,
                    poliza_cliente_id=poliza.id,
                    archivo_id=poliza.archivo_id,
                    mensaje_enviado=mensaje,
                    estado='pendiente'
                )
                db.session.add(envio)
            else:
                # Modo manual: generar enlace wa.me
                item['enlace_wa'] = sender.generar_enlace_manual(
                    cliente.telefono_formateado,
                    mensaje
                )

            envios_creados.append(item)

        if envio_automatico:
            db.session.commit()
            metodo = 'WhatsApp Web' if sesion_web else 'API'
            LogActividad.registrar(
                current_user.id, 'envio_masivo_representante',
                f'{len(envios_creados)} documento(s) encolado(s) para envío ({metodo}) a {cliente.nombre_completo}',
                request
            )

        return render_template('representante/envio_confirmacion.html',
                               cliente=cliente,
                               envios=envios_creados,
                               envio_automatico=envio_automatico,
                               sesion_web=sesion_web)

    # GET: Mostrar confirmación antes de enviar
    return render_template('representante/confirmar_envio.html',
                           cliente=cliente,
                           polizas=polizas_pendientes,
                           plantilla=plantilla)


@representante_bp.route('/cliente/<int:cliente_id>/telefono', methods=['GET', 'POST'])
@login_required
@collaborator_requerido
def editar_telefono(cliente_id):
    """Editar teléfono de WhatsApp del cliente."""
    cliente = Cliente.query.get_or_404(cliente_id)

    # Obtener la póliza de referencia para volver
    poliza_id = request.args.get('poliza_id', type=int)

    if request.method == 'POST':
        nuevo_telefono = request.form.get('telefono', '').strip()

        if not nuevo_telefono:
            flash('El teléfono es requerido.', 'danger')
        else:
            exito, mensaje = cliente.establecer_telefono(nuevo_telefono)

            if exito:
                db.session.commit()
                LogActividad.registrar(
                    current_user.id, 'telefono_actualizado',
                    f'Teléfono de {cliente.nombre_completo} actualizado a {cliente.telefono_whatsapp}',
                    request
                )
                flash(f'Teléfono actualizado correctamente: {cliente.telefono_whatsapp}', 'success')

                if poliza_id:
                    return redirect(url_for('representante.poliza_detalle', poliza_id=poliza_id))
                return redirect(url_for('representante.index'))
            else:
                flash(f'Error: {mensaje}', 'danger')

    return render_template('representante/editar_telefono.html',
                           cliente=cliente,
                           poliza_id=poliza_id)

