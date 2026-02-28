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
    EnvioWhatsApp, PlantillaMensaje, LogActividad, Pago, Usuario
)
from app.utils.decoradores import collaborator_requerido
from app.distribucion.forms import EnvioForm, PagoForm
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

    return render_template('representante/dashboard.html',
                           polizas=polizas,
                           paginacion=paginacion,
                           stats=stats,
                           companias=companias,
                           usuarios=usuarios,
                           cuentas=cuentas,
                           tipos_seguro=tipos_seguro,
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

    # Obtener pagos
    pagos = Pago.query.filter_by(poliza_cliente_id=poliza_id).order_by(
        Pago.numero_cuota
    ).all()

    return render_template('representante/poliza_detalle.html',
                           poliza=poliza,
                           envios=envios,
                           pagos=pagos)


@representante_bp.route('/poliza/<int:poliza_id>/whatsapp', methods=['GET', 'POST'])
@login_required
@collaborator_requerido
def enviar_whatsapp(poliza_id):
    """Enviar póliza por WhatsApp."""
    poliza = PolizaCliente.query.options(
        joinedload(PolizaCliente.cliente)
    ).get_or_404(poliza_id)

    cliente = poliza.cliente
    form = EnvioForm()

    # Obtener mensaje predeterminado
    if cliente.usar_mensaje_estandar:
        plantilla = PlantillaMensaje.obtener_predeterminada(current_user.id)
        if plantilla:
            mensaje_default = plantilla.renderizar(cliente, poliza)
        else:
            mensaje_default = f"Hola {cliente.nombre}, este es un envío de tu póliza número {poliza.numero_poliza or ''} de la compañía {poliza.obtener_nombre_compania() or ''}. Saludos!"
    else:
        mensaje_default = cliente.mensaje_personalizado or ''
        plantilla_temp = PlantillaMensaje(mensaje=mensaje_default)
        mensaje_default = plantilla_temp.renderizar(cliente, poliza)

    if not form.mensaje.data:
        form.mensaje.data = mensaje_default

    if form.validate_on_submit():
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
            current_user.id, 'envio_whatsapp_representante',
            f'Póliza {poliza.numero_poliza} encolada para envío a {cliente.nombre_completo}',
            request
        )

        sender = WhatsAppSender(current_app.config)
        if sender.modo == 'api' and sender.api_key:
            flash(f'Mensaje encolado para envío a {cliente.nombre_completo}.', 'success')
            return redirect(url_for('representante.poliza_detalle', poliza_id=poliza.id))
        else:
            enlace = sender.generar_enlace_manual(
                cliente.telefono_formateado,
                form.mensaje.data
            )
            flash('Usa el enlace para enviar manualmente por WhatsApp.', 'info')
            return render_template('representante/enviar_resultado.html',
                                   enlace=enlace,
                                   cliente=cliente,
                                   poliza=poliza,
                                   envio=envio)

    return render_template('representante/enviar_whatsapp.html',
                           form=form,
                           cliente=cliente,
                           poliza=poliza)


@representante_bp.route('/poliza/<int:poliza_id>/pago', methods=['GET', 'POST'])
@login_required
@collaborator_requerido
def registrar_pago(poliza_id):
    """Registrar un pago de la póliza."""
    poliza = PolizaCliente.query.options(
        joinedload(PolizaCliente.cliente)
    ).get_or_404(poliza_id)

    form = PagoForm()

    # Obtener siguiente número de cuota
    ultimo_pago = Pago.query.filter_by(poliza_cliente_id=poliza_id).order_by(
        Pago.numero_cuota.desc()
    ).first()
    siguiente_cuota = (ultimo_pago.numero_cuota + 1) if ultimo_pago else 1

    if not form.numero_cuota.data:
        form.numero_cuota.data = siguiente_cuota

    if form.validate_on_submit():
        pago = Pago(
            poliza_cliente_id=poliza.id,
            numero_cuota=form.numero_cuota.data,
            monto=form.monto.data,
            fecha_vencimiento=form.fecha_vencimiento.data,
            fecha_pago=form.fecha_pago.data,
            estado='pagado' if form.fecha_pago.data else 'pendiente',
            medio_pago=form.medio_pago.data,
            comprobante=form.comprobante.data,
            notas=form.notas.data
        )
        db.session.add(pago)
        db.session.commit()

        LogActividad.registrar(
            current_user.id, 'pago_registrado_representante',
            f'Pago cuota {pago.numero_cuota} de póliza {poliza.numero_poliza}',
            request
        )

        flash(f'Pago de cuota {pago.numero_cuota} registrado correctamente.', 'success')
        return redirect(url_for('representante.poliza_detalle', poliza_id=poliza.id))

    # Obtener pagos existentes
    pagos = Pago.query.filter_by(poliza_cliente_id=poliza_id).order_by(
        Pago.numero_cuota
    ).all()

    return render_template('representante/registrar_pago.html',
                           form=form,
                           poliza=poliza,
                           pagos=pagos)
