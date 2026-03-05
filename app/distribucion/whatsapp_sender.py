"""
Motor de envío de mensajes por WhatsApp en segundo plano.

Usa el servicio whatsapp-service-standalone (localhost:3001) para envío automático.
Fallback a enlaces wa.me para envío manual cuando no hay sesión activa.
"""

import urllib.parse
import requests
import os
import logging
from datetime import datetime
from threading import Thread, Lock
from time import sleep
from flask import current_app

# Importar gestión de sesiones thread-safe
from app.utils.db_session import thread_session

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
        """Bucle principal de procesamiento de cola.

        IMPORTANTE: Usa sesiones CORTAS para no bloquear la BD durante
        operaciones lentas (HTTP calls a WhatsApp, sleeps).
        """
        while self.running:
            try:
                # Procesar envíos a clientes (sesiones cortas internas)
                self._procesar_envios_clientes()

                # Procesar notificaciones a inmobiliarias (sesiones cortas internas)
                self._procesar_notificaciones_inmobiliarias()

            except Exception as e:
                logger.error(f"[WhatsApp] Error en procesador: {e}")

            sleep(self.intervalo_segundos)

    def _enviar_via_api(self, usuario_id, telefono, mensaje, ruta_pdf=None, nombre_pdf=None):
        """
        Envía un mensaje usando el servicio API de WhatsApp (whatsapp-service-standalone).

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
            return False, "Servicio API de WhatsApp no disponible"
        except requests.exceptions.Timeout:
            return False, "Timeout conectando al servicio"
        except Exception as e:
            return False, str(e)

    def _verificar_sesion_api_activa(self, usuario_id):
        """Verifica si el usuario tiene una sesión API de WhatsApp activa."""
        from app.models import WhatsAppSession

        try:
            with thread_session(self.app) as session:
                wa_session = session.query(WhatsAppSession).filter_by(
                    usuario_id=usuario_id,
                    estado='ready',
                    activo=True
                ).first()
                return wa_session is not None
        except Exception:
            return False

    def _procesar_envios_clientes(self):
        """Procesa los envíos pendientes a clientes.

        IMPORTANTE: Usa sesiones CORTAS para no bloquear la BD.
        1. Lee pendientes (sesión corta)
        2. Cierra sesión
        3. Hace HTTP calls (sin sesión)
        4. Actualiza estado (sesión corta por cada update)
        """
        from app.models import EnvioWhatsApp, WhatsAppSession

        # PASO 1: Leer pendientes con sesión corta
        pendientes_data = []
        try:
            with thread_session(self.app) as session:
                pendientes = session.query(EnvioWhatsApp).filter_by(estado='pendiente').filter(
                    EnvioWhatsApp.intentos < self.max_reintentos
                ).order_by(EnvioWhatsApp.id).limit(10).all()

                # Extraer datos ANTES de cerrar sesión
                for envio in pendientes:
                    try:
                        data = {
                            'envio_id': envio.id,
                            'cliente_id': envio.cliente_id,
                            'cliente_nombre': envio.cliente.nombre_completo if envio.cliente else 'Desconocido',
                            'telefono': envio.cliente.telefono_formateado if envio.cliente else None,
                            'usuario_id': envio.cliente.usuario_id if envio.cliente else None,
                            'mensaje': envio.mensaje_enviado,
                            'intentos': envio.intentos,
                            'ruta_pdf': None,
                            'nombre_pdf': None,
                        }

                        if envio.poliza:
                            if envio.poliza.ruta_pdf_backup and os.path.exists(envio.poliza.ruta_pdf_backup):
                                data['ruta_pdf'] = envio.poliza.ruta_pdf_backup
                                data['nombre_pdf'] = f"Poliza_{envio.poliza.numero_poliza or envio.poliza.id}.pdf"
                            elif envio.archivo and envio.archivo.ruta_archivo:
                                if os.path.exists(envio.archivo.ruta_archivo):
                                    data['ruta_pdf'] = envio.archivo.ruta_archivo
                                    data['nombre_pdf'] = envio.archivo.nombre_archivo or f"Poliza_{envio.poliza.id}.pdf"

                        pendientes_data.append(data)
                    except Exception as e:
                        logger.warning(f"[WhatsApp] Error extrayendo datos envío {envio.id}: {e}")

        except Exception as e:
            logger.error(f"[WhatsApp] Error leyendo pendientes: {e}")
            return

        if not pendientes_data:
            return

        # PASO 2: Procesar cada envío (HTTP calls FUERA de sesión)
        sender = WhatsAppSender(self.app.config)

        for data in pendientes_data:
            if not self.running:
                break

            if not data['telefono']:
                continue

            try:
                exito = False
                resultado = None
                metodo = 'manual'

                # Verificar si hay sesión API activa
                if self._verificar_sesion_api_activa(data['usuario_id']):
                    metodo = 'api'
                    if data['ruta_pdf']:
                        logger.info(f"[WhatsApp-API] Enviando documento a {data['cliente_nombre']}")
                    else:
                        logger.info(f"[WhatsApp-API] Enviando mensaje a {data['cliente_nombre']}")

                    exito, resultado = self._enviar_via_api(
                        usuario_id=data['usuario_id'],
                        telefono=data['telefono'],
                        mensaje=data['mensaje'],
                        ruta_pdf=data['ruta_pdf'],
                        nombre_pdf=data['nombre_pdf']
                    )

                # Sin sesión API: modo manual (no se envía automáticamente)
                else:
                    logger.warning(f"[WhatsApp] Sin sesión API activa para usuario {data['usuario_id']}")
                    exito = False
                    resultado = 'Sin sesión API activa'

                # PASO 3: Actualizar estado con sesión corta
                self._actualizar_envio_cliente(
                    envio_id=data['envio_id'],
                    cliente_id=data['cliente_id'],
                    usuario_id=data['usuario_id'],
                    exito=exito,
                    resultado=resultado,
                    metodo=metodo,
                    intentos=data['intentos'],
                    cliente_nombre=data['cliente_nombre']
                )

                # Rate limiting
                sleep(1)

            except Exception as e:
                logger.error(f"[WhatsApp] Excepción procesando envío {data['envio_id']}: {e}")
                self._marcar_error_envio(data['envio_id'], str(e), data['intentos'])

    def _actualizar_envio_cliente(self, envio_id, cliente_id, usuario_id, exito, resultado, metodo, intentos, cliente_nombre):
        """Actualiza el estado de un envío con sesión corta."""
        from app.models import EnvioWhatsApp, Cliente, WhatsAppSession

        try:
            with thread_session(self.app) as session:
                envio = session.query(EnvioWhatsApp).get(envio_id)
                if not envio:
                    return

                cliente = session.query(Cliente).get(cliente_id) if cliente_id else None

                if exito:
                    envio.estado = 'enviado'
                    envio.fecha_envio = datetime.utcnow()
                    envio.estado_mensaje = 'sent'
                    if resultado and resultado not in ('OK', 'manual'):
                        envio.wamid = resultado

                    if cliente:
                        cliente.ultimo_envio = datetime.utcnow()

                    # Actualizar último uso de sesión API
                    if metodo == 'api' and usuario_id:
                        wa_session = session.query(WhatsAppSession).filter_by(usuario_id=usuario_id).first()
                        if wa_session:
                            wa_session.ultimo_uso = datetime.utcnow()

                    logger.info(f"[WhatsApp-API] Enviado a {cliente_nombre}: {resultado}")
                else:
                    envio.intentos = intentos + 1
                    envio.mensaje_error = f"{metodo}: {resultado}"
                    if envio.intentos >= self.max_reintentos:
                        envio.estado = 'error'
                    logger.warning(f"[WhatsApp-{metodo.upper()}] Error enviando a {cliente_nombre}: {resultado}")

        except Exception as e:
            logger.error(f"[WhatsApp] Error actualizando envío {envio_id}: {e}")

    def _marcar_error_envio(self, envio_id, error_msg, intentos):
        """Marca un envío como error con sesión corta."""
        from app.models import EnvioWhatsApp

        try:
            with thread_session(self.app) as session:
                envio = session.query(EnvioWhatsApp).get(envio_id)
                if envio:
                    envio.intentos = intentos + 1
                    envio.mensaje_error = error_msg
                    if envio.intentos >= self.max_reintentos:
                        envio.estado = 'error'
        except Exception as e:
            logger.error(f"[WhatsApp] Error marcando error en envío {envio_id}: {e}")

    def _procesar_notificaciones_inmobiliarias(self):
        """Procesa las notificaciones pendientes a inmobiliarias.

        IMPORTANTE: Usa sesiones CORTAS para no bloquear la BD.
        """
        from app.models import NotificacionInmobiliaria

        # PASO 1: Leer pendientes con sesión corta
        pendientes_data = []
        try:
            with thread_session(self.app) as session:
                pendientes = session.query(NotificacionInmobiliaria).filter_by(estado='pendiente').filter(
                    NotificacionInmobiliaria.intentos < self.max_reintentos
                ).order_by(NotificacionInmobiliaria.id).limit(10).all()

                for notif in pendientes:
                    try:
                        inmobiliaria = notif.inmobiliaria
                        data = {
                            'notif_id': notif.id,
                            'tipo': notif.tipo,
                            'mensaje': notif.mensaje,
                            'intentos': notif.intentos,
                            'telefono': inmobiliaria.telefono_formateado if inmobiliaria and inmobiliaria.telefono_whatsapp else None,
                            'inmobiliaria_nombre': inmobiliaria.nombre if inmobiliaria else 'Desconocida',
                        }
                        pendientes_data.append(data)
                    except Exception as e:
                        logger.warning(f"[WhatsApp-Inmob] Error extrayendo datos notif {notif.id}: {e}")

        except Exception as e:
            logger.error(f"[WhatsApp-Inmob] Error leyendo pendientes: {e}")
            return

        if not pendientes_data:
            return

        # PASO 2: Procesar cada notificación
        sender = WhatsAppSender(self.app.config)

        for data in pendientes_data:
            if not self.running:
                break

            # Si no tiene teléfono, marcar error
            if not data['telefono']:
                self._marcar_error_notif(data['notif_id'], 'Inmobiliaria sin telefono WhatsApp', data['intentos'])
                continue

            try:
                exito = False
                resultado = None

                # Enviar mensaje
                if sender.modo == 'api' and sender.api_key:
                    exito, resultado = sender.enviar_mensaje_api(data['telefono'], data['mensaje'])
                else:
                    # Modo manual
                    exito = True
                    resultado = 'manual'

                # PASO 3: Actualizar con sesión corta
                self._actualizar_notificacion(
                    notif_id=data['notif_id'],
                    exito=exito,
                    resultado=resultado,
                    intentos=data['intentos'],
                    inmobiliaria_nombre=data['inmobiliaria_nombre'],
                    tipo=data['tipo']
                )

                # Rate limiting
                sleep(1)

            except Exception as e:
                logger.error(f"[WhatsApp-Inmob] Excepción procesando notif {data['notif_id']}: {e}")
                self._marcar_error_notif(data['notif_id'], str(e), data['intentos'])

    def _actualizar_notificacion(self, notif_id, exito, resultado, intentos, inmobiliaria_nombre, tipo):
        """Actualiza el estado de una notificación con sesión corta."""
        from app.models import NotificacionInmobiliaria

        try:
            with thread_session(self.app) as session:
                notif = session.query(NotificacionInmobiliaria).get(notif_id)
                if not notif:
                    return

                if exito:
                    notif.estado = 'enviado'
                    notif.fecha_envio = datetime.utcnow()
                    logger.info(f"[WhatsApp-Inmob] Enviado a {inmobiliaria_nombre}: {tipo}")
                else:
                    notif.intentos = intentos + 1
                    notif.mensaje_error = resultado
                    if notif.intentos >= self.max_reintentos:
                        notif.estado = 'error'
                    logger.warning(f"[WhatsApp-Inmob] Error enviando a {inmobiliaria_nombre}: {resultado}")

        except Exception as e:
            logger.error(f"[WhatsApp-Inmob] Error actualizando notif {notif_id}: {e}")

    def _marcar_error_notif(self, notif_id, error_msg, intentos):
        """Marca una notificación como error con sesión corta."""
        from app.models import NotificacionInmobiliaria

        try:
            with thread_session(self.app) as session:
                notif = session.query(NotificacionInmobiliaria).get(notif_id)
                if notif:
                    notif.intentos = intentos + 1
                    notif.mensaje_error = error_msg
                    if notif.intentos >= self.max_reintentos:
                        notif.estado = 'error'
        except Exception as e:
            logger.error(f"[WhatsApp-Inmob] Error marcando error en notif {notif_id}: {e}")


# Instancia global del procesador
queue_processor = WhatsAppQueueProcessor()


def iniciar_procesador_whatsapp(app):
    """Función helper para iniciar el procesador desde la app."""
    queue_processor.iniciar(app)
