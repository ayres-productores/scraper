"""
Webhook para recibir eventos de WhatsApp Business API (Meta)

Este módulo maneja:
- Verificación del webhook (challenge de Meta)
- Validación de firma HMAC-SHA256 de Meta
- Eventos de estado de mensajes (sent, delivered, read)
"""

import hmac
import hashlib
import logging
from datetime import datetime
from flask import request, jsonify, current_app, abort
from app import db
from app.models import EnvioWhatsApp
from app.api.routes import api_bp
from app.utils.structured_logger import log_whatsapp, log_seguridad

logger = logging.getLogger(__name__)


def verificar_firma_meta(payload: bytes, signature_header: str, app_secret: str) -> bool:
    """
    Verifica la firma HMAC-SHA256 de Meta para webhooks.

    Meta firma cada webhook con el App Secret usando HMAC-SHA256.
    El header X-Hub-Signature-256 contiene: sha256=<firma_hexadecimal>

    Args:
        payload: Cuerpo del request en bytes (request.data)
        signature_header: Valor del header X-Hub-Signature-256
        app_secret: App Secret de la aplicación de Meta

    Returns:
        True si la firma es válida, False si no

    Nota de seguridad:
        Usa hmac.compare_digest() para evitar timing attacks.
    """
    if not signature_header or not signature_header.startswith('sha256='):
        return False

    # Extraer la firma del header (quitar prefijo 'sha256=')
    firma_recibida = signature_header[7:]

    # Calcular la firma esperada
    firma_esperada = hmac.new(
        app_secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    # Comparar de forma segura (timing-safe)
    return hmac.compare_digest(firma_esperada, firma_recibida)


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

    SEGURIDAD: Valida la firma HMAC-SHA256 de Meta antes de procesar.
    Sin esta validación, un atacante podría enviar webhooks falsos para:
    - Marcar pólizas como "definitivas" sin consentimiento del cliente
    - Inyectar datos falsos en el historial de comunicaciones

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
    # ================================================================
    # VALIDACIÓN DE FIRMA HMAC (Seguridad crítica)
    # ================================================================
    app_secret = current_app.config.get('WHATSAPP_APP_SECRET')
    signature = request.headers.get('X-Hub-Signature-256', '')

    if app_secret:
        # App Secret configurado - VALIDAR firma obligatoriamente
        if not verificar_firma_meta(request.data, signature, app_secret):
            # Firma inválida - posible ataque
            logger.warning(
                f"[Webhook] FIRMA INVÁLIDA - Posible ataque. "
                f"IP: {request.remote_addr}, "
                f"Signature: {signature[:20]}..." if signature else "sin firma"
            )

            # Log estructurado de seguridad
            log_seguridad('webhook_firma_invalida', 'error',
                          ip=request.remote_addr,
                          user_agent=request.headers.get('User-Agent', '')[:100],
                          signature_presente=bool(signature),
                          content_length=len(request.data))

            return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403
    else:
        # App Secret NO configurado - solo loguear advertencia
        # Esto permite que instalaciones existentes sigan funcionando
        # pero incentiva a configurar el App Secret
        if current_app.debug:
            logger.debug("[Webhook] WHATSAPP_APP_SECRET no configurado - firma NO validada")
        else:
            logger.warning(
                "[Webhook] WHATSAPP_APP_SECRET no configurado - webhook procesado SIN validar firma. "
                "Configure WHATSAPP_APP_SECRET para mayor seguridad."
            )

    # ================================================================
    # PROCESAMIENTO DEL WEBHOOK
    # ================================================================
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
        except (ValueError, TypeError, OSError):
            timestamp = datetime.utcnow()

    # Buscar el envío por wamid
    envio = EnvioWhatsApp.buscar_por_wamid(wamid)

    if not envio:
        logger.warning(f"[Webhook] Envío no encontrado para wamid: {wamid}")
        log_whatsapp('estado_mensaje', 'advertencia',
                     wamid=wamid,
                     estado_recibido=estado,
                     error='envio_no_encontrado')
        return

    # Actualizar estado
    estado_anterior = envio.estado_mensaje
    envio.actualizar_estado_mensaje(estado, timestamp)
    db.session.commit()

    logger.info(f"[Webhook] Estado actualizado - wamid: {wamid}, estado: {estado}")

    # Log estructurado: estado de mensaje actualizado
    log_whatsapp('estado_mensaje', 'exito',
                 wamid=wamid,
                 estado_anterior=estado_anterior,
                 estado_nuevo=estado,
                 cliente_id=envio.cliente_id,
                 envio_id=envio.id)

    # Log adicional si es lectura confirmada
    if estado == 'read':
        cliente_nombre = envio.cliente.nombre_completo if envio.cliente else 'Desconocido'
        logger.info(f"[Webhook] Mensaje leído por {cliente_nombre} - Póliza/Archivo marcados como definitivos")

        # Log estructurado: póliza confirmada automáticamente
        log_whatsapp('poliza_confirmada_auto', 'exito',
                     wamid=wamid,
                     cliente_id=envio.cliente_id,
                     cliente_nombre=cliente_nombre,
                     poliza_id=envio.poliza_cliente_id,
                     confirmado_por='whatsapp_read')
