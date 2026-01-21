"""
Sistema de alertas automaticas para vencimientos de polizas y pagos.
"""

from datetime import date, timedelta
from app import db
from app.models import (Usuario, Cliente, PolizaCliente, Pago,
                        AlertaVencimiento, Interaccion)


def generar_alertas_vencimiento_polizas(usuario_id=None, dias_anticipacion=None):
    """
    Genera alertas para polizas proximas a vencer.

    Args:
        usuario_id: Si se especifica, solo genera para ese usuario. Si es None, para todos.
        dias_anticipacion: Lista de dias antes del vencimiento para generar alertas.
                          Default: [30, 15, 7]
    """
    if dias_anticipacion is None:
        dias_anticipacion = [30, 15, 7]

    # Obtener usuarios a procesar
    if usuario_id:
        usuarios = Usuario.query.filter_by(id=usuario_id, activo=True).all()
    else:
        usuarios = Usuario.query.filter_by(activo=True).all()

    total_alertas = 0

    for usuario in usuarios:
        # Obtener polizas activas del usuario
        polizas = PolizaCliente.query.join(Cliente).filter(
            Cliente.usuario_id == usuario.id,
            PolizaCliente.estado == 'activa',
            PolizaCliente.fecha_vigencia_hasta.isnot(None)
        ).all()

        for poliza in polizas:
            for dias in dias_anticipacion:
                fecha_alerta = poliza.fecha_vigencia_hasta - timedelta(days=dias)

                # Solo crear si la fecha de alerta es hoy o en el futuro
                if fecha_alerta >= date.today():
                    # Verificar si ya existe esta alerta
                    existe = AlertaVencimiento.query.filter_by(
                        poliza_cliente_id=poliza.id,
                        tipo='vencimiento_poliza',
                        dias_anticipacion=dias
                    ).filter(
                        AlertaVencimiento.estado.in_(['pendiente', 'notificada'])
                    ).first()

                    if not existe:
                        alerta = AlertaVencimiento(
                            usuario_id=usuario.id,
                            poliza_cliente_id=poliza.id,
                            tipo='vencimiento_poliza',
                            fecha_alerta=fecha_alerta,
                            dias_anticipacion=dias,
                            mensaje=f'La poliza {poliza.numero_poliza or poliza.id} del cliente {poliza.cliente.nombre_completo} vence en {dias} dias ({poliza.fecha_vigencia_hasta.strftime("%d/%m/%Y")}).',
                            prioridad='alta' if dias <= 7 else ('media' if dias <= 15 else 'baja')
                        )
                        db.session.add(alerta)
                        total_alertas += 1

    db.session.commit()
    return total_alertas


def generar_alertas_vencimiento_pagos(usuario_id=None, dias_anticipacion=5):
    """
    Genera alertas para pagos proximos a vencer.

    Args:
        usuario_id: Si se especifica, solo genera para ese usuario.
        dias_anticipacion: Dias antes del vencimiento para generar alerta.
    """
    fecha_limite = date.today() + timedelta(days=dias_anticipacion)

    # Obtener usuarios a procesar
    if usuario_id:
        usuarios = Usuario.query.filter_by(id=usuario_id, activo=True).all()
    else:
        usuarios = Usuario.query.filter_by(activo=True).all()

    total_alertas = 0

    for usuario in usuarios:
        # Obtener pagos pendientes proximos a vencer
        pagos = Pago.query.join(PolizaCliente).join(Cliente).filter(
            Cliente.usuario_id == usuario.id,
            Pago.estado == 'pendiente',
            Pago.fecha_vencimiento <= fecha_limite,
            Pago.fecha_vencimiento >= date.today()
        ).all()

        for pago in pagos:
            # Verificar si ya existe esta alerta
            existe = AlertaVencimiento.query.filter_by(
                pago_id=pago.id,
                tipo='vencimiento_pago'
            ).filter(
                AlertaVencimiento.estado.in_(['pendiente', 'notificada'])
            ).first()

            if not existe:
                dias_restantes = (pago.fecha_vencimiento - date.today()).days
                alerta = AlertaVencimiento(
                    usuario_id=usuario.id,
                    poliza_cliente_id=pago.poliza_cliente_id,
                    pago_id=pago.id,
                    tipo='vencimiento_pago',
                    fecha_alerta=date.today(),
                    dias_anticipacion=dias_restantes,
                    mensaje=f'Pago de ${pago.monto:.2f} (cuota {pago.numero_cuota or "-"}) de {pago.poliza.cliente.nombre_completo} vence el {pago.fecha_vencimiento.strftime("%d/%m/%Y")}.',
                    prioridad='alta' if dias_restantes <= 2 else 'media'
                )
                db.session.add(alerta)
                total_alertas += 1

    db.session.commit()
    return total_alertas


def marcar_pagos_vencidos():
    """
    Actualiza el estado de pagos pendientes que ya vencieron.
    """
    pagos_vencidos = Pago.query.filter(
        Pago.estado == 'pendiente',
        Pago.fecha_vencimiento < date.today()
    ).all()

    count = 0
    for pago in pagos_vencidos:
        pago.estado = 'vencido'
        count += 1

    db.session.commit()
    return count


def actualizar_estados_polizas():
    """
    Actualiza el estado de polizas basado en su fecha de vencimiento.
    """
    # Polizas vencidas
    polizas_vencidas = PolizaCliente.query.filter(
        PolizaCliente.estado == 'activa',
        PolizaCliente.fecha_vigencia_hasta < date.today()
    ).all()

    count_vencidas = 0
    for poliza in polizas_vencidas:
        poliza.estado = 'vencida'
        count_vencidas += 1

    # Polizas en renovacion (proximas a vencer)
    fecha_limite = date.today() + timedelta(days=15)
    polizas_renovacion = PolizaCliente.query.filter(
        PolizaCliente.estado == 'activa',
        PolizaCliente.fecha_vigencia_hasta <= fecha_limite,
        PolizaCliente.fecha_vigencia_hasta >= date.today()
    ).all()

    count_renovacion = 0
    for poliza in polizas_renovacion:
        poliza.estado = 'en_renovacion'
        count_renovacion += 1

    db.session.commit()
    return {'vencidas': count_vencidas, 'en_renovacion': count_renovacion}


def generar_alertas_seguimientos_pendientes(usuario_id=None):
    """
    Genera alertas para seguimientos pendientes cuya fecha ya paso o es hoy.
    """
    if usuario_id:
        usuarios = Usuario.query.filter_by(id=usuario_id, activo=True).all()
    else:
        usuarios = Usuario.query.filter_by(activo=True).all()

    total_alertas = 0

    for usuario in usuarios:
        # Obtener interacciones con seguimiento pendiente
        interacciones = Interaccion.query.join(Cliente).filter(
            Cliente.usuario_id == usuario.id,
            Interaccion.requiere_seguimiento == True,
            Interaccion.seguimiento_completado == False,
            Interaccion.fecha_seguimiento <= date.today()
        ).all()

        for inter in interacciones:
            # Verificar si ya existe esta alerta
            existe = AlertaVencimiento.query.filter(
                AlertaVencimiento.usuario_id == usuario.id,
                AlertaVencimiento.tipo == 'seguimiento',
                AlertaVencimiento.mensaje.contains(str(inter.id))
            ).filter(
                AlertaVencimiento.estado.in_(['pendiente', 'notificada'])
            ).first()

            if not existe:
                alerta = AlertaVencimiento(
                    usuario_id=usuario.id,
                    poliza_cliente_id=inter.poliza_cliente_id,
                    tipo='seguimiento',
                    fecha_alerta=inter.fecha_seguimiento or date.today(),
                    mensaje=f'Seguimiento pendiente con {inter.cliente.nombre_completo}: {inter.asunto or inter.tipo} (ID: {inter.id})',
                    prioridad='media'
                )
                db.session.add(alerta)
                total_alertas += 1

    db.session.commit()
    return total_alertas


def ejecutar_tareas_diarias(usuario_id=None):
    """
    Ejecuta todas las tareas de mantenimiento diario.
    Puede llamarse desde un job scheduler o manualmente.

    Returns:
        dict: Resumen de las tareas ejecutadas.
    """
    resultados = {
        'pagos_marcados_vencidos': marcar_pagos_vencidos(),
        'polizas_actualizadas': actualizar_estados_polizas(),
        'alertas_polizas': generar_alertas_vencimiento_polizas(usuario_id),
        'alertas_pagos': generar_alertas_vencimiento_pagos(usuario_id),
        'alertas_seguimientos': generar_alertas_seguimientos_pendientes(usuario_id),
    }

    return resultados


def limpiar_alertas_antiguas(dias=90):
    """
    Elimina alertas resueltas o descartadas mas antiguas que N dias.
    """
    fecha_limite = date.today() - timedelta(days=dias)

    alertas_eliminar = AlertaVencimiento.query.filter(
        AlertaVencimiento.estado.in_(['resuelta', 'descartada']),
        AlertaVencimiento.fecha_creacion < fecha_limite
    ).all()

    count = len(alertas_eliminar)
    for alerta in alertas_eliminar:
        db.session.delete(alerta)

    db.session.commit()
    return count
