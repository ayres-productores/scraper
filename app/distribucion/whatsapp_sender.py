"""
Motor de envío de mensajes por WhatsApp en segundo plano
Soporta WhatsApp Business API y servicios de terceros
"""

import urllib.parse
import requests
import os
import logging
from datetime import datetime
from threading import Thread, Lock
from time import sleep
from flask import current_app

logger = logging.getLogger(__name__)


class WhatsAppSender:
    """
    Motor de envío de mensajes WhatsApp.

    Modos de operación:
    - 'api': Usa WhatsApp Business API (envío automático en background)
    - 'manual': Genera enlaces wa.me para envío manual (fallback)
    """

    def __init__(self, config):
        self.modo = config.get('WHATSAPP_MODO', 'manual')
        self.api_key = config.get('WHATSAPP_API_KEY')
        self.phone_id = config.get('WHATSAPP_PHONE_ID')
        self.api_url = config.get('WHATSAPP_API_URL', 'https://graph.facebook.com/v17.0')

    def generar_enlace_manual(self, telefono, mensaje):
        """Genera un enlace wa.me para envío manual (fallback)."""
        telefono_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '')
        mensaje_codificado = urllib.parse.quote(mensaje)
        return f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"

    def enviar_mensaje_api(self, telefono, mensaje):
        """
        Envía un mensaje usando WhatsApp Business API.

        Returns:
            Tupla (éxito: bool, mensaje_o_error: str)
        """
        if not self.api_key or not self.phone_id:
            return False, "API de WhatsApp no configurada"

        telefono_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '')

        url = f"{self.api_url}/{self.phone_id}/messages"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': telefono_limpio,
            'type': 'text',
            'text': {
                'preview_url': False,
                'body': mensaje
            }
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                return True, data.get('messages', [{}])[0].get('id', 'OK')
            else:
                error = response.json().get('error', {}).get('message', response.text)
                return False, f"Error API: {error}"

        except requests.exceptions.Timeout:
            return False, "Timeout al conectar con la API"
        except requests.exceptions.RequestException as e:
            return False, f"Error de conexión: {str(e)}"
        except Exception as e:
            return False, f"Error inesperado: {str(e)}"

    def enviar_documento_api(self, telefono, documento_url, mensaje=None, nombre_archivo=None):
        """Envía un documento PDF usando WhatsApp Business API."""
        if not self.api_key or not self.phone_id:
            return False, "API de WhatsApp no configurada"

        telefono_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '')

        url = f"{self.api_url}/{self.phone_id}/messages"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': telefono_limpio,
            'type': 'document',
            'document': {
                'link': documento_url,
                'caption': mensaje or '',
                'filename': nombre_archivo or 'documento.pdf'
            }
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                return True, data.get('messages', [{}])[0].get('id', 'OK')
            else:
                error = response.json().get('error', {}).get('message', response.text)
                return False, f"Error API: {error}"

        except Exception as e:
            return False, f"Error: {str(e)}"

    def subir_media_api(self, ruta_archivo):
        """
        Sube un archivo (PDF) a WhatsApp Business API y retorna el media_id.

        Args:
            ruta_archivo: Ruta local al archivo PDF

        Returns:
            Tupla (éxito: bool, media_id_o_error: str)
        """
        if not self.api_key or not self.phone_id:
            return False, "API de WhatsApp no configurada"

        if not os.path.exists(ruta_archivo):
            return False, f"Archivo no encontrado: {ruta_archivo}"

        url = f"{self.api_url}/{self.phone_id}/media"
        headers = {
            'Authorization': f'Bearer {self.api_key}'
        }

        try:
            with open(ruta_archivo, 'rb') as f:
                files = {
                    'file': (os.path.basename(ruta_archivo), f, 'application/pdf'),
                    'messaging_product': (None, 'whatsapp'),
                    'type': (None, 'application/pdf')
                }
                response = requests.post(url, headers=headers, files=files, timeout=60)

            if response.status_code == 200:
                data = response.json()
                media_id = data.get('id')
                if media_id:
                    logger.info(f"[WhatsApp] Media subida: {media_id}")
                    return True, media_id
                return False, "No se obtuvo media_id"
            else:
                error = response.json().get('error', {}).get('message', response.text)
                return False, f"Error subiendo media: {error}"

        except requests.exceptions.Timeout:
            return False, "Timeout al subir archivo"
        except requests.exceptions.RequestException as e:
            return False, f"Error de conexión: {str(e)}"
        except Exception as e:
            return False, f"Error inesperado: {str(e)}"

    def enviar_documento_con_media_id(self, telefono, media_id, mensaje=None, nombre_archivo=None):
        """
        Envía un documento usando media_id (previamente subido).

        Args:
            telefono: Número de teléfono destino
            media_id: ID del media obtenido de subir_media_api()
            mensaje: Caption/mensaje que acompaña al documento
            nombre_archivo: Nombre del archivo a mostrar

        Returns:
            Tupla (éxito: bool, wamid_o_error: str)
        """
        if not self.api_key or not self.phone_id:
            return False, "API de WhatsApp no configurada"

        telefono_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '')

        url = f"{self.api_url}/{self.phone_id}/messages"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': telefono_limpio,
            'type': 'document',
            'document': {
                'id': media_id,
                'caption': mensaje or '',
                'filename': nombre_archivo or 'documento.pdf'
            }
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                wamid = data.get('messages', [{}])[0].get('id', 'OK')
                logger.info(f"[WhatsApp] Documento enviado: wamid={wamid}")
                return True, wamid
            else:
                error = response.json().get('error', {}).get('message', response.text)
                return False, f"Error API: {error}"

        except requests.exceptions.Timeout:
            return False, "Timeout al enviar documento"
        except requests.exceptions.RequestException as e:
            return False, f"Error de conexión: {str(e)}"
        except Exception as e:
            return False, f"Error inesperado: {str(e)}"

    def enviar_poliza_completa(self, telefono, ruta_pdf, mensaje, nombre_archivo=None):
        """
        Envía una póliza completa: sube el PDF y lo envía con mensaje.

        Args:
            telefono: Número de teléfono destino
            ruta_pdf: Ruta local al archivo PDF
            mensaje: Mensaje/caption a enviar con el documento
            nombre_archivo: Nombre del archivo a mostrar (opcional)

        Returns:
            Tupla (éxito: bool, wamid_o_error: str)
        """
        # Primero subir el PDF
        exito_subida, resultado_subida = self.subir_media_api(ruta_pdf)

        if not exito_subida:
            logger.warning(f"[WhatsApp] Fallo subida PDF, enviando solo texto: {resultado_subida}")
            # Fallback: enviar solo el mensaje de texto
            return self.enviar_mensaje_api(telefono, mensaje)

        media_id = resultado_subida

        # Enviar documento con el media_id
        return self.enviar_documento_con_media_id(
            telefono=telefono,
            media_id=media_id,
            mensaje=mensaje,
            nombre_archivo=nombre_archivo
        )

    def validar_telefono(self, telefono):
        """Valida el formato de un número de teléfono."""
        tel = telefono.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

        if tel.startswith('+'):
            tel_numeros = tel[1:]
        else:
            tel_numeros = tel

        if not tel_numeros.isdigit():
            return False, "El teléfono solo puede contener números"

        if len(tel_numeros) < 8:
            return False, "El teléfono es demasiado corto"
        if len(tel_numeros) > 15:
            return False, "El teléfono es demasiado largo"

        if not tel.startswith('+'):
            tel = '+' + tel

        return True, tel


# ============================================================================
# PROCESADOR DE COLA EN SEGUNDO PLANO
# ============================================================================

class WhatsAppQueueProcessor:
    """
    Procesador de cola de envíos de WhatsApp en segundo plano.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.running = False
        self.thread = None
        self.app = None
        self.intervalo_segundos = 5
        self.max_reintentos = 3

    def iniciar(self, app):
        """Inicia el procesador de cola."""
        if self.running:
            return

        self.app = app
        self.running = True
        self.thread = Thread(target=self._procesar_cola, daemon=True)
        self.thread.start()
        logger.info("[WhatsApp] Procesador de cola iniciado")

    def detener(self):
        """Detiene el procesador de cola."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _procesar_cola(self):
        """Bucle principal de procesamiento de cola."""
        while self.running:
            try:
                with self.app.app_context():
                    self._procesar_pendientes()
            except Exception as e:
                logger.error(f"[WhatsApp] Error en procesador: {e}")

            sleep(self.intervalo_segundos)

    def _procesar_pendientes(self):
        """Procesa los envíos pendientes."""
        from app import db
        from app.models import EnvioWhatsApp

        # Procesar envíos a clientes
        self._procesar_envios_clientes()

        # Procesar notificaciones a inmobiliarias
        self._procesar_notificaciones_inmobiliarias()

    def _enviar_via_servicio_web(self, usuario_id, telefono, mensaje, ruta_pdf=None, nombre_pdf=None):
        """
        Envía un mensaje usando el servicio de WhatsApp Web (sesión personal).

        Returns:
            Tupla (éxito: bool, resultado_o_error: str)
        """
        service_url = self.app.config.get('WHATSAPP_SERVICE_URL', 'http://localhost:3001')
        timeout = self.app.config.get('WHATSAPP_SERVICE_TIMEOUT', 30)

        try:
            telefono_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '')

            if ruta_pdf and os.path.exists(ruta_pdf):
                # Enviar documento con mensaje
                response = requests.post(
                    f"{service_url}/session/{usuario_id}/send-document",
                    json={
                        'phone': telefono_limpio,
                        'filePath': ruta_pdf,
                        'filename': nombre_pdf or 'documento.pdf',
                        'caption': mensaje
                    },
                    timeout=timeout
                )
            else:
                # Enviar solo texto
                response = requests.post(
                    f"{service_url}/session/{usuario_id}/send",
                    json={
                        'phone': telefono_limpio,
                        'message': mensaje
                    },
                    timeout=timeout
                )

            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    return True, data.get('messageId', 'OK')
                else:
                    return False, data.get('error', 'Error desconocido')
            else:
                return False, f"Error HTTP {response.status_code}"

        except requests.exceptions.ConnectionError:
            return False, "Servicio WhatsApp Web no disponible"
        except requests.exceptions.Timeout:
            return False, "Timeout conectando al servicio"
        except Exception as e:
            return False, str(e)

    def _verificar_sesion_web_activa(self, usuario_id):
        """Verifica si el usuario tiene una sesión de WhatsApp Web activa."""
        from app.models import WhatsAppSession

        session = WhatsAppSession.query.filter_by(
            usuario_id=usuario_id,
            estado='ready',
            activo=True
        ).first()

        return session is not None

    def _procesar_envios_clientes(self):
        """Procesa los envíos pendientes a clientes."""
        from app import db
        from app.models import EnvioWhatsApp, WhatsAppSession

        # Obtener envíos pendientes
        pendientes = EnvioWhatsApp.query.filter_by(estado='pendiente').filter(
            EnvioWhatsApp.intentos < self.max_reintentos
        ).order_by(EnvioWhatsApp.id).limit(10).all()

        if not pendientes:
            return

        sender = WhatsAppSender(self.app.config)

        for envio in pendientes:
            if not self.running:
                break

            try:
                cliente = envio.cliente
                telefono = cliente.telefono_formateado
                usuario_id = cliente.usuario_id

                # Obtener datos del PDF si existe
                ruta_pdf = None
                nombre_pdf = None

                if envio.poliza:
                    poliza = envio.poliza
                    if poliza.ruta_pdf_backup and os.path.exists(poliza.ruta_pdf_backup):
                        ruta_pdf = poliza.ruta_pdf_backup
                        nombre_pdf = f"Poliza_{poliza.numero_poliza or poliza.id}.pdf"
                    elif envio.archivo and envio.archivo.ruta_archivo:
                        if os.path.exists(envio.archivo.ruta_archivo):
                            ruta_pdf = envio.archivo.ruta_archivo
                            nombre_pdf = envio.archivo.nombre_archivo or f"Poliza_{poliza.id}.pdf"

                # PRIORIDAD 1: Sesión personal de WhatsApp Web
                if self._verificar_sesion_web_activa(usuario_id):
                    logger.info(f"[WhatsApp] Usando sesión personal del usuario {usuario_id}")

                    exito, resultado = self._enviar_via_servicio_web(
                        usuario_id=usuario_id,
                        telefono=telefono,
                        mensaje=envio.mensaje_enviado,
                        ruta_pdf=ruta_pdf,
                        nombre_pdf=nombre_pdf
                    )

                    if exito:
                        envio.estado = 'enviado'
                        envio.fecha_envio = datetime.utcnow()
                        envio.estado_mensaje = 'sent'
                        if resultado and resultado != 'OK':
                            envio.wamid = resultado
                        cliente.ultimo_envio = datetime.utcnow()

                        # Actualizar último uso de la sesión
                        wa_session = WhatsAppSession.query.filter_by(usuario_id=usuario_id).first()
                        if wa_session:
                            wa_session.actualizar_uso()

                        logger.info(f"[WhatsApp-Web] Enviado a {cliente.nombre_completo}: {resultado}")
                    else:
                        envio.intentos += 1
                        envio.mensaje_error = f"WhatsApp Web: {resultado}"
                        if envio.intentos >= self.max_reintentos:
                            envio.estado = 'error'
                        logger.warning(f"[WhatsApp-Web] Error enviando a {cliente.nombre_completo}: {resultado}")

                # PRIORIDAD 2: WhatsApp Business API (central)
                elif sender.modo == 'api' and sender.api_key:
                    if ruta_pdf:
                        logger.info(f"[WhatsApp-API] Enviando póliza con PDF a {cliente.nombre_completo}")
                        exito, resultado = sender.enviar_poliza_completa(
                            telefono=telefono,
                            ruta_pdf=ruta_pdf,
                            mensaje=envio.mensaje_enviado,
                            nombre_archivo=nombre_pdf
                        )
                    else:
                        logger.info(f"[WhatsApp-API] Enviando solo texto a {cliente.nombre_completo}")
                        exito, resultado = sender.enviar_mensaje_api(telefono, envio.mensaje_enviado)

                    if exito:
                        envio.estado = 'enviado'
                        envio.fecha_envio = datetime.utcnow()
                        envio.estado_mensaje = 'sent'
                        if resultado and resultado != 'OK':
                            envio.wamid = resultado
                        cliente.ultimo_envio = datetime.utcnow()
                        logger.info(f"[WhatsApp-API] Enviado a {cliente.nombre_completo}: wamid={resultado}")
                    else:
                        envio.intentos += 1
                        envio.mensaje_error = resultado
                        if envio.intentos >= self.max_reintentos:
                            envio.estado = 'error'
                        logger.warning(f"[WhatsApp-API] Error enviando a {cliente.nombre_completo}: {resultado}")

                # PRIORIDAD 3: Modo manual (fallback)
                else:
                    envio.estado = 'enviado'
                    envio.fecha_envio = datetime.utcnow()
                    cliente.ultimo_envio = datetime.utcnow()
                    logger.info(f"[WhatsApp-Manual] Marcado para envío manual: {cliente.nombre_completo}")

                db.session.commit()

                # Rate limiting: esperar entre envíos
                sleep(1)

            except Exception as e:
                envio.intentos += 1
                envio.mensaje_error = str(e)
                if envio.intentos >= self.max_reintentos:
                    envio.estado = 'error'
                db.session.commit()
                logger.error(f"[WhatsApp] Excepción: {e}")

    def _procesar_notificaciones_inmobiliarias(self):
        """Procesa las notificaciones pendientes a inmobiliarias."""
        from app import db
        from app.models import NotificacionInmobiliaria

        # Obtener notificaciones pendientes
        pendientes = NotificacionInmobiliaria.query.filter_by(estado='pendiente').filter(
            NotificacionInmobiliaria.intentos < self.max_reintentos
        ).order_by(NotificacionInmobiliaria.id).limit(10).all()

        if not pendientes:
            return

        sender = WhatsAppSender(self.app.config)

        for notif in pendientes:
            if not self.running:
                break

            try:
                inmobiliaria = notif.inmobiliaria
                if not inmobiliaria or not inmobiliaria.telefono_whatsapp:
                    notif.estado = 'error'
                    notif.mensaje_error = 'Inmobiliaria sin telefono WhatsApp'
                    db.session.commit()
                    continue

                telefono = inmobiliaria.telefono_formateado

                # Enviar mensaje
                if sender.modo == 'api' and sender.api_key:
                    exito, resultado = sender.enviar_mensaje_api(telefono, notif.mensaje)

                    if exito:
                        notif.marcar_enviado()
                        logger.info(f"[WhatsApp-Inmob] Enviado a {inmobiliaria.nombre}: {notif.tipo}")
                    else:
                        notif.intentos += 1
                        notif.mensaje_error = resultado
                        if notif.intentos >= self.max_reintentos:
                            notif.estado = 'error'
                        logger.warning(f"[WhatsApp-Inmob] Error enviando a {inmobiliaria.nombre}: {resultado}")
                else:
                    # Modo manual - marcar como enviado
                    notif.marcar_enviado()

                db.session.commit()

                # Rate limiting
                sleep(1)

            except Exception as e:
                notif.intentos += 1
                notif.mensaje_error = str(e)
                if notif.intentos >= self.max_reintentos:
                    notif.estado = 'error'
                db.session.commit()
                logger.error(f"[WhatsApp-Inmob] Excepción: {e}")


# Instancia global del procesador
queue_processor = WhatsAppQueueProcessor()


def iniciar_procesador_whatsapp(app):
    """Función helper para iniciar el procesador desde la app."""
    queue_processor.iniciar(app)
