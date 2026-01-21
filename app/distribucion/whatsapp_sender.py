"""
Motor de envío de mensajes por WhatsApp en segundo plano
Soporta WhatsApp Business API y servicios de terceros
"""

import urllib.parse
import requests
import os
from datetime import datetime
from threading import Thread, Lock
from time import sleep
from flask import current_app


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
        print("  [WhatsApp] Procesador de cola iniciado")

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
                print(f"  [WhatsApp] Error en procesador: {e}")

            sleep(self.intervalo_segundos)

    def _procesar_pendientes(self):
        """Procesa los envíos pendientes."""
        from app import db
        from app.models import EnvioWhatsApp

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

                # Enviar mensaje
                if sender.modo == 'api' and sender.api_key:
                    exito, resultado = sender.enviar_mensaje_api(telefono, envio.mensaje_enviado)

                    if exito:
                        envio.estado = 'enviado'
                        envio.fecha_envio = datetime.utcnow()
                        cliente.ultimo_envio = datetime.utcnow()
                        print(f"  [WhatsApp] Enviado a {cliente.nombre_completo}: {resultado}")
                    else:
                        envio.intentos += 1
                        envio.mensaje_error = resultado
                        if envio.intentos >= self.max_reintentos:
                            envio.estado = 'error'
                        print(f"  [WhatsApp] Error enviando a {cliente.nombre_completo}: {resultado}")
                else:
                    # Modo manual - marcar como enviado (el usuario usará el enlace)
                    envio.estado = 'enviado'
                    envio.fecha_envio = datetime.utcnow()
                    cliente.ultimo_envio = datetime.utcnow()

                db.session.commit()

                # Rate limiting: esperar entre envíos
                sleep(1)

            except Exception as e:
                envio.intentos += 1
                envio.mensaje_error = str(e)
                if envio.intentos >= self.max_reintentos:
                    envio.estado = 'error'
                db.session.commit()
                print(f"  [WhatsApp] Excepción: {e}")


# Instancia global del procesador
queue_processor = WhatsAppQueueProcessor()


def iniciar_procesador_whatsapp(app):
    """Función helper para iniciar el procesador desde la app."""
    queue_processor.iniciar(app)
