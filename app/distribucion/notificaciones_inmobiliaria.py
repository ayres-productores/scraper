"""
Sistema de notificaciones para inmobiliarias.

Genera y encola notificaciones a inmobiliarias cuando ocurren eventos
en polizas de tipo incendio y hogar asignadas a una inmobiliaria.
"""

from datetime import datetime
from app import db
from app.models import NotificacionInmobiliaria, PolizaCliente, Inmobiliaria


# Tipos de seguro que pueden tener inmobiliaria asignada
TIPOS_CON_INMOBILIARIA = ('incendio', 'hogar')


def generar_mensaje_vencimiento(poliza, inmobiliaria, dias_restantes):
    """Genera mensaje para notificacion de vencimiento proximo."""
    cliente = poliza.cliente
    mensaje = f"""*Aviso de Vencimiento*

Inmobiliaria: {inmobiliaria.nombre}
Poliza: {poliza.numero_poliza or f'ID {poliza.id}'}
Asegurado: {poliza.asegurado_nombre or cliente.nombre_completo}
Tipo: {poliza.tipo_seguro}

Vence el: {poliza.fecha_vigencia_hasta.strftime('%d/%m/%Y')}
Dias restantes: {dias_restantes}

{f'Direccion: {poliza.inmueble_direccion}' if poliza.inmueble_direccion else ''}
"""
    return mensaje.strip()


def generar_mensaje_renovacion(poliza, inmobiliaria):
    """Genera mensaje para notificacion de renovacion."""
    cliente = poliza.cliente
    mensaje = f"""*Renovacion de Poliza*

Inmobiliaria: {inmobiliaria.nombre}
Poliza: {poliza.numero_poliza or f'ID {poliza.id}'}
Asegurado: {poliza.asegurado_nombre or cliente.nombre_completo}
Tipo: {poliza.tipo_seguro}

Nueva vigencia: {poliza.fecha_vigencia_desde.strftime('%d/%m/%Y')} al {poliza.fecha_vigencia_hasta.strftime('%d/%m/%Y')}

{f'Direccion: {poliza.inmueble_direccion}' if poliza.inmueble_direccion else ''}
"""
    return mensaje.strip()


def generar_mensaje_siniestro(poliza, inmobiliaria, siniestro):
    """Genera mensaje para notificacion de siniestro."""
    cliente = poliza.cliente
    mensaje = f"""*URGENTE - Siniestro Registrado*

Inmobiliaria: {inmobiliaria.nombre}
Poliza: {poliza.numero_poliza or f'ID {poliza.id}'}
Asegurado: {poliza.asegurado_nombre or cliente.nombre_completo}

Fecha del siniestro: {siniestro.fecha_ocurrencia.strftime('%d/%m/%Y')}
Tipo: {siniestro.tipo_siniestro or 'No especificado'}

Descripcion: {siniestro.descripcion[:200]}{'...' if len(siniestro.descripcion) > 200 else ''}

{f'Ubicacion: {siniestro.ubicacion}' if siniestro.ubicacion else ''}
"""
    return mensaje.strip()


def generar_mensaje_cambio_estado(poliza, inmobiliaria, estado_anterior, estado_nuevo):
    """Genera mensaje para notificacion de cambio de estado."""
    cliente = poliza.cliente
    mensaje = f"""*Cambio de Estado de Poliza*

Inmobiliaria: {inmobiliaria.nombre}
Poliza: {poliza.numero_poliza or f'ID {poliza.id}'}
Asegurado: {poliza.asegurado_nombre or cliente.nombre_completo}
Tipo: {poliza.tipo_seguro}

Estado anterior: {estado_anterior}
Nuevo estado: {estado_nuevo}

{f'Direccion: {poliza.inmueble_direccion}' if poliza.inmueble_direccion else ''}
"""
    return mensaje.strip()


def notificar_vencimiento(poliza_id, dias_restantes=None):
    """
    Crea notificacion de vencimiento proximo para la inmobiliaria.

    Args:
        poliza_id: ID de la poliza que va a vencer
        dias_restantes: Dias hasta el vencimiento (opcional, se calcula si no se provee)

    Returns:
        NotificacionInmobiliaria creada o None si no aplica
    """
    poliza = PolizaCliente.query.get(poliza_id)
    if not poliza:
        return None

    # Verificar que tiene inmobiliaria asignada
    if not poliza.inmobiliaria_id:
        return None

    # Verificar tipo de seguro
    if poliza.tipo_seguro not in TIPOS_CON_INMOBILIARIA:
        return None

    inmobiliaria = poliza.inmobiliaria
    if not inmobiliaria or not inmobiliaria.activa:
        return None

    # Verificar que la inmobiliaria tiene WhatsApp
    if not inmobiliaria.telefono_whatsapp:
        return None

    # Calcular dias restantes si no se provee
    if dias_restantes is None and poliza.fecha_vigencia_hasta:
        from datetime import date
        dias_restantes = (poliza.fecha_vigencia_hasta - date.today()).days

    mensaje = generar_mensaje_vencimiento(poliza, inmobiliaria, dias_restantes)

    notif = NotificacionInmobiliaria.crear_notificacion(
        inmobiliaria_id=inmobiliaria.id,
        poliza_id=poliza.id,
        tipo='vencimiento',
        mensaje=mensaje
    )

    return notif


def notificar_renovacion(poliza_id):
    """
    Crea notificacion de renovacion para la inmobiliaria.
    """
    poliza = PolizaCliente.query.get(poliza_id)
    if not poliza:
        return None

    if not poliza.inmobiliaria_id:
        return None

    if poliza.tipo_seguro not in TIPOS_CON_INMOBILIARIA:
        return None

    inmobiliaria = poliza.inmobiliaria
    if not inmobiliaria or not inmobiliaria.activa:
        return None

    if not inmobiliaria.telefono_whatsapp:
        return None

    mensaje = generar_mensaje_renovacion(poliza, inmobiliaria)

    notif = NotificacionInmobiliaria.crear_notificacion(
        inmobiliaria_id=inmobiliaria.id,
        poliza_id=poliza.id,
        tipo='renovacion',
        mensaje=mensaje
    )

    return notif


def notificar_siniestro(poliza_id, siniestro):
    """
    Crea notificacion de siniestro para la inmobiliaria.
    """
    poliza = PolizaCliente.query.get(poliza_id)
    if not poliza:
        return None

    if not poliza.inmobiliaria_id:
        return None

    if poliza.tipo_seguro not in TIPOS_CON_INMOBILIARIA:
        return None

    inmobiliaria = poliza.inmobiliaria
    if not inmobiliaria or not inmobiliaria.activa:
        return None

    if not inmobiliaria.telefono_whatsapp:
        return None

    mensaje = generar_mensaje_siniestro(poliza, inmobiliaria, siniestro)

    notif = NotificacionInmobiliaria.crear_notificacion(
        inmobiliaria_id=inmobiliaria.id,
        poliza_id=poliza.id,
        tipo='siniestro',
        mensaje=mensaje
    )

    return notif


def notificar_cambio_estado(poliza_id, estado_anterior, estado_nuevo):
    """
    Crea notificacion de cambio de estado para la inmobiliaria.
    """
    poliza = PolizaCliente.query.get(poliza_id)
    if not poliza:
        return None

    if not poliza.inmobiliaria_id:
        return None

    if poliza.tipo_seguro not in TIPOS_CON_INMOBILIARIA:
        return None

    inmobiliaria = poliza.inmobiliaria
    if not inmobiliaria or not inmobiliaria.activa:
        return None

    if not inmobiliaria.telefono_whatsapp:
        return None

    mensaje = generar_mensaje_cambio_estado(poliza, inmobiliaria, estado_anterior, estado_nuevo)

    notif = NotificacionInmobiliaria.crear_notificacion(
        inmobiliaria_id=inmobiliaria.id,
        poliza_id=poliza.id,
        tipo='cambio_estado',
        mensaje=mensaje
    )

    return notif


def generar_notificaciones_vencimiento_masivo(dias_anticipacion=30, usuario_id=None):
    """
    Genera notificaciones de vencimiento para todas las polizas
    que venzan en los proximos N dias.

    Args:
        dias_anticipacion: Dias antes del vencimiento para notificar
        usuario_id: Si se especifica, solo para polizas de este usuario

    Returns:
        Cantidad de notificaciones creadas
    """
    from datetime import date, timedelta
    from app.models import Cliente

    fecha_limite = date.today() + timedelta(days=dias_anticipacion)

    # Query de polizas que vencen pronto con inmobiliaria asignada
    query = PolizaCliente.query.filter(
        PolizaCliente.inmobiliaria_id.isnot(None),
        PolizaCliente.tipo_seguro.in_(TIPOS_CON_INMOBILIARIA),
        PolizaCliente.estado == 'activa',
        PolizaCliente.fecha_vigencia_hasta <= fecha_limite,
        PolizaCliente.fecha_vigencia_hasta >= date.today()
    )

    if usuario_id:
        query = query.join(Cliente).filter(Cliente.usuario_id == usuario_id)

    polizas = query.all()

    notificaciones_creadas = 0

    for poliza in polizas:
        dias = (poliza.fecha_vigencia_hasta - date.today()).days

        # Verificar si ya existe una notificacion pendiente de vencimiento para esta poliza
        existente = NotificacionInmobiliaria.query.filter_by(
            poliza_id=poliza.id,
            tipo='vencimiento',
            estado='pendiente'
        ).first()

        if not existente:
            notif = notificar_vencimiento(poliza.id, dias)
            if notif:
                notificaciones_creadas += 1

    db.session.commit()
    return notificaciones_creadas
