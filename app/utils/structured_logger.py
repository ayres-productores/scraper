"""
Logging estructurado para operaciones críticas del sistema.

Este módulo proporciona funciones para registrar eventos en formato JSON
estructurado, facilitando el análisis y diagnóstico de problemas.

Categorías de eventos:
- extraccion: Operaciones del motor de extracción de PDFs
- whatsapp: Envíos, webhooks y estados de mensajes
- bd: Operaciones de base de datos críticas
- seguridad: Intentos de acceso, firmas inválidas, etc.

Uso:
    from app.utils.structured_logger import log_operacion, get_operations_logger

    # Log simple
    log_operacion('extraccion', 'pdf_guardado', 'exito', archivo='poliza.pdf', hash='abc123')

    # Log con contexto completo
    log_operacion(
        categoria='whatsapp',
        accion='webhook_recibido',
        resultado='exito',
        wamid='wamid.xxx',
        estado='delivered',
        cliente_id=123
    )
"""

import json
import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from threading import current_thread

# Detectar directorio base
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Directorio de logs
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
OPERATIONS_LOG_FILE = os.path.join(LOGS_DIR, 'operaciones.log')

# Crear directorio de logs si no existe
os.makedirs(LOGS_DIR, exist_ok=True)

# Logger específico para operaciones estructuradas
_operations_logger = None


class StructuredFormatter(logging.Formatter):
    """
    Formatter que genera logs en formato JSON estructurado.

    Cada línea es un objeto JSON válido, facilitando el parseo con herramientas
    como jq, Elasticsearch, etc.
    """

    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'categoria': getattr(record, 'categoria', 'general'),
            'accion': getattr(record, 'accion', 'log'),
            'resultado': getattr(record, 'resultado', 'info'),
            'mensaje': record.getMessage(),
            'thread': current_thread().name,
        }

        # Agregar contexto adicional si existe
        if hasattr(record, 'contexto') and record.contexto:
            log_data['contexto'] = record.contexto

        # Agregar información de excepción si existe
        if record.exc_info:
            log_data['excepcion'] = self.formatException(record.exc_info)

        # Agregar usuario si está disponible
        if hasattr(record, 'usuario_id'):
            log_data['usuario_id'] = record.usuario_id

        return json.dumps(log_data, ensure_ascii=False, default=str)


def get_operations_logger():
    """
    Obtiene el logger de operaciones estructuradas.

    Configura el logger con:
    - Rotación diaria de archivos
    - Retención de 30 días
    - Formato JSON estructurado

    Returns:
        logging.Logger configurado
    """
    global _operations_logger

    if _operations_logger is not None:
        return _operations_logger

    _operations_logger = logging.getLogger('portal_seguros.operaciones')
    _operations_logger.setLevel(logging.DEBUG)

    # Evitar duplicar handlers si ya existen
    if _operations_logger.handlers:
        return _operations_logger

    # Handler de archivo con rotación diaria
    try:
        file_handler = TimedRotatingFileHandler(
            OPERATIONS_LOG_FILE,
            when='midnight',
            interval=1,
            backupCount=30,  # Retener 30 días
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredFormatter())
        _operations_logger.addHandler(file_handler)
    except Exception as e:
        # Si falla la creación del archivo, usar stderr
        print(f"[WARNING] No se pudo crear log de operaciones: {e}", file=sys.stderr)
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(StructuredFormatter())
        _operations_logger.addHandler(console_handler)

    # No propagar al logger raíz para evitar duplicados
    _operations_logger.propagate = False

    return _operations_logger


def log_operacion(categoria: str, accion: str, resultado: str, **contexto):
    """
    Registra una operación en el log estructurado.

    Args:
        categoria: Categoría del evento. Valores recomendados:
            - 'extraccion': Motor de extracción de PDFs
            - 'whatsapp': Envíos y webhooks
            - 'bd': Operaciones de base de datos
            - 'seguridad': Eventos de seguridad

        accion: Acción específica. Ejemplos:
            - 'escaneo_iniciado', 'pdf_guardado', 'correo_procesado'
            - 'mensaje_enviado', 'webhook_recibido', 'estado_actualizado'
            - 'firma_invalida', 'acceso_denegado'

        resultado: Resultado de la operación:
            - 'inicio': Operación iniciada
            - 'exito': Operación exitosa
            - 'error': Operación falló
            - 'advertencia': Completó con advertencias

        **contexto: Datos adicionales relevantes. Ejemplos:
            - archivo='poliza.pdf'
            - hash='abc123'
            - usuario_id=1
            - cliente_id=123
            - wamid='wamid.xxx'
            - ip='192.168.1.1'
            - duracion_ms=150

    Ejemplo:
        log_operacion(
            'extraccion',
            'pdf_guardado',
            'exito',
            archivo='poliza.pdf',
            hash='abc123',
            compania='Liderar',
            tamano_bytes=150000
        )
    """
    logger = get_operations_logger()

    # Determinar nivel de log según resultado
    level_map = {
        'inicio': logging.INFO,
        'exito': logging.INFO,
        'error': logging.ERROR,
        'advertencia': logging.WARNING,
    }
    level = level_map.get(resultado, logging.INFO)

    # Crear mensaje descriptivo
    mensaje = f"[{categoria.upper()}] {accion}: {resultado}"

    # Crear record extra
    extra = {
        'categoria': categoria,
        'accion': accion,
        'resultado': resultado,
        'contexto': contexto if contexto else None,
    }

    # Extraer usuario_id si está en contexto
    if 'usuario_id' in contexto:
        extra['usuario_id'] = contexto['usuario_id']

    logger.log(level, mensaje, extra=extra)


def log_extraccion(accion: str, resultado: str, **contexto):
    """Shortcut para logs de extracción."""
    log_operacion('extraccion', accion, resultado, **contexto)


def log_whatsapp(accion: str, resultado: str, **contexto):
    """Shortcut para logs de WhatsApp."""
    log_operacion('whatsapp', accion, resultado, **contexto)


def log_seguridad(accion: str, resultado: str, **contexto):
    """Shortcut para logs de seguridad."""
    log_operacion('seguridad', accion, resultado, **contexto)


def log_bd(accion: str, resultado: str, **contexto):
    """Shortcut para logs de base de datos."""
    log_operacion('bd', accion, resultado, **contexto)
