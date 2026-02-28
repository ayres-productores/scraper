"""
Sistema de alertas automaticas para vencimientos de polizas y pagos.

NOTA: Este módulo puede ejecutarse desde:
- Contexto web (request de Flask) - usa db.session normal
- Contexto background (scheduler/thread) - usa thread_session

Todas las funciones aceptan un parámetro opcional `session` para permitir
inyección de sesión en contextos thread-safe.
"""

from datetime import date, timedelta
from flask import has_app_context, current_app
from app import db
from app.models import (Usuario, Cliente, PolizaCliente, Pago,
                        AlertaVencimiento, Interaccion)


def _get_session(session=None):
    """
    Obtiene la sesión de BD apropiada para el contexto actual.

    Args:
        session: Sesión explícita (para threads). Si None, usa db.session.

    Returns:
        Sesión SQLAlchemy a usar
    """
    if session is not None:
        return session
    return db.session


def generar_alertas_vencimiento_polizas(usuario_id=None, dias_anticipacion=None, session=None):
    """
    Genera alertas para polizas proximas a vencer.

    Args:
        usuario_id: Si se especifica, solo genera para ese usuario. Si es None, para todos.
        dias_anticipacion: Lista de dias antes del vencimiento para generar alertas.
                          Default: [30, 15, 7]
        session: Sesión SQLAlchemy (opcional, para uso en threads)
    """
    if dias_anticipacion is None:
        dias_anticipacion = [30, 15, 7]

    db_session = _get_session(session)

    # Obtener usuarios a procesar
    if usuario_id:
        usuarios = db_session.query(Usuario).filter_by(id=usuario_id, activo=True).all()
    else:
        usuarios = db_session.query(Usuario).filter_by(activo=True).all()

    total_alertas = 0

    for usuario in usuarios:
        # Obtener polizas activas del usuario
        polizas = db_session.query(PolizaCliente).join(Cliente).filter(
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
                    existe = db_session.query(AlertaVencimiento).filter_by(
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
                        db_session.add(alerta)
                        total_alertas += 1

    # Solo commit si usamos db.session (no si es thread_session que hace autocommit)
    if session is None:
        db_session.commit()

    return total_alertas


def generar_alertas_vencimiento_pagos(usuario_id=None, dias_anticipacion=5, session=None):
    """
    Genera alertas para pagos proximos a vencer.

    Args:
        usuario_id: Si se especifica, solo genera para ese usuario.
        dias_anticipacion: Dias antes del vencimiento para generar alerta.
        session: Sesión SQLAlchemy (opcional, para uso en threads)
    """
    fecha_limite = date.today() + timedelta(days=dias_anticipacion)
    db_session = _get_session(session)

    # Obtener usuarios a procesar
    if usuario_id:
        usuarios = db_session.query(Usuario).filter_by(id=usuario_id, activo=True).all()
    else:
        usuarios = db_session.query(Usuario).filter_by(activo=True).all()

    total_alertas = 0

    for usuario in usuarios:
        # Obtener pagos pendientes proximos a vencer
        pagos = db_session.query(Pago).join(PolizaCliente).join(Cliente).filter(
            Cliente.usuario_id == usuario.id,
            Pago.estado == 'pendiente',
            Pago.fecha_vencimiento <= fecha_limite,
            Pago.fecha_vencimiento >= date.today()
        ).all()

        for pago in pagos:
            # Verificar si ya existe esta alerta
            existe = db_session.query(AlertaVencimiento).filter_by(
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
                db_session.add(alerta)
                total_alertas += 1

    if session is None:
        db_session.commit()

    return total_alertas


def marcar_pagos_vencidos(session=None):
    """
    Actualiza el estado de pagos pendientes que ya vencieron.

    Args:
        session: Sesión SQLAlchemy (opcional, para uso en threads)
    """
    db_session = _get_session(session)

    pagos_vencidos = db_session.query(Pago).filter(
        Pago.estado == 'pendiente',
        Pago.fecha_vencimiento < date.today()
    ).all()

    count = 0
    for pago in pagos_vencidos:
        pago.estado = 'vencido'
        count += 1

    if session is None:
        db_session.commit()

    return count


def actualizar_estados_polizas(session=None):
    """
    Actualiza el estado de polizas basado en su fecha de vencimiento.

    Args:
        session: Sesión SQLAlchemy (opcional, para uso en threads)
    """
    db_session = _get_session(session)

    # Polizas vencidas
    polizas_vencidas = db_session.query(PolizaCliente).filter(
        PolizaCliente.estado == 'activa',
        PolizaCliente.fecha_vigencia_hasta < date.today()
    ).all()

    count_vencidas = 0
    for poliza in polizas_vencidas:
        poliza.estado = 'vencida'
        count_vencidas += 1

    # Polizas en renovacion (proximas a vencer)
    fecha_limite = date.today() + timedelta(days=15)
    polizas_renovacion = db_session.query(PolizaCliente).filter(
        PolizaCliente.estado == 'activa',
        PolizaCliente.fecha_vigencia_hasta <= fecha_limite,
        PolizaCliente.fecha_vigencia_hasta >= date.today()
    ).all()

    count_renovacion = 0
    for poliza in polizas_renovacion:
        poliza.estado = 'en_renovacion'
        count_renovacion += 1

    if session is None:
        db_session.commit()

    return {'vencidas': count_vencidas, 'en_renovacion': count_renovacion}


def generar_alertas_seguimientos_pendientes(usuario_id=None, session=None):
    """
    Genera alertas para seguimientos pendientes cuya fecha ya paso o es hoy.

    Args:
        usuario_id: Si se especifica, solo genera para ese usuario.
        session: Sesión SQLAlchemy (opcional, para uso en threads)
    """
    db_session = _get_session(session)

    if usuario_id:
        usuarios = db_session.query(Usuario).filter_by(id=usuario_id, activo=True).all()
    else:
        usuarios = db_session.query(Usuario).filter_by(activo=True).all()

    total_alertas = 0

    for usuario in usuarios:
        # Obtener interacciones con seguimiento pendiente
        interacciones = db_session.query(Interaccion).join(Cliente).filter(
            Cliente.usuario_id == usuario.id,
            Interaccion.requiere_seguimiento == True,
            Interaccion.seguimiento_completado == False,
            Interaccion.fecha_seguimiento <= date.today()
        ).all()

        for inter in interacciones:
            # Verificar si ya existe esta alerta
            existe = db_session.query(AlertaVencimiento).filter(
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
                db_session.add(alerta)
                total_alertas += 1

    if session is None:
        db_session.commit()

    return total_alertas


def ejecutar_tareas_diarias(usuario_id=None, session=None):
    """
    Ejecuta todas las tareas de mantenimiento diario.
    Puede llamarse desde un job scheduler o manualmente.

    Para uso desde threads background, usar con thread_session:

        from app.utils.db_session import thread_session
        with thread_session(app) as session:
            ejecutar_tareas_diarias(session=session)

    Args:
        usuario_id: ID del usuario (None para todos)
        session: Sesión SQLAlchemy (opcional, para uso en threads)

    Returns:
        dict: Resumen de las tareas ejecutadas.
    """
    from app.tasks.clientes_actuales import evaluar_clientes_actuales

    resultados = {
        'pagos_marcados_vencidos': marcar_pagos_vencidos(session=session),
        'polizas_actualizadas': actualizar_estados_polizas(session=session),
        'alertas_polizas': generar_alertas_vencimiento_polizas(usuario_id, session=session),
        'alertas_pagos': generar_alertas_vencimiento_pagos(usuario_id, session=session),
        'alertas_seguimientos': generar_alertas_seguimientos_pendientes(usuario_id, session=session),
        'clientes_evaluados': evaluar_clientes_actuales(usuario_id, session=session),
    }

    return resultados


def limpiar_alertas_antiguas(dias=90, session=None):
    """
    Elimina alertas resueltas o descartadas mas antiguas que N dias.

    Args:
        dias: Días de antigüedad para eliminar
        session: Sesión SQLAlchemy (opcional, para uso en threads)
    """
    db_session = _get_session(session)
    fecha_limite = date.today() - timedelta(days=dias)

    alertas_eliminar = db_session.query(AlertaVencimiento).filter(
        AlertaVencimiento.estado.in_(['resuelta', 'descartada']),
        AlertaVencimiento.fecha_creacion < fecha_limite
    ).all()

    count = len(alertas_eliminar)
    for alerta in alertas_eliminar:
        db_session.delete(alerta)

    if session is None:
        db_session.commit()

    return count


# ============================================================================
# FUNCIONES THREAD-SAFE PARA USO CON SCHEDULERS
# ============================================================================

def ejecutar_tareas_diarias_background(app):
    """
    Versión thread-safe de ejecutar_tareas_diarias para uso con schedulers.

    Uso con APScheduler:
        scheduler.add_job(
            func=lambda: ejecutar_tareas_diarias_background(app),
            trigger='cron',
            hour=6,
            minute=0
        )

    Args:
        app: Instancia de Flask app

    Returns:
        dict: Resumen de las tareas ejecutadas
    """
    from app.utils.db_session import thread_session
    from app.utils.structured_logger import log_operacion

    try:
        with thread_session(app) as session:
            resultados = ejecutar_tareas_diarias(session=session)

            log_operacion('bd', 'tareas_diarias', 'exito',
                          pagos_vencidos=resultados['pagos_marcados_vencidos'],
                          polizas_vencidas=resultados['polizas_actualizadas'].get('vencidas', 0),
                          polizas_renovacion=resultados['polizas_actualizadas'].get('en_renovacion', 0),
                          alertas_polizas=resultados['alertas_polizas'],
                          alertas_pagos=resultados['alertas_pagos'],
                          alertas_seguimientos=resultados['alertas_seguimientos'])

            return resultados

    except Exception as e:
        log_operacion('bd', 'tareas_diarias', 'error', error=str(e))
        raise
