"""
Módulo para evaluación de clientes actuales.
Identifica clientes que necesitan reactivación basándose en:
1. Comunicación exitosa en últimos 6 meses
2. Póliza emitida/vigente en el último año

NOTA: Este módulo puede ejecutarse desde:
- Contexto web (request de Flask) - usa db.session normal
- Contexto background (scheduler/thread) - usa thread_session

Todas las funciones aceptan un parámetro opcional `session` para permitir
inyección de sesión en contextos thread-safe.
"""

from datetime import datetime
from app import db
from app.models import Cliente, AlertaVencimiento


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


def evaluar_clientes_actuales(usuario_id=None, session=None):
    """
    Evalúa todos los clientes y actualiza su estado 'actual'.
    Genera alertas para clientes que dejaron de ser actuales.

    Args:
        usuario_id: ID del usuario (None para todos los usuarios)
        session: Sesión SQLAlchemy (opcional, para uso en threads)

    Returns:
        dict: Estadísticas de la evaluación
    """
    db_session = _get_session(session)

    # Construir query
    query = db_session.query(Cliente).filter_by(activo=True)
    if usuario_id:
        query = query.filter_by(usuario_id=usuario_id)

    clientes = query.all()

    stats = {
        'total_evaluados': 0,
        'actuales': 0,
        'no_actuales': 0,
        'nuevos_no_actuales': 0,  # Clientes que eran actuales y dejaron de serlo
        'recuperados': 0,  # Clientes que no eran actuales y ahora sí
        'alertas_creadas': 0,
        'por_motivo': {
            'sin_comunicacion': 0,
            'sin_poliza_reciente': 0,
            'ambos': 0
        }
    }

    for cliente in clientes:
        stats['total_evaluados'] += 1

        era_actual = cliente.es_cliente_actual
        es_actual, detalles = cliente.actualizar_estado_actual()

        if es_actual:
            stats['actuales'] += 1
            if not era_actual:
                stats['recuperados'] += 1
                # Resolver alertas de reactivación pendientes
                _resolver_alertas_reactivacion(cliente, db_session)
        else:
            stats['no_actuales'] += 1

            # Contar por motivo
            if cliente.motivo_no_actual:
                stats['por_motivo'][cliente.motivo_no_actual] = \
                    stats['por_motivo'].get(cliente.motivo_no_actual, 0) + 1

            if era_actual:
                stats['nuevos_no_actuales'] += 1
                # Crear alerta de reactivación
                if _crear_alerta_reactivacion(cliente, db_session):
                    stats['alertas_creadas'] += 1

    if session is None:
        db_session.commit()

    return stats


def _crear_alerta_reactivacion(cliente, db_session=None):
    """
    Crea una alerta de reactivación para un cliente.
    Solo crea si no existe una alerta pendiente.

    Args:
        cliente: Objeto Cliente
        db_session: Sesión SQLAlchemy (opcional)

    Returns:
        bool: True si se creó la alerta
    """
    if db_session is None:
        db_session = db.session

    # Verificar si ya existe una alerta pendiente
    alerta_existente = db_session.query(AlertaVencimiento).filter_by(
        usuario_id=cliente.usuario_id,
        tipo='reactivacion_cliente',
        estado='pendiente'
    ).filter(
        AlertaVencimiento.mensaje.contains(f"Cliente: {cliente.nombre_completo}")
    ).first()

    if alerta_existente:
        return False

    # Construir mensaje según motivo
    motivo_texto = {
        'sin_comunicacion': 'sin contacto en 6+ meses',
        'sin_poliza_reciente': 'sin póliza emitida en 1+ año',
        'ambos': 'sin contacto ni póliza reciente'
    }.get(cliente.motivo_no_actual, 'requiere seguimiento')

    mensaje = f"Cliente: {cliente.nombre_completo} ({motivo_texto})"

    alerta = AlertaVencimiento(
        usuario_id=cliente.usuario_id,
        tipo='reactivacion_cliente',
        fecha_alerta=datetime.utcnow().date(),
        mensaje=mensaje,
        prioridad='media',
        estado='pendiente'
    )

    db_session.add(alerta)
    return True


def _resolver_alertas_reactivacion(cliente, db_session=None):
    """
    Resuelve alertas de reactivación pendientes para un cliente recuperado.

    Args:
        cliente: Objeto Cliente
        db_session: Sesión SQLAlchemy (opcional)
    """
    if db_session is None:
        db_session = db.session

    alertas = db_session.query(AlertaVencimiento).filter_by(
        usuario_id=cliente.usuario_id,
        tipo='reactivacion_cliente',
        estado='pendiente'
    ).filter(
        AlertaVencimiento.mensaje.contains(f"Cliente: {cliente.nombre_completo}")
    ).all()

    for alerta in alertas:
        alerta.estado = 'resuelta'
        alerta.fecha_notificacion = datetime.utcnow()


def obtener_clientes_a_reactivar(usuario_id, session=None):
    """
    Obtiene lista de clientes que necesitan reactivación.

    Args:
        usuario_id: ID del usuario
        session: Sesión SQLAlchemy (opcional, para uso en threads)

    Returns:
        list: Lista de clientes con es_cliente_actual=False
    """
    db_session = _get_session(session)

    return db_session.query(Cliente).filter_by(
        usuario_id=usuario_id,
        activo=True,
        es_cliente_actual=False
    ).order_by(Cliente.fecha_evaluacion_actual.desc()).all()


def obtener_estadisticas_reactivacion(usuario_id, session=None):
    """
    Obtiene estadísticas de clientes para reactivación.

    Args:
        usuario_id: ID del usuario
        session: Sesión SQLAlchemy (opcional, para uso en threads)

    Returns:
        dict: Estadísticas
    """
    db_session = _get_session(session)

    total_clientes = db_session.query(Cliente).filter_by(
        usuario_id=usuario_id,
        activo=True
    ).count()

    clientes_actuales = db_session.query(Cliente).filter_by(
        usuario_id=usuario_id,
        activo=True,
        es_cliente_actual=True
    ).count()

    clientes_no_actuales = db_session.query(Cliente).filter_by(
        usuario_id=usuario_id,
        activo=True,
        es_cliente_actual=False
    ).count()

    # Contar por motivo
    sin_comunicacion = db_session.query(Cliente).filter_by(
        usuario_id=usuario_id,
        activo=True,
        es_cliente_actual=False,
        motivo_no_actual='sin_comunicacion'
    ).count()

    sin_poliza = db_session.query(Cliente).filter_by(
        usuario_id=usuario_id,
        activo=True,
        es_cliente_actual=False,
        motivo_no_actual='sin_poliza_reciente'
    ).count()

    ambos = db_session.query(Cliente).filter_by(
        usuario_id=usuario_id,
        activo=True,
        es_cliente_actual=False,
        motivo_no_actual='ambos'
    ).count()

    return {
        'total_clientes': total_clientes,
        'actuales': clientes_actuales,
        'no_actuales': clientes_no_actuales,
        'porcentaje_actuales': round(clientes_actuales / total_clientes * 100, 1) if total_clientes > 0 else 0,
        'por_motivo': {
            'sin_comunicacion': sin_comunicacion,
            'sin_poliza_reciente': sin_poliza,
            'ambos': ambos
        }
    }


def generar_tareas_reactivacion(usuario_id, session=None):
    """
    Genera alertas de reactivación para clientes no actuales
    que aún no tienen tarea pendiente.

    Args:
        usuario_id: ID del usuario
        session: Sesión SQLAlchemy (opcional, para uso en threads)

    Returns:
        int: Número de alertas creadas
    """
    db_session = _get_session(session)
    clientes = obtener_clientes_a_reactivar(usuario_id, session=db_session)
    alertas_creadas = 0

    for cliente in clientes:
        if _crear_alerta_reactivacion(cliente, db_session):
            alertas_creadas += 1

    if session is None:
        db_session.commit()

    return alertas_creadas
