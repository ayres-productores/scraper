"""
Rutas del módulo Usage Tracker.

Incluye:
- API para recibir eventos de tracking
- Panel de analytics con visualización de uso
"""

from datetime import datetime
from flask import render_template, request, jsonify, current_app
from flask_login import login_required, current_user

from app import db
from app.usage_tracker import usage_tracker_bp
from app.usage_tracker.models import EventoUso
from app.utils.decoradores import admin_requerido


# =============================================================================
# API - Recepción de eventos (sin autenticación para permitir tracking anónimo)
# =============================================================================

@usage_tracker_bp.route('/track', methods=['POST'])
def track_evento():
    """Recibe eventos de tracking del frontend.

    Acepta JSON con formato:
    {
        "events": [
            {
                "pagina": "/distribucion/clientes",
                "elemento": "button",
                "elemento_id": "btn-nuevo",
                "elemento_texto": "Nuevo Cliente",
                "accion": "click",
                "posicion_x": 150,
                "posicion_y": 300,
                "viewport_width": 1920,
                "viewport_height": 1080
            }
        ]
    }
    """
    if not current_app.config.get('USAGE_TRACKER_ENABLED', True):
        return jsonify({'ok': True, 'tracked': 0}), 200

    try:
        data = request.get_json(silent=True) or {}
        eventos = data.get('events', [])

        # Limitar cantidad de eventos por request
        eventos = eventos[:50]

        for evento in eventos:
            EventoUso.registrar(evento)

        db.session.commit()

        return jsonify({'ok': True, 'tracked': len(eventos)}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error en tracking: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# Panel de Analytics (solo administradores)
# =============================================================================

@usage_tracker_bp.route('/')
@login_required
@admin_requerido
def dashboard():
    """Panel principal de analytics con estadísticas de uso."""
    # Obtener mes seleccionado o usar el actual
    mes = request.args.get('mes', datetime.now().strftime('%Y-%m'))
    pagina_filtro = request.args.get('pagina', '')

    # Meses disponibles para el selector
    meses_disponibles = EventoUso.meses_disponibles()
    if not meses_disponibles:
        meses_disponibles = [mes]

    # Estadísticas por página
    uso_paginas = EventoUso.estadisticas_paginas(mes)

    # Total de clics para calcular porcentajes
    total_clics = sum(p[1] for p in uso_paginas)

    # Estadísticas por elemento (top 50)
    uso_elementos = EventoUso.estadisticas_elementos(mes, limite=50)

    # Datos para heatmap
    heatmap_data = []
    if pagina_filtro:
        raw_data = EventoUso.datos_heatmap(mes, pagina_filtro)
        for row in raw_data:
            heatmap_data.append({
                'x': row[1],
                'y': row[2],
                'value': row[4]
            })

    # Lista de páginas para el selector de heatmap
    paginas = [p[0] for p in uso_paginas]

    return render_template('usage_tracker/analytics.html',
                           mes=mes,
                           meses_disponibles=meses_disponibles,
                           uso_paginas=uso_paginas,
                           uso_elementos=uso_elementos,
                           total_clics=total_clics,
                           heatmap_data=heatmap_data,
                           pagina_filtro=pagina_filtro,
                           paginas=paginas)


@usage_tracker_bp.route('/heatmap-data')
@login_required
@admin_requerido
def heatmap_data():
    """API para obtener datos de heatmap por página (AJAX)."""
    mes = request.args.get('mes', datetime.now().strftime('%Y-%m'))
    pagina = request.args.get('pagina', '')

    if not pagina:
        return jsonify({'data': [], 'max': 0})

    raw_data = EventoUso.datos_heatmap(mes, pagina)

    data = []
    max_count = 0
    for row in raw_data:
        count = row[4]
        if count > max_count:
            max_count = count
        data.append({
            'x': row[1],
            'y': row[2],
            'value': count
        })

    return jsonify({'data': data, 'max': max_count})


@usage_tracker_bp.route('/limpiar', methods=['POST'])
@login_required
@admin_requerido
def limpiar_antiguos():
    """Elimina datos de tracking más antiguos que N meses."""
    meses = request.form.get('meses', 6, type=int)

    try:
        eliminados = EventoUso.limpiar_antiguos(meses)
        return jsonify({
            'ok': True,
            'eliminados': eliminados,
            'mensaje': f'Se eliminaron {eliminados} registros antiguos'
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
