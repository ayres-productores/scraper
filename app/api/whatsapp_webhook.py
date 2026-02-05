"""
Webhook para recibir eventos de WhatsApp Business API (Meta)

Este módulo maneja:
- Verificación del webhook (challenge de Meta)
- Eventos de estado de mensajes (sent, delivered, read)
"""

import logging
from datetime import datetime
from flask import request, jsonify, current_app
from app import db
from app.models import EnvioWhatsApp
from app.api.routes import api_bp

logger = logging.getLogger(__name__)


@api_bp.route('/whatsapp/webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    """
    Endpoint webhook para WhatsApp Business API.

    GET: Verificación del webhook (Meta challenge)
    POST: Recibir eventos de estado de mensajes
    """
    if request.method == 'GET':
        return verificar_webhook()
    else:
        return procesar_evento_whatsapp()


def verificar_webhook():
    """
    Verifica el webhook con Meta (challenge-response).

    Meta envía:
    - hub.mode: 'subscribe'
    - hub.verify_token: token configurado en Meta
    - hub.challenge: string a devolver
    """
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    verify_token = current_app.config.get('WHATSAPP_VERIFY_TOKEN', 'mi_token_verificacion')

    if mode == 'subscribe' and token == verify_token:
        logger.info("[Webhook] Verificación exitosa")
        return challenge, 200
    else:
        logger.warning(f"[Webhook] Verificación fallida - mode: {mode}, token válido: {token == verify_token}")
        return 'Forbidden', 403


def procesar_evento_whatsapp():
    """
    Procesa eventos de estado de mensajes de WhatsApp.

    Formato esperado de Meta:
    {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {...},
                    "statuses": [{
                        "id": "wamid.xxx",
                        "status": "sent|delivered|read|failed",
                        "timestamp": "1234567890",
                        "recipient_id": "5491155551234"
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'status': 'error', 'message': 'No data'}), 400

        # Verificar que es un evento de WhatsApp Business
        if data.get('object') != 'whatsapp_business_account':
            return jsonify({'status': 'ignored'}), 200

        # Procesar cada entrada
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})

                # Procesar estados de mensajes
                for status in value.get('statuses', []):
                    procesar_estado_mensaje(status)

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        logger.error(f"[Webhook] Error procesando evento: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


def procesar_estado_mensaje(status):
    """
    Procesa un evento de estado individual.

    Estados posibles:
    - sent: Mensaje enviado al servidor de WhatsApp
    - delivered: Mensaje entregado al dispositivo del destinatario
    - read: Mensaje leído por el destinatario
    - failed: Error en el envío
    """
    wamid = status.get('id')
    estado = status.get('status')
    timestamp_str = status.get('timestamp')

    if not wamid or not estado:
        return

    # Convertir timestamp
    timestamp = None
    if timestamp_str:
        try:
            timestamp = datetime.fromtimestamp(int(timestamp_str))
        except:
            timestamp = datetime.utcnow()

    # Buscar el envío por wamid
    envio = EnvioWhatsApp.buscar_por_wamid(wamid)

    if not envio:
        logger.warning(f"[Webhook] Envío no encontrado para wamid: {wamid}")
        return

    # Actualizar estado
    envio.actualizar_estado_mensaje(estado, timestamp)
    db.session.commit()

    logger.info(f"[Webhook] Estado actualizado - wamid: {wamid}, estado: {estado}")

    # Log adicional si es lectura confirmada
    if estado == 'read':
        cliente_nombre = envio.cliente.nombre_completo if envio.cliente else 'Desconocido'
        logger.info(f"[Webhook] Mensaje leído por {cliente_nombre} - Póliza/Archivo marcados como definitivos")
