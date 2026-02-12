"""
Motor de extracción de PDFs adaptado para uso web
Soporta escaneo multi-cuenta
"""

import imaplib
import email
from email.header import decode_header
import os
import hashlib
import re
import requests
import tempfile
import logging
import socket
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Thread, Event
from time import sleep
from flask import current_app

# Importar gestión de sesiones thread-safe
from app.utils.db_session import thread_session
# Importar logging estructurado
from app.utils.structured_logger import log_extraccion
# Importar logger detallado de escaneo
from app.utils.scan_logger import ScanLogger, close_scan_logger
# Importar buffer JSON para evitar bloqueos de BD
from app.utils.scan_buffer import ScanBuffer
# Importar patrón State para gestión de ciclo de vida
from app.extractor.scan_state import ScanStateContext

logger = logging.getLogger(__name__)

# Importar sistema de estrategias por compañía
try:
    from app.extractor.companias import obtener_estrategia, obtener_compania
    ESTRATEGIAS_DISPONIBLES = True
except ImportError:
    ESTRATEGIAS_DISPONIBLES = False
    obtener_estrategia = None
    obtener_compania = None

# Importar detector de compañía por contenido del PDF
try:
    from app.extractor.detector_compania import detectar_compania_en_pdf, obtener_detector
    DETECTOR_COMPANIA_DISPONIBLE = True
except ImportError:
    DETECTOR_COMPANIA_DISPONIBLE = False
    detectar_compania_en_pdf = None
    obtener_detector = None


# ============================================================================
# CONTEXT MANAGER PARA CONEXIONES IMAP SEGURAS
# ============================================================================

class IMAPConnectionManager:
    """
    Context manager para conexiones IMAP con timeout y cierre garantizado.

    Resuelve dos problemas críticos:
    1. Sin timeout: conexiones que quedan bloqueadas indefinidamente
    2. Sin cierre: leak de conexiones cuando hay excepciones

    Uso:
        with IMAPConnectionManager('imap.gmail.com', 993, timeout=60) as imap:
            imap.login(correo, password)
            # ... operaciones IMAP ...
        # Conexión cerrada automáticamente (éxito o error)
    """

    DEFAULT_TIMEOUT = 60  # segundos

    def __init__(self, servidor, puerto, timeout=None, logger_func=None):
        """
        Args:
            servidor: Servidor IMAP (ej: 'imap.gmail.com')
            puerto: Puerto IMAP (ej: 993 para SSL)
            timeout: Timeout en segundos (default: 60)
            logger_func: Función opcional para logging (recibe mensaje)
        """
        self.servidor = servidor
        self.puerto = puerto
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.logger_func = logger_func
        self.connection = None
        self._logged_in = False

    def __enter__(self):
        """Establece conexión IMAP con timeout."""
        # Establecer timeout a nivel de socket
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(self.timeout)
            self.connection = imaplib.IMAP4_SSL(self.servidor, self.puerto)
            self._log(f"Conexión IMAP establecida (timeout={self.timeout}s)")
        finally:
            socket.setdefaulttimeout(old_timeout)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cierra conexión IMAP garantizado."""
        self._close()
        # No suprimir excepciones
        return False

    def _close(self):
        """Cierra la conexión de forma segura."""
        if self.connection is not None:
            try:
                if self._logged_in:
                    self.connection.logout()
                    self._log("Conexión IMAP cerrada correctamente")
                else:
                    # Si no se hizo login, cerrar el socket directamente
                    self.connection.shutdown()
            except Exception as e:
                self._log(f"Error cerrando conexión IMAP: {e}")
            finally:
                self.connection = None
                self._logged_in = False

    def _log(self, mensaje):
        """Log opcional."""
        if self.logger_func:
            self.logger_func(mensaje)

    def login(self, correo, contrasena):
        """Login con tracking de estado."""
        result = self.connection.login(correo, contrasena)
        self._logged_in = True
        return result

    # Proxy de métodos comunes de IMAP
    def select(self, carpeta):
        return self.connection.select(carpeta)

    def search(self, charset, criteria):
        return self.connection.search(charset, criteria)

    def fetch(self, msg_ids, parts):
        return self.connection.fetch(msg_ids, parts)

    def list(self, *args):
        return self.connection.list(*args)

    def logout(self):
        """Logout explícito (también se llama en __exit__)."""
        if self._logged_in and self.connection:
            result = self.connection.logout()
            self._logged_in = False
            return result


@contextmanager
def imap_connection(servidor, puerto, timeout=60, logger_func=None):
    """
    Context manager funcional para conexiones IMAP.

    Uso alternativo más simple:
        with imap_connection('imap.gmail.com', 993) as mail:
            mail.login(correo, password)
            # ...
    """
    mgr = IMAPConnectionManager(servidor, puerto, timeout, logger_func)
    try:
        yield mgr.__enter__()
    finally:
        mgr.__exit__(None, None, None)


class MotorExtractorWeb:
    """Motor para conectar a Gmail y extraer PDFs (versión web)."""

    SERVIDOR_IMAP = 'imap.gmail.com'
    PUERTO_IMAP = 993
    MAX_CUENTAS_SIMULTANEAS = 5

    # Estados del motor
    ESTADO_IDLE = 'idle'
    ESTADO_EJECUTANDO = 'ejecutando'
    ESTADO_PAUSADO = 'pausado'
    ESTADO_DETENIDO = 'detenido'
    ESTADO_COMPLETADO = 'completado'

    def __init__(self, escaneo_id, app, usuario_id=None):
        self.escaneo_id = escaneo_id
        self.app = app
        self.usuario_id = usuario_id
        self.hashes_descargados = set()
        self.detener_solicitado = False
        self.pausado = False
        self.evento_pausa = Event()
        self.evento_pausa.set()  # Inicialmente no pausado (evento activo)
        self.consolidar_al_pausar = False  # Flag para consolidar cuando se pausa
        self.evento_consolidacion = Event()  # Se activa cuando la consolidación termina
        self.evento_consolidacion.set()  # Inicialmente ya "consolidado"
        self.logs = []
        self.cuenta_actual = None
        self.carpeta_actual = None
        self.total_cuentas = 0
        self.cuenta_index = 0
        self.estado_motor = self.ESTADO_IDLE
        self.correo_actual = 0
        self.total_correos_carpeta = 0
        self.correos_en_memoria = 0
        self.total_en_rango = 0
        self.correos_saltados_total = 0
        self.pdfs_duplicados = 0  # PDFs ya descargados anteriormente
        self.correos_procesados_total = 0  # Total de correos nuevos procesados
        self.pdfs_descargados_total = 0  # Total de PDFs descargados
        self.logs_pendientes = 0  # Contador para commit periódico
        # Logger detallado para diagnóstico
        self.scan_logger = ScanLogger(escaneo_id=escaneo_id)
        self.errores_escaneo = 0  # Contador de errores
        # Buffer JSON para evitar bloqueos de BD durante escaneo
        self.scan_buffer = None  # Se inicializa en _escanear_multi con usuario_id

        # Referencia al hilo de escaneo para poder esperar su finalización
        self._thread = None

        # Estado persistente (patrón State)
        # Se inicializa cuando se conoce el usuario_id
        self.state_context = None

    def registrar(self, mensaje, nivel='info', categoria='sistema',
                  correo_message_id=None, archivo_nombre=None, datos_extra=None):
        """Registra un mensaje de log (memoria + base de datos + archivo)."""
        prefijo = ""
        if self.cuenta_actual:
            prefijo = f"[{self.cuenta_actual}] "

        # Log en memoria para la UI en tiempo real
        self.logs.append({
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'mensaje': f"{prefijo}{mensaje}",
            'nivel': nivel
        })

        # Log al archivo detallado (scan_logger)
        try:
            if self.scan_logger:
                log_msg = f"{prefijo}{mensaje}"
                extras = {}
                if correo_message_id:
                    extras['message_id'] = correo_message_id[:50]
                if archivo_nombre:
                    extras['archivo'] = archivo_nombre
                if datos_extra:
                    extras.update(datos_extra)

                if nivel == 'error':
                    self.scan_logger.error(log_msg, **extras)
                    self.errores_escaneo += 1
                elif nivel == 'warning':
                    self.scan_logger.warning(log_msg, **extras)
                elif nivel == 'success':
                    self.scan_logger.success(log_msg, **extras)
                elif nivel == 'debug':
                    self.scan_logger.debug(log_msg, **extras)
                else:
                    self.scan_logger.info(log_msg, **extras)
        except Exception:
            pass

        # Log persistente en base de datos
        try:
            from app.models import LogEscaneo, db
            LogEscaneo.registrar(
                escaneo_id=self.escaneo_id,
                mensaje=f"{prefijo}{mensaje}",
                nivel=nivel,
                categoria=categoria,
                cuenta_gmail=self.cuenta_actual,
                carpeta=self.carpeta_actual,
                correo_message_id=correo_message_id,
                archivo_nombre=archivo_nombre,
                datos_extra=datos_extra
            )
            self.logs_pendientes += 1

            # Commit cada 20 logs para mejor rendimiento
            if self.logs_pendientes >= 20:
                db.session.commit()
                self.logs_pendientes = 0
        except Exception as e:
            # Si falla el log a BD, al menos queda en memoria
            pass

    def commit_logs(self):
        """Guarda logs pendientes en la base de datos."""
        if self.logs_pendientes > 0:
            try:
                from app.models import db
                db.session.commit()
                self.logs_pendientes = 0
            except Exception as e:
                logger.debug(f"No se pudo hacer commit de logs: {e}")

    def probar_conexion(self, correo, contrasena):
        """Prueba la conexión a Gmail con timeout y cierre garantizado."""
        try:
            with IMAPConnectionManager(
                self.SERVIDOR_IMAP,
                self.PUERTO_IMAP,
                timeout=30  # Timeout más corto para prueba de conexión
            ) as mail:
                mail.login(correo, contrasena)
                # Conexión se cierra automáticamente al salir del with
                return True, "Conexión exitosa"
        except imaplib.IMAP4.error as e:
            return False, f"Error de autenticación: {str(e)}"
        except socket.timeout:
            return False, "Timeout: el servidor no responde"
        except Exception as e:
            return False, f"Error de conexión: {str(e)}"

    def sanitizar_nombre(self, nombre):
        """Elimina caracteres inválidos del nombre de archivo."""
        caracteres_invalidos = '<>:"/\\|?*'
        for caracter in caracteres_invalidos:
            nombre = nombre.replace(caracter, '_')
        return nombre[:100]

    def _generar_nombre_desde_datos(self, datos, fecha_correo, directorio_salida, nombre_cia=None):
        """
        Genera nombre de archivo basado en datos extraídos del PDF.
        Formato: COMPAÑIA - TOMADOR - BIEN ASEGURADO - FECHA.pdf

        Ejemplo: berkley - ricardo saccone - ford ranger raptor - 20250115.pdf

        Args:
            datos: dict con datos extraídos (asegurado_nombre, vehiculo_patente, etc.)
            fecha_correo: datetime del correo
            directorio_salida: directorio donde guardar
            nombre_cia: nombre de la compañía (para incluir al inicio del nombre)

        Returns:
            tuple: (nombre_display, ruta_completa)
            - nombre_display: nombre para mostrar en listado
            - ruta_completa: ruta del archivo físico
        """
        # 1. Compañía (al inicio)
        compania = ''
        if nombre_cia:
            compania = self.sanitizar_nombre(nombre_cia)[:20].strip()

        # 2. Tomador/Asegurado
        asegurado = datos.get('asegurado_nombre', '')
        if asegurado:
            asegurado = self.sanitizar_nombre(asegurado)[:40].strip()

        # 3. Bien asegurado (mejorado: marca + modelo para vehículos)
        bien = self._obtener_bien_asegurado(datos)

        # 4. Fecha
        fecha_limpia = fecha_correo.strftime('%Y%m%d')

        # Construir nombre con formato: COMPAÑIA - TOMADOR - BIEN - FECHA.pdf
        partes = []
        if compania:
            partes.append(compania)
        if asegurado:
            partes.append(asegurado)
        if bien:
            partes.append(bien)
        partes.append(fecha_limpia)

        nombre_base = ' - '.join(partes)
        nombre_display = f"{nombre_base}.pdf"
        nombre_fisico = nombre_display

        ruta_salida = os.path.join(directorio_salida, nombre_fisico)

        # Manejar conflictos de nombre
        contador = 1
        while os.path.exists(ruta_salida):
            nombre_display = f"{nombre_base} ({contador}).pdf"
            nombre_fisico = nombre_display
            ruta_salida = os.path.join(directorio_salida, nombre_fisico)
            contador += 1

        return nombre_display, ruta_salida

    def _obtener_bien_asegurado(self, datos):
        """
        Obtiene la descripción del bien asegurado.
        Para vehículos: marca + modelo (ej: ford ranger raptor)
        Para otros: tipo de seguro o número de póliza

        Returns:
            str: descripción del bien asegurado
        """
        # Para vehículos: preferir marca + modelo
        marca = datos.get('vehiculo_marca', '').strip()
        modelo = datos.get('vehiculo_modelo', '').strip()

        if marca or modelo:
            vehiculo_desc = f"{marca} {modelo}".strip()
            if vehiculo_desc:
                return self.sanitizar_nombre(vehiculo_desc)[:40]

        # Si hay patente pero no marca/modelo, usar patente
        if datos.get('vehiculo_patente'):
            patente = datos['vehiculo_patente'].replace(' ', '').replace('-', '')
            return patente[:10]

        # Para inmuebles: usar dirección o tipo
        if datos.get('inmueble_direccion'):
            return self.sanitizar_nombre(datos['inmueble_direccion'])[:40]
        if datos.get('inmueble_tipo'):
            return self.sanitizar_nombre(datos['inmueble_tipo'])[:20]

        # Fallback: tipo de seguro o número de póliza
        if datos.get('tipo_seguro'):
            return self.sanitizar_nombre(datos['tipo_seguro'])[:20]
        if datos.get('bien_asegurado_tipo'):
            return self.sanitizar_nombre(datos['bien_asegurado_tipo'])[:20]
        if datos.get('numero_poliza'):
            return datos['numero_poliza'].replace(' ', '')[:15]

        return ''

    def _guardar_pdf_atomico(self, contenido, hash_archivo, nuevo_nombre, datos_correo,
                             compania, db_session, escaneo, archivo_repo_existente=None,
                             max_reintentos=3):
        """
        Guarda un PDF a disco y registra en buffer JSON (sin tocar la BD).

        La BD se actualiza al finalizar el escaneo via consolidar_a_bd().
        Esto evita completamente el problema de "database is locked".

        Args:
            contenido: bytes del PDF
            hash_archivo: hash SHA-256 del contenido
            nuevo_nombre: nombre sugerido para el archivo
            datos_correo: dict con {remitente, asunto, fecha_correo, message_id, cuenta_id}
            compania: objeto Compania o None
            db_session: sesión SQLAlchemy (solo para lecturas)
            escaneo: objeto Escaneo actual
            archivo_repo_existente: ArchivoRepositorio si ya existe (para reutilizar)
            max_reintentos: ignorado (mantenido por compatibilidad)

        Returns:
            tuple: (archivo_info, exito, mensaje)
            - archivo_info: dict con datos del archivo o None
            - exito: bool indicando si se guardó correctamente
            - mensaje: descripción del resultado
        """
        from app.models import ArchivoDescargado, ArchivoRepositorio
        from flask import current_app

        remitente = datos_correo['remitente']
        asunto = datos_correo['asunto']
        fecha_correo = datos_correo['fecha_correo']
        cuenta_origen = datos_correo.get('cuenta_origen', '')

        try:
            # ================================================================
            # FASE 1: Guardar archivo a disco (sin BD)
            # ================================================================
            ruta_archivo = None
            es_reutilizado = False
            archivo_repo_hash = None

            if archivo_repo_existente:
                # Reutilizar archivo existente
                ruta_archivo = archivo_repo_existente.obtener_ruta_fisica()
                es_reutilizado = True
                archivo_repo_hash = archivo_repo_existente.hash_sha256
            else:
                # Verificar si existe por hash
                archivo_repo = ArchivoRepositorio.buscar_por_hash(hash_archivo)
                if archivo_repo:
                    ruta_archivo = archivo_repo.obtener_ruta_fisica()
                    es_reutilizado = True
                    archivo_repo_hash = archivo_repo.hash_sha256
                else:
                    # Guardar archivo nuevo a disco
                    repo_dir = current_app.config.get('REPOSITORIO_ARCHIVOS')
                    if not repo_dir:
                        repo_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'repositorio_archivos')
                    os.makedirs(repo_dir, exist_ok=True)

                    # Crear subdirectorio por primeros 2 caracteres del hash
                    subdir = os.path.join(repo_dir, hash_archivo[:2])
                    os.makedirs(subdir, exist_ok=True)

                    # Nombre único basado en hash
                    nombre_fisico = f"{hash_archivo}.pdf"
                    ruta_archivo = os.path.join(subdir, nombre_fisico)
                    ruta_relativa = os.path.join(hash_archivo[:2], nombre_fisico)

                    # Escribir archivo a disco
                    with open(ruta_archivo, 'wb') as f:
                        f.write(contenido)

                    # Registrar en buffer para insertar después
                    if self.scan_buffer:
                        self.scan_buffer.agregar_archivo_repositorio(
                            hash_archivo=hash_archivo,
                            nombre_archivo=nuevo_nombre,
                            ruta_relativa=ruta_relativa,
                            tamano_bytes=len(contenido)
                        )
                    archivo_repo_hash = hash_archivo

            # ================================================================
            # FASE 2: Generar ID temporal y registrar en buffer JSON
            # ================================================================
            # Usar ID temporal del buffer (se convertirá a ID real en consolidación)
            if self.scan_buffer:
                id_documento = self.scan_buffer.generar_id_temporal()
            else:
                id_documento = ArchivoDescargado.generar_siguiente_id()

            if self.scan_buffer:
                self.scan_buffer.agregar_pdf(
                    id_documento=id_documento,
                    nombre_archivo=nuevo_nombre,
                    ruta_archivo=ruta_archivo,
                    tamano_bytes=len(contenido),
                    hash_archivo=hash_archivo,
                    remitente=remitente[:255] if remitente else None,
                    asunto=asunto[:500] if asunto else None,
                    fecha_correo=fecha_correo,
                    compania_id=compania.id if compania else None,
                    nombre_compania=compania.nombre if compania else None,
                    cuenta_origen=cuenta_origen,
                    archivo_repo_hash=archivo_repo_hash
                )

                # Registrar dominio
                if remitente and '@' in remitente:
                    dominio = remitente.split('@')[-1].replace('>', '').strip()
                    self.scan_buffer.agregar_dominio(dominio)

            logger.debug(f"[Buffer] PDF guardado: {nuevo_nombre}")

            # Log estructurado
            log_extraccion('pdf_guardado', 'exito',
                           id_documento=id_documento,
                           archivo=nuevo_nombre,
                           hash=hash_archivo[:16],
                           compania=compania.nombre if compania else None,
                           tamano_bytes=len(contenido),
                           reutilizado=es_reutilizado,
                           escaneo_id=self.escaneo_id)

            # Retornar un objeto tipo dict con id_documento para compatibilidad
            archivo_info = type('ArchivoInfo', (), {'id_documento': id_documento})()
            return archivo_info, True, f"Guardado: {id_documento}"

        except Exception as e:
            error_msg = f"Error guardando PDF: {str(e)[:100]}"
            logger.error(f"[Buffer] {error_msg}")

            if self.scan_buffer:
                self.scan_buffer.registrar_error()

            log_extraccion('pdf_guardado', 'error',
                           archivo=nuevo_nombre,
                           hash=hash_archivo[:16] if hash_archivo else None,
                           error=str(e)[:200],
                           escaneo_id=self.escaneo_id)

            return None, False, error_msg

    def decodificar_cabecera(self, valor):
        """Decodifica el valor de una cabecera de correo."""
        if valor is None:
            return ""
        partes_decodificadas = decode_header(valor)
        resultado = ""
        for parte, codificacion in partes_decodificadas:
            if isinstance(parte, bytes):
                resultado += parte.decode(codificacion or 'utf-8', errors='replace')
            else:
                resultado += parte
        return resultado

    def obtener_hash_archivo(self, contenido):
        """Genera hash del contenido del archivo."""
        return hashlib.sha256(contenido).hexdigest()

    def coincide_palabras_clave(self, asunto, remitente, palabras_clave):
        """DEPRECADO - Usar coincide_dominio en su lugar."""
        if not palabras_clave:
            return True
        texto = f"{asunto} {remitente}".lower()
        return any(pc.lower() in texto for pc in palabras_clave)

    def extraer_dominio(self, remitente):
        """Extrae el dominio de un remitente de email."""
        if not remitente:
            return None
        match = re.search(r'@([a-zA-Z0-9.-]+)', remitente)
        return match.group(1).lower() if match else None

    def coincide_dominio(self, remitente, dominios_filtro):
        """Verifica si el remitente pertenece a alguno de los dominios/emails filtro.

        Args:
            remitente: Dirección de email del remitente
            dominios_filtro: Lista de dominios o emails permitidos, vacía = todos

        Returns:
            True si coincide o no hay filtro, False si no coincide
        """
        # Si no hay filtro de dominios, aceptar todos
        if not dominios_filtro:
            return True

        if not remitente:
            return False

        remitente_lower = remitente.lower()

        for filtro in dominios_filtro:
            filtro_lower = filtro.lower()

            # Si el filtro contiene @, es un email completo
            if '@' in filtro_lower:
                if filtro_lower in remitente_lower:
                    return True
            else:
                # Es un dominio, verificar que termine con @dominio
                if f'@{filtro_lower}' in remitente_lower:
                    return True

        return False

    # ============================================================================
    # DESCARGA DE PDFs DESDE ENLACES EN CORREOS (Ej: Mercantil Andina)
    # ============================================================================

    # Dominios de compañías que envían PDFs via enlace en lugar de adjunto
    COMPANIAS_CON_ENLACE = {
        'mercantil_andina': {
            'dominios': ['lamercantil.com.ar', 'mercantilandina.com.ar'],
            # Patrón específico para URLs de descarga de Mercantil Andina
            'patron_enlace': r'api_papeleria.*?/descarga\?token=',
            'texto_boton': ['descarga', 'download'],
            # URLs a excluir (dar de baja, desuscripción, etc.)
            'excluir': ['/baja', 'distribucion_digital'],
        },
    }

    def es_correo_con_enlace_descarga(self, remitente):
        """Detecta si el correo es de una compañía que envía PDFs por enlace."""
        # Usar sistema de estrategias si está disponible
        if ESTRATEGIAS_DISPONIBLES and obtener_compania:
            compania = obtener_compania(remitente)
            if compania and compania.tipo_extraccion == 'enlace_html':
                # Convertir ConfigCompania a formato dict compatible
                config_compat = {
                    'dominios': compania.dominios,
                    'patron_enlace': compania.config_especifica.get('patron_url'),
                    'texto_boton': compania.config_especifica.get('texto_boton', ['descarga', 'download']),
                    'excluir': compania.config_especifica.get('excluir_urls', []),
                }
                return compania.id, config_compat
            return None, None

        # Fallback: usar diccionario hardcodeado
        remitente_lower = remitente.lower()
        for nombre, config in self.COMPANIAS_CON_ENLACE.items():
            for dominio in config['dominios']:
                if dominio in remitente_lower:
                    return nombre, config
        return None, None

    def obtener_estrategia_compania(self, remitente):
        """Obtiene la estrategia de extracción para un remitente."""
        if ESTRATEGIAS_DISPONIBLES and obtener_estrategia:
            return obtener_estrategia(remitente)
        return None

    def extraer_enlaces_descarga(self, html_content, config_compania):
        """Extrae URLs de descarga del contenido HTML del correo."""
        enlaces_prioritarios = []  # Enlaces que coinciden con patrón específico
        enlaces_secundarios = []   # Enlaces por palabras clave

        if not html_content:
            return []

        # Buscar todos los enlaces <a href="..."> - captura URL y contenido interno (puede ser img)
        patron_href = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
        matches = re.findall(patron_href, html_content, re.IGNORECASE | re.DOTALL)

        # Lista de patrones a excluir
        patrones_excluir = config_compania.get('excluir', [])

        for url, contenido_interno in matches:
            # Verificar si la URL debe ser excluida
            url_lower = url.lower()
            if any(excluir in url_lower for excluir in patrones_excluir):
                continue

            if not url.startswith('http'):
                continue

            # Extraer texto del contenido (puede incluir <img alt="...">)
            texto_alt = re.search(r'alt=["\']([^"\']+)["\']', contenido_interno)
            texto = texto_alt.group(1) if texto_alt else contenido_interno
            texto_limpio = re.sub(r'<[^>]+>', '', texto).strip().lower()

            # Prioridad 1: Coincide con patrón específico de la compañía
            if config_compania.get('patron_enlace'):
                if re.search(config_compania['patron_enlace'], url, re.IGNORECASE):
                    enlaces_prioritarios.append(url)
                    continue

            # Prioridad 2: Texto o URL contiene palabras clave de descarga
            es_enlace_descarga = any(
                palabra in texto_limpio or palabra in url_lower
                for palabra in config_compania.get('texto_boton', ['descarga', 'download'])
            )

            if es_enlace_descarga:
                enlaces_secundarios.append(url)

        # Devolver prioritarios primero, luego secundarios
        return enlaces_prioritarios + enlaces_secundarios

    def descargar_pdf_desde_url(self, url, timeout=30):
        """Descarga un PDF desde una URL y retorna el contenido."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/pdf,*/*',
            }

            response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)

            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '').lower()

                # Verificar si es PDF por Content-Type o por magic bytes
                if 'pdf' in content_type or response.content[:4] == b'%PDF':
                    return response.content, None
                else:
                    return None, f"No es PDF (Content-Type: {content_type})"
            else:
                return None, f"HTTP {response.status_code}"

        except requests.exceptions.Timeout:
            return None, "Timeout al descargar"
        except requests.exceptions.RequestException as e:
            return None, f"Error de conexión: {str(e)}"
        except Exception as e:
            return None, f"Error: {str(e)}"

    def ejecutar_escaneo_multi(self, cuentas, config, directorio_salida):
        """Ejecuta el escaneo de múltiples cuentas en un hilo separado."""
        # Extraer solo los IDs para evitar problemas de sesion SQLAlchemy
        # Los objetos se re-consultan dentro del hilo con el contexto correcto
        cuenta_ids = [c.id for c in cuentas]
        self._thread = Thread(target=self._escanear_multi_con_contexto,
                              args=(cuenta_ids, config, directorio_salida),
                              name=f"Escaneo-{self.escaneo_id}")
        self._thread.daemon = True
        self._thread.start()

    def esperar_finalizacion(self, timeout: float = 10.0) -> bool:
        """
        Espera a que el hilo de escaneo termine.

        Args:
            timeout: Tiempo máximo de espera en segundos

        Returns:
            True si el hilo terminó, False si expiró el timeout
        """
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            return not self._thread.is_alive()
        return True

    def _escanear_multi_con_contexto(self, cuenta_ids, config, directorio_salida):
        """Ejecuta el escaneo multi-cuenta dentro del contexto de la aplicación.

        Usa thread_session para garantizar que las operaciones de BD sean
        thread-safe y no tengan problemas de sesiones detached.
        """
        try:
            with thread_session(self.app) as session:
                self._escanear_multi(cuenta_ids, config, directorio_salida, session)
        except Exception as e:
            logger.error(f"[Motor] Error crítico en escaneo: {e}")
            # Log detallado del error
            if self.scan_logger:
                self.scan_logger.escaneo_error(str(e))
            # Intentar marcar el escaneo como error con una nueva sesión
            try:
                with thread_session(self.app) as session:
                    from app.models import Escaneo
                    escaneo = session.query(Escaneo).get(self.escaneo_id)
                    if escaneo and escaneo.estado == 'en_progreso':
                        escaneo.estado = 'error'
                        escaneo.mensaje_error = f"Error crítico: {str(e)[:200]}"
                        escaneo.fecha_fin = datetime.utcnow()
            except Exception as e2:
                logger.error(f"[Motor] No se pudo marcar escaneo como error: {e2}")
        finally:
            # Cerrar el logger al finalizar
            if self.scan_logger:
                self.scan_logger.close()

    def _escanear_multi(self, cuenta_ids, config, directorio_salida, session=None):
        """Realiza el escaneo de múltiples cuentas de Gmail secuencialmente.

        Args:
            cuenta_ids: Lista de IDs de cuentas Gmail a escanear
            config: Configuración del escaneo
            directorio_salida: Directorio donde guardar los PDFs
            session: Sesión SQLAlchemy thread-safe (opcional, usa db.session si no se provee)
        """
        from app import db
        from app.models import Escaneo, CuentaGmail

        # Usar la sesión proporcionada o db.session como fallback
        # Nota: cuando se usa thread_session, db.session apunta a la sesión correcta
        db_session = session if session is not None else db.session

        escaneo = db_session.query(Escaneo).get(self.escaneo_id)
        if not escaneo:
            return

        # Inicializar buffer JSON para evitar bloqueos de BD durante escaneo
        self.scan_buffer = ScanBuffer(escaneo_id=self.escaneo_id, usuario_id=escaneo.usuario_id)

        # Inicializar contexto de estado persistente
        self.usuario_id = escaneo.usuario_id
        self.state_context = ScanStateContext(
            escaneo_id=self.escaneo_id,
            usuario_id=escaneo.usuario_id
        )

        # Re-consultar las cuentas dentro del contexto de este hilo
        # Esto evita errores de DetachedInstanceError
        cuentas = db_session.query(CuentaGmail).filter(CuentaGmail.id.in_(cuenta_ids)).all()
        if not cuentas:
            escaneo.estado = 'error'
            escaneo.mensaje_error = 'No se encontraron cuentas validas'
            escaneo.fecha_fin = datetime.utcnow()
            db_session.commit()
            return

        # Inicializar set para tracking de duplicados en ESTE escaneo
        # (la deduplicación real se hace contra ArchivoRepositorio)
        self.hashes_descargados = set()
        self.registrar("Repositorio de archivos activo - deduplicación por hash",
                       nivel='info', categoria='sistema')

        self.estado_motor = self.ESTADO_EJECUTANDO
        self.total_cuentas = len(cuentas)
        total_correos = 0
        total_pdfs = 0

        # Log estructurado: inicio de escaneo
        log_extraccion('escaneo_iniciado', 'inicio',
                       escaneo_id=self.escaneo_id,
                       total_cuentas=self.total_cuentas,
                       usuario_id=escaneo.usuario_id,
                       cuentas=[c.correo_gmail for c in cuentas])

        # Iniciar contexto de estado persistente
        lista_correos = [c.correo_gmail for c in cuentas]
        if self.state_context:
            # Verificar si hay estado guardado previo
            if self.state_context.can_resume:
                self.restaurar_desde_estado()
                self.registrar(f"Reanudando desde estado guardado")
            else:
                self.state_context.start(config, lista_correos, directorio_salida)

        try:
            # Log del sistema de estrategias
            if ESTRATEGIAS_DISPONIBLES:
                from app.extractor.companias import RegistroEstrategias
                registro = RegistroEstrategias()
                companias_config = registro.listar_companias()
                self.registrar(f"Sistema de estrategias activo: {len(companias_config)} compañías configuradas",
                               nivel='info', categoria='sistema',
                               datos_extra={'companias': list(companias_config.keys())})
            else:
                self.registrar("Sistema de estrategias no disponible, usando configuración legacy",
                               nivel='warning', categoria='sistema')

            self.registrar(f"Iniciando escaneo de {self.total_cuentas} cuenta(s)",
                           nivel='info', categoria='sistema')

            for index, cuenta in enumerate(cuentas):
                # Verificar pausa/detención
                if not self.esperar_si_pausado():
                    break

                if self.detener_solicitado:
                    break

                self.cuenta_index = index + 1
                self.cuenta_actual = cuenta.correo_gmail
                escaneo.cuenta_actual = self.cuenta_actual
                db_session.commit()

                self.registrar(f"Procesando cuenta {self.cuenta_index}/{self.total_cuentas}",
                               nivel='info', categoria='conexion')

                try:
                    correos, pdfs = self._escanear_cuenta(cuenta, config, directorio_salida, escaneo, db_session)
                    total_correos += correos
                    total_pdfs += pdfs
                except Exception as e:
                    error_msg = f"Error en cuenta {cuenta.correo_gmail}: {str(e)}"
                    self.registrar(f"ERROR: {error_msg}", nivel='error', categoria='conexion',
                                   datos_extra={'exception': str(e)})
                    # Continuar con siguiente cuenta si hay más
                    if index < len(cuentas) - 1:
                        self.registrar("Continuando con siguiente cuenta...", nivel='warning', categoria='conexion')
                        continue
                    else:
                        raise

                # Nota: Ya no actualizamos BD aquí, se hace al consolidar al final
                # El progreso se muestra desde la memoria del motor

            # ================================================================
            # CONSOLIDAR BUFFER JSON A BASE DE DATOS
            # IMPORTANTE: Hacer ANTES de marcar como completado para que
            # los PDFs estén disponibles cuando el frontend detecte el cambio
            # ================================================================
            if self.scan_buffer:
                try:
                    # Mostrar resumen antes de consolidar
                    stats = self.scan_buffer.obtener_estadisticas()
                    self.registrar(
                        f"=== INICIANDO CONSOLIDACIÓN ===\n"
                        f"  PDFs a guardar: {stats['pdfs']}\n"
                        f"  Correos procesados: {stats['correos']}\n"
                        f"  Dominios detectados: {stats['dominios']}",
                        nivel='info', categoria='sistema')

                    resultado_consolidacion = self.scan_buffer.consolidar_a_bd(db_session)

                    # Mostrar resultado
                    errores = resultado_consolidacion.get('errores', [])
                    msg = (
                        f"=== CONSOLIDACIÓN COMPLETADA ===\n"
                        f"  PDFs insertados: {resultado_consolidacion['pdfs_insertados']}\n"
                        f"  Correos insertados: {resultado_consolidacion['correos_insertados']}\n"
                        f"  Repos insertados: {resultado_consolidacion['repos_insertados']}"
                    )
                    if errores:
                        msg += f"\n  Errores: {len(errores)}"
                    self.registrar(msg, nivel='success', categoria='sistema')

                    # Actualizar contadores reales del escaneo
                    escaneo.pdfs_descargados = resultado_consolidacion['pdfs_insertados']
                    total_pdfs = resultado_consolidacion['pdfs_insertados']

                except Exception as e_consolidar:
                    self.registrar(f"ERROR EN CONSOLIDACIÓN: {e_consolidar}",
                                   nivel='error', categoria='sistema')
                    if self.scan_logger:
                        self.scan_logger.error(f"Error consolidando buffer: {e_consolidar}", exc_info=True)

            # Actualizar estado persistente
            if self.state_context:
                if self.detener_solicitado:
                    # Guardar estado para posible reanudación
                    self._actualizar_progreso_estado()
                    self.state_context.stop()
                    self.registrar("Estado guardado - puede reanudarse con /reanudar")
                else:
                    # Completado - eliminar archivo de estado
                    self.state_context.complete()

            # ================================================================
            # MARCAR COMO COMPLETADO - ÚLTIMO PASO
            # El frontend detecta este cambio y redirige a Archivos
            # Los PDFs ya están consolidados en la BD
            # ================================================================
            escaneo.estado = 'cancelado' if self.detener_solicitado else 'completado'
            escaneo.fecha_fin = datetime.utcnow()
            escaneo.cuenta_actual = None
            self.estado_motor = self.ESTADO_COMPLETADO if not self.detener_solicitado else self.ESTADO_DETENIDO

            # Commit con retry para evitar "database is locked" después de consolidación pesada
            for intento in range(5):
                try:
                    db_session.commit()
                    break
                except Exception as e_commit:
                    if 'database is locked' in str(e_commit).lower() and intento < 4:
                        import time
                        delay = (2 ** intento) * 0.5  # 0.5s, 1s, 2s, 4s
                        self.registrar(f"BD ocupada, reintentando en {delay}s (intento {intento+1}/5)",
                                       nivel='warning', categoria='sistema')
                        time.sleep(delay)
                    else:
                        raise

            self.registrar(f"Escaneo finalizado: {total_correos} correos, {total_pdfs} PDFs",
                           nivel='success', categoria='sistema',
                           datos_extra={'correos': total_correos, 'pdfs': total_pdfs,
                                        'saltados': self.correos_saltados_total,
                                        'duplicados': self.pdfs_duplicados})
            self.commit_logs()  # Guardar logs pendientes

            # Log estructurado: escaneo completado
            log_extraccion('escaneo_completado', 'exito',
                           escaneo_id=self.escaneo_id,
                           usuario_id=escaneo.usuario_id,
                           correos_procesados=total_correos,
                           pdfs_descargados=total_pdfs,
                           correos_saltados=self.correos_saltados_total,
                           duplicados_detectados=self.pdfs_duplicados,
                           estado_final=escaneo.estado)

            # Log detallado: escaneo completado
            if self.scan_logger:
                self.scan_logger.escaneo_completado(total_correos, total_pdfs, self.errores_escaneo)

            # Verificar duplicados al finalizar el escaneo
            try:
                from app.extractor.verificador_duplicados import verificar_duplicados_post_escaneo
                self.registrar("Iniciando verificación de duplicados post-escaneo...",
                               nivel='info', categoria='sistema')
                resultados_dup = verificar_duplicados_post_escaneo(
                    escaneo_id=escaneo.id,
                    db_session=db_session,
                    logger=lambda msg: self.registrar(msg, nivel='info', categoria='duplicados')
                )
                if resultados_dup['total_duplicados'] > 0:
                    self.registrar(
                        f"Verificación completada: {resultados_dup['total_duplicados']} duplicados encontrados",
                        nivel='warning', categoria='duplicados',
                        datos_extra=resultados_dup
                    )
                else:
                    self.registrar("Verificación completada: No se encontraron duplicados",
                                   nivel='success', categoria='duplicados')
                self.commit_logs()
            except Exception as e_dup:
                self.registrar(f"Error en verificación de duplicados: {str(e_dup)}",
                               nivel='error', categoria='duplicados')
                self.commit_logs()

        except Exception as e:
            # Capturar cualquier excepción y marcar como error
            error_msg = f"Error fatal: {str(e)}"
            self.registrar(f"ERROR CRÍTICO: {error_msg}", nivel='error', categoria='sistema',
                           datos_extra={'exception': str(e), 'tipo': type(e).__name__})
            # Log detallado del error fatal
            if self.scan_logger:
                self.scan_logger.escaneo_error(str(e))
            self.commit_logs()  # Guardar logs antes de terminar
            self.estado_motor = self.ESTADO_DETENIDO

            try:
                db_session.rollback()  # Limpiar transacción anterior
                escaneo = db_session.query(Escaneo).get(self.escaneo_id)
                if escaneo:
                    escaneo.estado = 'error'
                    escaneo.mensaje_error = error_msg
                    escaneo.fecha_fin = datetime.utcnow()
                    escaneo.cuenta_actual = None
                    escaneo.correos_escaneados = total_correos
                    escaneo.pdfs_descargados = total_pdfs
                    db_session.commit()
            except Exception as commit_error:
                logger.error(f"[Motor] Error guardando estado de error: {commit_error}")

    def _obtener_todas_carpetas(self, mail, incluir_spam_trash=False):
        """
        Obtiene todas las carpetas disponibles en la cuenta IMAP.
        Filtra carpetas del sistema y devuelve una lista limpia.

        Args:
            mail: Conexión IMAP
            incluir_spam_trash: Si True, incluye carpetas de spam/papelera (modo dev)
        """
        carpetas_disponibles = []

        # Carpetas a ignorar (sistema, spam, papelera)
        carpetas_ignorar = [
            '[Gmail]/Borrador', '[Gmail]/Drafts', '[Gmail]/Borradores'
        ]

        # Solo agregar spam/trash a la lista de ignorar si NO estamos en modo dev
        if not incluir_spam_trash:
            carpetas_ignorar.extend([
                '[Gmail]/Spam', '[Gmail]/Papelera', '[Gmail]/Trash',
                '[Gmail]/Bin', '[Gmail]/Junk'
            ])
        else:
            self.registrar("[DEV] Incluyendo carpetas Spam/Papelera", nivel='warning', categoria='config')

        carpetas_ignorar_lower = [c.lower() for c in carpetas_ignorar]

        try:
            resultado, lista = mail.list()
            if resultado == 'OK':
                for item in lista:
                    # Decodificar el item
                    if isinstance(item, bytes):
                        item = item.decode('utf-8', errors='ignore')

                    # Extraer nombre de carpeta del formato IMAP
                    # Formato: (\\HasNoChildren) "/" "INBOX"
                    import re
                    match = re.search(r'"([^"]+)"$', item)
                    if match:
                        carpeta = match.group(1)
                    else:
                        # Intentar otro formato
                        partes = item.split(' "/" ')
                        if len(partes) >= 2:
                            carpeta = partes[-1].strip('"')
                        else:
                            continue

                    # Filtrar carpetas del sistema
                    if carpeta.lower() in carpetas_ignorar_lower:
                        continue
                    # Solo filtrar spam/trash si NO estamos en modo dev
                    if not incluir_spam_trash:
                        if 'spam' in carpeta.lower() or 'trash' in carpeta.lower():
                            continue

                    carpetas_disponibles.append(carpeta)

        except Exception as e:
            self.registrar(f"Error obteniendo carpetas: {e}")
            # Si falla, al menos usar INBOX
            return ['INBOX']

        # Si no encontramos carpetas, usar INBOX
        if not carpetas_disponibles:
            return ['INBOX']

        # Ordenar: INBOX primero, luego alfabeticamente
        carpetas_ordenadas = []
        if 'INBOX' in carpetas_disponibles:
            carpetas_ordenadas.append('INBOX')
            carpetas_disponibles.remove('INBOX')

        carpetas_ordenadas.extend(sorted(carpetas_disponibles))

        return carpetas_ordenadas

    def _escanear_cuenta(self, cuenta, config, directorio_salida, escaneo, db_session=None):
        """Escanea una cuenta individual de Gmail.

        Args:
            cuenta: Objeto CuentaGmail a escanear
            config: Configuración del escaneo
            directorio_salida: Directorio donde guardar los PDFs
            escaneo: Objeto Escaneo actual
            db_session: Sesión SQLAlchemy thread-safe (opcional)
        """
        from app import db
        from app.models import ArchivoDescargado, ArchivoRepositorio, Compania, CorreoProcesado, HistorialEscaneoCarpeta, DominioRemitente, RangoCobertura

        # Usar la sesión proporcionada o db.session como fallback
        if db_session is None:
            db_session = db.session

        carpetas = config.get('carpetas', ['INBOX'])
        # Nuevo sistema: filtrar por dominios
        dominios_filtro = config.get('dominios_filtro', [])
        # Mantener compatibilidad con palabras clave (deprecado)
        palabras_clave = config.get('palabras_clave', [])
        fecha_desde = config.get('fecha_desde')
        fecha_hasta = config.get('fecha_hasta')

        # Opcion para forzar re-escaneo completo (ignorar memoria)
        forzar_escaneo = config.get('forzar_escaneo', False)

        # Opcion para validar que el PDF sea una póliza antes de guardar
        validar_polizas = config.get('validar_polizas', True)  # Activado por defecto

        # Opciones de desarrollo (overrides de filtros)
        dev_options = config.get('dev_options', {})
        dev_incluir_spam = dev_options.get('incluir_spam_trash', False)
        dev_skip_validacion = dev_options.get('skip_validacion', False)
        dev_permitir_duplicados = dev_options.get('permitir_duplicados', False)
        dev_sin_compania_ok = dev_options.get('sin_compania_ok', False)

        # Si skip_validacion está activo, desactivar validación completamente
        if dev_skip_validacion:
            validar_polizas = False
            self.registrar("[DEV] Validación de pólizas DESACTIVADA", nivel='warning', categoria='config')

        pdfs_encontrados = 0
        correos_escaneados = 0

        # Inicializar conexión como None para manejo seguro en finally
        mail = None

        try:
            correo = cuenta.correo_gmail
            contrasena = cuenta.obtener_contrasena_app()

            # Log detallado: inicio de conexión
            if self.scan_logger:
                self.scan_logger.set_cuenta(correo)
                self.scan_logger.conexion_iniciada(self.SERVIDOR_IMAP, self.PUERTO_IMAP)

            # Usar context manager para conexión IMAP con timeout y cierre garantizado
            mail = IMAPConnectionManager(
                self.SERVIDOR_IMAP,
                self.PUERTO_IMAP,
                timeout=120,  # 2 minutos para operaciones largas
                logger_func=lambda msg: self.registrar(msg, nivel='debug', categoria='conexion')
            )
            mail.__enter__()
            mail.login(correo, contrasena)
            self.registrar(f"Conectado", nivel='success', categoria='conexion')

            # Log detallado: conexión exitosa
            if self.scan_logger:
                self.scan_logger.conexion_exitosa()

            # Actualizar último escaneo de la cuenta
            cuenta.ultimo_escaneo = datetime.utcnow()
            db_session.commit()

            # Obtener todas las carpetas disponibles si no se especificaron
            if carpetas == ['INBOX'] or not carpetas:
                carpetas = self._obtener_todas_carpetas(mail, incluir_spam_trash=dev_incluir_spam)
                self.registrar(f"Explorando {len(carpetas)} carpetas", nivel='info', categoria='carpeta',
                               datos_extra={'carpetas': carpetas[:10]})

            for carpeta in carpetas:
                if self.detener_solicitado:
                    break

                self.carpeta_actual = carpeta
                try:
                    resultado, _ = mail.select(f'"{carpeta}"')
                    if resultado != 'OK':
                        self.registrar(f"No se pudo seleccionar: {carpeta}", nivel='warning', categoria='carpeta')
                        continue

                    self.registrar(f"Escaneando: {carpeta}", nivel='info', categoria='carpeta')

                    # ============================================================
                    # OPTIMIZACION: Usar fecha más reciente procesada como filtro
                    # Si ya escaneamos hasta cierta fecha, empezar desde ahí
                    # ============================================================
                    fecha_desde_efectiva = fecha_desde
                    fecha_mas_reciente = None

                    if not forzar_escaneo:
                        fecha_mas_reciente = HistorialEscaneoCarpeta.obtener_fecha_mas_reciente_procesada(
                            cuenta.id, carpeta
                        )
                        if fecha_mas_reciente:
                            # Usar el día siguiente a la fecha más reciente procesada
                            from datetime import timedelta
                            fecha_limite = fecha_mas_reciente + timedelta(days=1)

                            if fecha_desde is None or fecha_limite > fecha_desde:
                                fecha_desde_efectiva = fecha_limite
                                self.registrar(f"Optimizado: saltando correos anteriores a {fecha_limite.strftime('%d/%m/%Y')}")

                    # Construir criterios de búsqueda
                    criterios = []
                    if fecha_desde_efectiva:
                        criterios.append(f'SINCE {fecha_desde_efectiva.strftime("%d-%b-%Y")}')
                    if fecha_hasta:
                        criterios.append(f'BEFORE {fecha_hasta.strftime("%d-%b-%Y")}')

                    # Filtro FROM por dominio/remitente (optimización IMAP)
                    if dominios_filtro and len(dominios_filtro) > 0:
                        if len(dominios_filtro) == 1:
                            # Un solo dominio: FROM "dominio"
                            dom = dominios_filtro[0]
                            criterios.append(f'FROM "{dom}"')
                            self.registrar(f"Filtro IMAP: FROM '{dom}'", nivel='info')
                        else:
                            # Múltiples dominios: OR (FROM "dom1") (FROM "dom2") ...
                            # IMAP usa OR binario, hay que anidarlo
                            from_parts = [f'FROM "{dom}"' for dom in dominios_filtro]
                            # Construir OR anidado: OR (FROM a) (OR (FROM b) (FROM c))
                            or_clause = from_parts[-1]
                            for part in reversed(from_parts[:-1]):
                                or_clause = f'OR {part} ({or_clause})'
                            criterios.append(f'({or_clause})')
                            self.registrar(f"Filtro IMAP: {len(dominios_filtro)} dominios seleccionados", nivel='info')

                    cadena_busqueda = ' '.join(criterios) if criterios else 'ALL'

                    resultado, mensajes = mail.search(None, cadena_busqueda)
                    if resultado != 'OK':
                        continue

                    ids_mensajes = mensajes[0].split()
                    total_en_carpeta = len(ids_mensajes)

                    # Cargar Message-IDs ya procesados en memoria para verificación O(1)
                    message_ids_procesados = set(
                        row[0] for row in db_session.query(CorreoProcesado.message_id).filter_by(
                            cuenta_gmail_id=cuenta.id,
                            carpeta=carpeta
                        ).all()
                    )
                    correos_en_memoria = len(message_ids_procesados)

                    self.total_correos_carpeta = total_en_carpeta
                    self.correos_en_memoria = correos_en_memoria
                    self.total_en_rango = total_en_carpeta

                    # Log detallado de carpeta
                    if self.scan_logger:
                        self.scan_logger.carpeta_seleccionada(carpeta, total_en_carpeta)

                    if fecha_mas_reciente:
                        self.registrar(f"Correos nuevos a revisar: {total_en_carpeta} (anteriores a {fecha_mas_reciente.strftime('%d/%m/%Y')} ya procesados)")
                    else:
                        self.registrar(f"Correos a revisar: {total_en_carpeta} | En memoria: {correos_en_memoria}")

                    # Contadores para esta carpeta
                    correos_nuevos = 0
                    correos_saltados = 0
                    correos_con_pdf_carpeta = 0
                    pdfs_carpeta = 0
                    fecha_mas_reciente = None
                    idx = 0  # Inicializar para evitar error si no hay correos

                    for idx, id_msg in enumerate(ids_mensajes, 1):
                        # Verificar pausa
                        if not self.esperar_si_pausado():
                            break

                        if self.detener_solicitado:
                            break

                        self.correo_actual = idx  # Posición dentro de la carpeta actual

                        # ============================================================
                        # OPTIMIZACION: Obtener SOLO el Message-ID primero
                        # Esto evita descargar el correo completo si ya fue procesado
                        # ============================================================
                        resultado_header, datos_header = mail.fetch(id_msg, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
                        if resultado_header != 'OK':
                            correos_escaneados += 1
                            continue

                        # Extraer Message-ID del header
                        header_data = datos_header[0][1] if datos_header and datos_header[0] else b''
                        if isinstance(header_data, bytes):
                            header_text = header_data.decode('utf-8', errors='replace')
                        else:
                            header_text = str(header_data)

                        # Parsear Message-ID
                        message_id = ''
                        for linea in header_text.split('\n'):
                            if linea.lower().startswith('message-id:'):
                                message_id = linea.split(':', 1)[1].strip()
                                break

                        # Si no tiene Message-ID, generar uno basado en el UID del correo
                        if not message_id:
                            message_id = f"no-msgid-{id_msg.decode() if isinstance(id_msg, bytes) else id_msg}"

                        # ============================================================
                        # VERIFICAR MEMORIA ANTES de descargar el correo completo
                        # Usa SET en memoria para verificación O(1)
                        # ============================================================
                        if not forzar_escaneo and message_id in message_ids_procesados:
                            correos_saltados += 1
                            self.correos_saltados_total = correos_saltados
                            # Actualizar progreso cada 500 correos saltados
                            if correos_saltados % 500 == 0:
                                self.registrar(f"Verificados {idx}/{total_en_carpeta} - Saltados: {correos_saltados}")
                            continue

                        # Solo ahora descargamos el correo completo (correo NUEVO)
                        correos_nuevos += 1
                        correos_escaneados += 1
                        self.correos_procesados_total += 1  # Contador para UI en tiempo real
                        self.correo_actual = correos_nuevos  # Mostrar progreso de correos NUEVOS
                        # Nota: Ya no actualizamos BD aquí, el progreso viene de memoria

                        resultado, datos_msg = mail.fetch(id_msg, '(RFC822)')
                        if resultado != 'OK':
                            continue

                        correo_crudo = datos_msg[0][1]
                        msg = email.message_from_bytes(correo_crudo)

                        asunto = self.decodificar_cabecera(msg['Subject'])
                        remitente = self.decodificar_cabecera(msg['From'])
                        fecha_str = msg['Date']

                        # === LOG DEBUG: Correo siendo analizado ===
                        remitente_corto = remitente[:60] if remitente else 'Desconocido'
                        asunto_corto = asunto[:70] if asunto else 'Sin asunto'
                        logger.debug(f"[CORREO] De: {remitente_corto} | Asunto: {asunto_corto}")

                        # Parsear fecha
                        try:
                            tupla_fecha = email.utils.parsedate_tz(fecha_str)
                            if tupla_fecha:
                                fecha_correo = datetime.fromtimestamp(
                                    email.utils.mktime_tz(tupla_fecha)
                                )
                            else:
                                fecha_correo = datetime.now()
                        except (ValueError, TypeError, OverflowError):
                            fecha_correo = datetime.now()

                        # Actualizar fecha más reciente de esta carpeta
                        if fecha_mas_reciente is None or fecha_correo > fecha_mas_reciente:
                            fecha_mas_reciente = fecha_correo

                        # Verificar filtro por dominios (nuevo sistema)
                        # Si hay dominios_filtro, usar eso; si no, usar palabras_clave (deprecado)
                        if dominios_filtro:
                            if not self.coincide_dominio(remitente, dominios_filtro):
                                logger.debug(f"[SKIP] Dominio no coincide con filtro: {remitente_corto}")
                                CorreoProcesado.registrar_procesado(
                                    cuenta.id, message_id, carpeta, fecha_correo,
                                    remitente[:255], asunto[:500], False, 0
                                )
                                continue
                        elif palabras_clave:
                            # Compatibilidad hacia atrás con palabras clave
                            if not self.coincide_palabras_clave(asunto, remitente, palabras_clave):
                                logger.debug(f"[SKIP] Palabras clave no coinciden: {asunto_corto}")
                                CorreoProcesado.registrar_procesado(
                                    cuenta.id, message_id, carpeta, fecha_correo,
                                    remitente[:255], asunto[:500], False, 0
                                )
                                continue
                        # Si no hay filtro (ni dominios ni palabras clave), procesar todos

                        # Contador de PDFs para ESTE correo especifico (se resetea por correo)
                        pdfs_este_correo = 0

                        # Procesar adjuntos
                        for parte in msg.walk():
                            if self.detener_solicitado:
                                break

                            tipo_contenido = parte.get_content_type()
                            nombre_archivo = parte.get_filename()

                            if nombre_archivo and tipo_contenido == 'application/pdf':
                                nombre_archivo = self.decodificar_cabecera(nombre_archivo)

                                if not nombre_archivo.lower().endswith('.pdf'):
                                    continue

                                contenido = parte.get_payload(decode=True)
                                if not contenido:
                                    continue

                                # Log detallado: PDF encontrado
                                tamano_kb = len(contenido) / 1024
                                logger.debug(f"[PDF] Encontrado: {nombre_archivo[:50]} ({tamano_kb:.1f} KB)")
                                if self.scan_logger:
                                    self.scan_logger.pdf_encontrado(nombre_archivo, len(contenido), remitente[:50])

                                # Calcular hash del archivo
                                hash_archivo = self.obtener_hash_archivo(contenido)

                                # Verificar si ya procesamos este archivo en ESTE escaneo
                                # (a menos que dev_permitir_duplicados esté activo)
                                if hash_archivo in self.hashes_descargados and not dev_permitir_duplicados:
                                    self.pdfs_duplicados += 1
                                    logger.debug(f"[DUPLICADO] {nombre_archivo[:50]} ya procesado en este escaneo")
                                    self.registrar(f"PDF duplicado en este escaneo: {nombre_archivo}",
                                                   nivel='info', categoria='pdf',
                                                   archivo_nombre=nombre_archivo,
                                                   correo_message_id=message_id)
                                    # Log detallado: duplicado
                                    if self.scan_logger:
                                        self.scan_logger.pdf_duplicado(nombre_archivo, hash_archivo)
                                    continue
                                elif dev_permitir_duplicados and hash_archivo in self.hashes_descargados:
                                    self.registrar(f"[DEV] Permitiendo duplicado: {nombre_archivo}",
                                                   nivel='warning', categoria='pdf')

                                self.hashes_descargados.add(hash_archivo)

                                # Verificar si existe en el repositorio (archivo físico ya guardado)
                                archivo_repo_existente = ArchivoRepositorio.buscar_por_hash(hash_archivo)
                                es_reutilizado = archivo_repo_existente is not None

                                # Variables para compañía (se determinará del contenido del PDF)
                                compania = None
                                nombre_cia = None
                                metodo_deteccion = 'ninguno'

                                # Construir nombre temporal de archivo
                                remitente_limpio = self.sanitizar_nombre(
                                    remitente.split('<')[0].strip()[:30]
                                )
                                asunto_limpio = self.sanitizar_nombre(asunto[:40])
                                fecha_limpia = fecha_correo.strftime('%Y%m%d')

                                nuevo_nombre = f"{remitente_limpio}_{asunto_limpio}_{fecha_limpia}.pdf"
                                ruta_salida = os.path.join(directorio_salida, nuevo_nombre)

                                # Manejar conflictos
                                contador = 1
                                while os.path.exists(ruta_salida):
                                    nuevo_nombre = f"{remitente_limpio}_{asunto_limpio}_{fecha_limpia}_{contador}.pdf"
                                    ruta_salida = os.path.join(directorio_salida, nuevo_nombre)
                                    contador += 1

                                # ============================================================
                                # VALIDACIÓN DE PÓLIZA (si está activada)
                                # ============================================================
                                if validar_polizas:
                                    from app.extractor.pdf_parser import extraer_y_validar_poliza

                                    # Guardar en archivo temporal para validar
                                    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                                        tmp.write(contenido)
                                        tmp_path = tmp.name

                                    try:
                                        # Validar si es póliza (pasando dev_options para posibles bypasses)
                                        resultado_val = extraer_y_validar_poliza(tmp_path, nombre_archivo, dev_options)

                                        if not resultado_val['es_valida']:
                                            # No es póliza válida - no guardar
                                            os.unlink(tmp_path)
                                            motivo = resultado_val['motivo_rechazo'] or 'desconocido'
                                            logger.debug(f"[NO VALIDO] {nombre_archivo[:40]}: {motivo}")
                                            self.registrar(f"  [SKIP] {nombre_archivo[:40]}... ({motivo})",
                                                           nivel='info', categoria='pdf',
                                                           archivo_nombre=nombre_archivo,
                                                           correo_message_id=message_id,
                                                           datos_extra={'motivo': motivo, 'remitente': remitente[:50]})
                                            # Log detallado: PDF descartado
                                            if self.scan_logger:
                                                self.scan_logger.pdf_descartado(nombre_archivo, motivo)
                                            continue

                                        # ============================================================
                                        # DETECTAR COMPAÑÍA DESDE CONTENIDO DEL PDF
                                        # ============================================================
                                        datos_extraidos = resultado_val.get('datos', {})
                                        texto_pdf = resultado_val.get('texto', '')

                                        if DETECTOR_COMPANIA_DISPONIBLE and texto_pdf:
                                            resultado_deteccion = detectar_compania_en_pdf(texto_pdf, remitente)
                                            if resultado_deteccion.compania_id and resultado_deteccion.confianza > 0.5:
                                                nombre_cia = resultado_deteccion.nombre_formal
                                                metodo_deteccion = resultado_deteccion.metodo
                                                # Buscar compañía existente (NO crear durante escaneo)
                                                compania = Compania.query.filter(
                                                    Compania.nombre.ilike(f'%{nombre_cia}%')
                                                ).first()
                                                # Si no existe, NO la creamos ahora - se creará en consolidación
                                                # Solo guardamos el nombre para el buffer

                                        # Fallback: detectar por dominio del remitente (solo lectura)
                                        if not compania:
                                            compania = Compania.detectar_solo(remitente)
                                            metodo_deteccion = 'dominio_email'

                                        if compania:
                                            nombre_cia = compania.nombre
                                        # Si no hay compania, nombre_cia ya tiene el valor detectado

                                        # ============================================================
                                        # GENERAR NOMBRE DESDE DATOS EXTRAÍDOS
                                        # ============================================================
                                        nuevo_nombre, _ = self._generar_nombre_desde_datos(
                                            datos_extraidos, fecha_correo, directorio_salida, nombre_cia
                                        )

                                        # Limpiar archivo temporal
                                        try:
                                            os.unlink(tmp_path)
                                        except OSError:
                                            pass  # Archivo temporal ya eliminado o inaccesible

                                    except Exception as e_val:
                                        # Si falla validación, fallback a detección por dominio
                                        if not compania:
                                            compania = Compania.detectar_solo(remitente)
                                            if compania:
                                                # compania.incrementar_contador()  # Deshabilitado: se actualiza en consolidación
                                                nombre_cia = compania.nombre
                                        try:
                                            os.unlink(tmp_path)
                                        except OSError:
                                            pass  # Archivo temporal ya eliminado o inaccesible
                                else:
                                    # Sin validación - detectar compañía por dominio
                                    compania = Compania.detectar_solo(remitente)
                                    if compania:
                                        # compania.incrementar_contador()  # Deshabilitado: se actualiza en consolidación
                                        nombre_cia = compania.nombre

                                # ============================================================
                                # GUARDAR PDF DE FORMA ATÓMICA (transacción + filesystem)
                                # ============================================================
                                datos_correo = {
                                    'remitente': remitente,
                                    'asunto': asunto,
                                    'fecha_correo': fecha_correo,
                                    'message_id': message_id,
                                    'cuenta_origen': correo
                                }

                                archivo, exito, mensaje = self._guardar_pdf_atomico(
                                    contenido=contenido,
                                    hash_archivo=hash_archivo,
                                    nuevo_nombre=nuevo_nombre,
                                    datos_correo=datos_correo,
                                    compania=compania,
                                    db_session=db_session,
                                    escaneo=escaneo,
                                    archivo_repo_existente=archivo_repo_existente if es_reutilizado else None
                                )

                                if not exito:
                                    logger.warning(f"[ERROR] Guardando PDF: {mensaje[:60]}")
                                    self.registrar(f"Error guardando PDF: {mensaje}",
                                                   nivel='error', categoria='pdf',
                                                   archivo_nombre=nuevo_nombre,
                                                   correo_message_id=message_id)
                                    # Log detallado: error al guardar
                                    if self.scan_logger:
                                        self.scan_logger.pdf_error(nuevo_nombre, mensaje)
                                    continue

                                if es_reutilizado:
                                    self.registrar(f"Reutilizando archivo del repositorio: {nuevo_nombre}",
                                                   nivel='info', categoria='repositorio')

                                pdfs_encontrados += 1
                                pdfs_carpeta += 1
                                pdfs_este_correo += 1
                                self.pdfs_descargados_total += 1  # Contador para UI en tiempo real
                                nombre_cia_log = nombre_cia if nombre_cia else 'Desconocida'
                                id_documento = archivo.id_documento if archivo else 'ERROR'
                                logger.debug(f"[GUARDADO] {id_documento} [{nombre_cia_log}]")
                                self.registrar(f"{id_documento}: {nuevo_nombre} [{nombre_cia_log}] ({metodo_deteccion})",
                                               nivel='success', categoria='pdf',
                                               archivo_nombre=nuevo_nombre,
                                               correo_message_id=message_id,
                                               datos_extra={'compania': nombre_cia_log, 'tamano': len(contenido), 'metodo_deteccion': metodo_deteccion,
                                                            'remitente': remitente[:50]})
                                # Log detallado: PDF guardado
                                if self.scan_logger:
                                    self.scan_logger.pdf_guardado(nuevo_nombre, nombre_cia_log)

                        # ============================================================
                        # PROCESAR PDFs DESDE ENLACES (Mercantil Andina, etc.)
                        # Si no se encontraron adjuntos PDF, buscar enlaces de descarga
                        # ============================================================
                        if pdfs_este_correo == 0:
                            logger.debug(f"[INFO] Sin adjuntos PDF en correo de {remitente_corto}")

                        nombre_cia_enlace, config_cia_enlace = self.es_correo_con_enlace_descarga(remitente)

                        # Calcular antigüedad del correo
                        dias_antiguedad = (datetime.now() - fecha_correo).days

                        if nombre_cia_enlace and pdfs_este_correo == 0 and dias_antiguedad <= 89:
                            logger.debug(f"[ENLACE] Buscando PDF en enlaces de {nombre_cia_enlace}...")
                            # Log de estrategia usada
                            if ESTRATEGIAS_DISPONIBLES:
                                self.registrar(f"Usando estrategia enlace_html para {nombre_cia_enlace}",
                                               nivel='debug', categoria='estrategia')
                            # Buscar contenido HTML del correo
                            html_content = None
                            for parte in msg.walk():
                                if parte.get_content_type() == 'text/html':
                                    payload = parte.get_payload(decode=True)
                                    if payload:
                                        html_content = payload.decode('utf-8', errors='replace')
                                    break

                            if html_content:
                                enlaces = self.extraer_enlaces_descarga(html_content, config_cia_enlace)
                                if enlaces:
                                    logger.debug(f"[ENLACE] Encontrados {len(enlaces)} enlaces de descarga")

                                for idx_enlace, url_descarga in enumerate(enlaces[:3]):  # Max 3 enlaces por correo
                                    if self.detener_solicitado:
                                        break

                                    contenido, error = self.descargar_pdf_desde_url(url_descarga)

                                    if contenido:
                                        tamano_kb = len(contenido) / 1024
                                        logger.debug(f"[PDF-ENLACE] Descargado desde enlace {idx_enlace+1} ({tamano_kb:.1f} KB)")
                                        # Calcular hash del archivo
                                        hash_archivo = self.obtener_hash_archivo(contenido)

                                        # Verificar si ya procesamos este archivo en ESTE escaneo
                                        if hash_archivo in self.hashes_descargados:
                                            self.pdfs_duplicados += 1
                                            self.registrar(f"PDF duplicado en este escaneo: enlace {idx_enlace + 1}")
                                            continue

                                        self.hashes_descargados.add(hash_archivo)

                                        # Verificar si existe en el repositorio
                                        archivo_repo_existente = ArchivoRepositorio.buscar_por_hash(hash_archivo)
                                        es_reutilizado = archivo_repo_existente is not None

                                        # Variables para compañía (se determinará del contenido del PDF)
                                        compania = None
                                        nombre_cia = None
                                        metodo_deteccion = 'ninguno'

                                        # Construir nombre temporal de archivo
                                        remitente_limpio = self.sanitizar_nombre(
                                            remitente.split('<')[0].strip()[:30]
                                        )
                                        asunto_limpio = self.sanitizar_nombre(asunto[:40])
                                        fecha_limpia = fecha_correo.strftime('%Y%m%d')

                                        sufijo = f"_{idx_enlace}" if idx_enlace > 0 else ""
                                        nuevo_nombre = f"{remitente_limpio}_{asunto_limpio}_{fecha_limpia}{sufijo}.pdf"
                                        ruta_salida = os.path.join(directorio_salida, nuevo_nombre)

                                        # Manejar conflictos
                                        contador = 1
                                        while os.path.exists(ruta_salida):
                                            nuevo_nombre = f"{remitente_limpio}_{asunto_limpio}_{fecha_limpia}{sufijo}_{contador}.pdf"
                                            ruta_salida = os.path.join(directorio_salida, nuevo_nombre)
                                            contador += 1

                                        # ============================================================
                                        # VALIDACIÓN DE PÓLIZA (si está activada)
                                        # ============================================================
                                        if validar_polizas:
                                            from app.extractor.pdf_parser import extraer_y_validar_poliza

                                            # Guardar en archivo temporal para validar
                                            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                                                tmp.write(contenido)
                                                tmp_path = tmp.name

                                            try:
                                                # Validar si es póliza (pasando dev_options para posibles bypasses)
                                                resultado_val = extraer_y_validar_poliza(tmp_path, nuevo_nombre, dev_options)

                                                if not resultado_val['es_valida']:
                                                    # No es póliza válida - no guardar
                                                    os.unlink(tmp_path)
                                                    motivo = resultado_val['motivo_rechazo'] or 'desconocido'
                                                    self.registrar(f"  [SKIP enlace] {nuevo_nombre[:40]}... ({motivo})")
                                                    continue

                                                # ============================================================
                                                # DETECTAR COMPAÑÍA DESDE CONTENIDO DEL PDF
                                                # ============================================================
                                                datos_extraidos = resultado_val.get('datos', {})
                                                texto_pdf = resultado_val.get('texto', '')

                                                if DETECTOR_COMPANIA_DISPONIBLE and texto_pdf:
                                                    resultado_deteccion = detectar_compania_en_pdf(texto_pdf, remitente)
                                                    if resultado_deteccion.compania_id and resultado_deteccion.confianza > 0.5:
                                                        nombre_cia = resultado_deteccion.nombre_formal
                                                        metodo_deteccion = resultado_deteccion.metodo
                                                        # Buscar compañía existente (NO crear durante escaneo)
                                                        compania = db_session.query(Compania).filter(
                                                            Compania.nombre.ilike(f'%{nombre_cia}%')
                                                        ).first()
                                                        # Si no existe, NO la creamos - se creará en consolidación

                                                # Fallback: detectar por dominio del remitente (solo lectura)
                                                if not compania:
                                                    compania = Compania.detectar_solo(remitente)
                                                    metodo_deteccion = 'dominio_email'

                                                if compania:
                                                    nombre_cia = compania.nombre
                                                # Si no hay compania, nombre_cia ya tiene el valor detectado

                                                # ============================================================
                                                # GENERAR NOMBRE DESDE DATOS EXTRAÍDOS
                                                # ============================================================
                                                nuevo_nombre, _ = self._generar_nombre_desde_datos(
                                                    datos_extraidos, fecha_correo, directorio_salida, nombre_cia
                                                )

                                                # Limpiar archivo temporal
                                                try:
                                                    os.unlink(tmp_path)
                                                except OSError:
                                                    pass  # Archivo temporal ya eliminado

                                            except Exception as e_val:
                                                # Si falla validación, fallback a detección por dominio
                                                if not compania:
                                                    compania = Compania.detectar_solo(remitente)
                                                    if compania:
                                                        # compania.incrementar_contador()  # Deshabilitado: se actualiza en consolidación
                                                        nombre_cia = compania.nombre
                                                try:
                                                    os.unlink(tmp_path)
                                                except OSError:
                                                    pass  # Archivo temporal ya eliminado
                                        else:
                                            # Sin validación - detectar compañía por dominio
                                            compania = Compania.detectar_solo(remitente)
                                            if compania:
                                                # compania.incrementar_contador()  # Deshabilitado: se actualiza en consolidación
                                                nombre_cia = compania.nombre

                                        # ============================================================
                                        # GUARDAR PDF DE FORMA ATÓMICA (transacción + filesystem)
                                        # ============================================================
                                        datos_correo = {
                                            'remitente': remitente,
                                            'asunto': asunto,
                                            'fecha_correo': fecha_correo,
                                            'message_id': message_id,
                                            'cuenta_origen': correo
                                        }

                                        archivo, exito, mensaje = self._guardar_pdf_atomico(
                                            contenido=contenido,
                                            hash_archivo=hash_archivo,
                                            nuevo_nombre=nuevo_nombre,
                                            datos_correo=datos_correo,
                                            compania=compania,
                                            db_session=db_session,
                                            escaneo=escaneo,
                                            archivo_repo_existente=archivo_repo_existente if es_reutilizado else None
                                        )

                                        if not exito:
                                            logger.warning(f"[ERROR] Guardando PDF desde enlace: {mensaje[:60]}")
                                            self.registrar(f"Error guardando PDF desde enlace: {mensaje}",
                                                           nivel='error', categoria='pdf',
                                                           archivo_nombre=nuevo_nombre,
                                                           correo_message_id=message_id)
                                            continue

                                        if es_reutilizado:
                                            self.registrar(f"Reutilizando archivo del repositorio: {nuevo_nombre}",
                                                           nivel='info', categoria='repositorio')

                                        pdfs_encontrados += 1
                                        pdfs_carpeta += 1
                                        pdfs_este_correo += 1
                                        self.pdfs_descargados_total += 1  # Contador para UI en tiempo real
                                        nombre_cia_log = nombre_cia if nombre_cia else nombre_cia_enlace
                                        id_documento = archivo.id_documento if archivo else 'ERROR'
                                        logger.debug(f"[GUARDADO] {id_documento} [{nombre_cia_log}] (desde enlace)")
                                        self.registrar(f"{id_documento}: {nuevo_nombre} [{nombre_cia_log}] ({metodo_deteccion}) (desde enlace)",
                                                       nivel='success', categoria='pdf',
                                                       archivo_nombre=nuevo_nombre,
                                                       correo_message_id=message_id,
                                                       datos_extra={'compania': nombre_cia, 'fuente': 'enlace'})

                                    elif error:
                                        remitente_corto = remitente.split('<')[0].strip()[:30] if remitente else 'Desconocido'
                                        asunto_corto = asunto[:40] if asunto else 'Sin asunto'

                                        # Categorizar el error
                                        error_lower = error.lower()
                                        if 'no es pdf' in error_lower or 'content-type' in error_lower:
                                            # Enlace no es PDF - esperado para algunos correos
                                            tipo = "NO-PDF"
                                        elif 'timeout' in error_lower:
                                            tipo = "TIMEOUT"
                                        elif 'HTTP 401' in error or 'HTTP 403' in error:
                                            # Enlace expirado o requiere autenticación
                                            tipo = "EXPIRADO"
                                        elif error.startswith('HTTP'):
                                            tipo = "HTTP"
                                        elif 'conexión' in error_lower or 'connection' in error_lower:
                                            tipo = "CONEXION"
                                        else:
                                            tipo = "ERROR"

                                        self.registrar(f"[{tipo}] [{remitente_corto}] '{asunto_corto}': {error[:50]}",
                                                       nivel='warning', categoria='pdf',
                                                       correo_message_id=message_id,
                                                       datos_extra={'tipo_error': tipo, 'error': error[:100],
                                                                    'remitente': remitente_corto})

                        # Registrar correo como procesado
                        # Usamos pdfs_este_correo (no pdfs_carpeta) para saber si ESTE correo tenia PDFs
                        tiene_pdfs = pdfs_este_correo > 0
                        if tiene_pdfs:
                            correos_con_pdf_carpeta += 1
                        CorreoProcesado.registrar_procesado(
                            cuenta.id, message_id, carpeta, fecha_correo,
                            remitente[:255] if remitente else None,
                            asunto[:500] if asunto else None,
                            tiene_pdfs, pdfs_este_correo
                        )

                    # Actualizar historial de la carpeta al terminar
                    if correos_nuevos > 0 or correos_saltados > 0:
                        HistorialEscaneoCarpeta.actualizar_historial(
                            cuenta.id, carpeta, fecha_mas_reciente,
                            correos_nuevos, correos_con_pdf_carpeta, pdfs_carpeta
                        )

                        # Registrar rango de cobertura para tracking de ventanas de tiempo
                        if fecha_desde or fecha_hasta:
                            RangoCobertura.registrar_cobertura(
                                cuenta_gmail_id=cuenta.id,
                                carpeta=carpeta,
                                fecha_inicio=fecha_desde,
                                fecha_fin=fecha_hasta or datetime.now().date(),
                                escaneo_id=self.escaneo_id
                            )

                        db_session.commit()

                    # Resumen de la carpeta
                    self.registrar(f"Carpeta completada: {correos_nuevos} nuevos procesados, {correos_saltados} en memoria (saltados), {pdfs_carpeta} PDFs",
                                   nivel='success', categoria='carpeta',
                                   datos_extra={'correos_nuevos': correos_nuevos,
                                                'correos_saltados': correos_saltados,
                                                'pdfs': pdfs_carpeta,
                                                'correos_con_pdf': correos_con_pdf_carpeta})

                except Exception as e:
                    logger.warning(f"Error en carpeta {carpeta}: {e}")
                    self.registrar(f"Error en {carpeta}: {e}", nivel='error', categoria='carpeta',
                                   datos_extra={'exception': str(e)})
                    # Limpiar transacción para poder continuar con siguiente carpeta
                    try:
                        db_session.rollback()
                    except Exception:
                        pass

            # Conexión completada exitosamente
            self.carpeta_actual = None
            self.registrar(f"Cuenta completada: {correos_escaneados} nuevos | {self.correos_saltados_total} saltados | {pdfs_encontrados} PDFs",
                           nivel='success', categoria='conexion',
                           datos_extra={'correos': correos_escaneados, 'saltados': self.correos_saltados_total,
                                        'pdfs': pdfs_encontrados})
            self.commit_logs()  # Guardar logs de esta cuenta

        except socket.timeout as e:
            logger.error(f"Timeout en conexión IMAP: {e}")
            self.registrar(f"Timeout: el servidor no responde", nivel='error', categoria='conexion',
                           datos_extra={'exception': str(e), 'tipo': 'timeout'})
            # Log detallado del error
            if self.scan_logger:
                self.scan_logger.conexion_fallida(f"Timeout: {e}")
            self.commit_logs()
            raise  # Re-lanzar para que se maneje arriba

        except imaplib.IMAP4.error as e:
            logger.error(f"Error IMAP en cuenta {cuenta.correo_gmail}: {e}")
            self.registrar(f"Error IMAP: {e}", nivel='error', categoria='conexion',
                           datos_extra={'exception': str(e), 'tipo': 'IMAP4.error'})
            # Log detallado del error
            if self.scan_logger:
                self.scan_logger.conexion_fallida(f"IMAP Error: {e}")
            self.commit_logs()
            raise  # Re-lanzar para que se maneje arriba

        except Exception as e:
            logger.exception(f"Error en cuenta {cuenta.correo_gmail}")
            self.registrar(f"Error: {e}", nivel='error', categoria='conexion',
                           datos_extra={'exception': str(e), 'tipo': type(e).__name__})
            # Log detallado del error con traceback
            if self.scan_logger:
                self.scan_logger.error(f"Error inesperado: {type(e).__name__}: {e}", exc_info=True)
            self.commit_logs()
            raise  # Re-lanzar para que se maneje arriba

        finally:
            # CRÍTICO: Garantizar cierre de conexión IMAP en cualquier caso
            if mail is not None:
                try:
                    mail.__exit__(None, None, None)
                except Exception as close_error:
                    logger.warning(f"Error cerrando conexión IMAP: {close_error}")
                    if self.scan_logger:
                        self.scan_logger.warning(f"Error cerrando conexión: {close_error}")

        return correos_escaneados, pdfs_encontrados

    # Mantener compatibilidad con escaneo individual
    def ejecutar_escaneo(self, cuenta, config, directorio_salida):
        """Ejecuta el escaneo de una sola cuenta (compatibilidad)."""
        self.ejecutar_escaneo_multi([cuenta], config, directorio_salida)

    def detener(self):
        """Solicita detener el escaneo y guarda el estado para posible reanudación."""
        self.detener_solicitado = True
        self.estado_motor = self.ESTADO_DETENIDO

        # Guardar estado persistente
        if self.state_context:
            self._actualizar_progreso_estado()
            self.state_context.stop()
            self.registrar("Estado guardado para reanudación posterior")

        # Si está pausado, reanudar para que pueda terminar
        if self.pausado:
            self.reanudar()
        self.registrar("Detención solicitada...")

    def pausar(self):
        """Pausa el escaneo, consolida PDFs encontrados y guarda el estado actual."""
        if not self.pausado and self.estado_motor == self.ESTADO_EJECUTANDO:
            self.pausado = True
            self.consolidar_al_pausar = True  # Señal para consolidar
            self.evento_consolidacion.clear()  # Se activará cuando termine la consolidación
            self.evento_pausa.clear()  # Bloquea el hilo
            self.estado_motor = self.ESTADO_PAUSADO

            # Guardar estado persistente
            if self.state_context:
                self._actualizar_progreso_estado()
                self.state_context.pause()
                self.registrar("Estado guardado - puede reanudarse más tarde")

            self.registrar("Escaneo pausado")
            return True
        return False

    def esperar_consolidacion(self, timeout: float = 10.0) -> bool:
        """Espera a que la consolidación de pausa termine."""
        return self.evento_consolidacion.wait(timeout=timeout)

    def reanudar(self):
        """Reanuda el escaneo pausado."""
        if self.pausado:
            self.pausado = False
            self.evento_pausa.set()  # Desbloquea el hilo
            self.estado_motor = self.ESTADO_EJECUTANDO

            # Actualizar estado persistente
            if self.state_context:
                self.state_context.resume()

            self.registrar("Escaneo reanudado")
            return True
        return False

    def _actualizar_progreso_estado(self):
        """Actualiza el progreso en el contexto de estado."""
        if not self.state_context:
            return

        # Actualizar cuenta actual
        if self.cuenta_actual:
            self.state_context.set_cuenta_actual(self.cuenta_actual, self.cuenta_index - 1)

        # Actualizar carpeta actual
        if self.cuenta_actual and self.carpeta_actual:
            self.state_context.set_carpeta_actual(
                self.cuenta_actual,
                self.carpeta_actual,
                self.total_correos_carpeta
            )

        # Actualizar índice de mensaje
        if self.cuenta_actual:
            self.state_context.update_mensaje_idx(self.cuenta_actual, self.correo_actual)

        # Sincronizar hashes
        for h in self.hashes_descargados:
            if not self.state_context.es_hash_procesado(h):
                self.state_context.registrar_pdf(h)

    def esperar_si_pausado(self):
        """Espera si el escaneo está pausado. Retorna False si debe detenerse."""
        # Si hay solicitud de consolidar al pausar, hacerlo una vez
        if self.pausado and self.consolidar_al_pausar:
            self._consolidar_buffer_parcial()
            self.consolidar_al_pausar = False
            self.evento_consolidacion.set()  # Señalizar que terminó

        while self.pausado and not self.detener_solicitado:
            self.evento_pausa.wait(timeout=0.5)
        return not self.detener_solicitado

    def _consolidar_buffer_parcial(self):
        """Consolida el buffer actual a la BD (para pausas parciales)."""
        if not self.scan_buffer or (not self.scan_buffer.pdfs and not self.scan_buffer.archivos_repositorio):
            return 0

        try:
            from app.utils.db_session import thread_session
            from app.models import Escaneo

            with thread_session(self.app) as session:
                resultado = self.scan_buffer.consolidar_a_bd(session)
                pdfs_insertados = resultado.get('pdfs_insertados', 0)

                # Actualizar contador del escaneo
                if pdfs_insertados > 0:
                    escaneo = session.query(Escaneo).get(self.escaneo_id)
                    if escaneo:
                        escaneo.pdfs_descargados = (escaneo.pdfs_descargados or 0) + pdfs_insertados
                        session.commit()

                # Resetear contadores del motor (ya están consolidados en BD)
                self.pdfs_descargados_total = 0
                self.correos_procesados_total = 0

                self.registrar(f"Consolidación parcial: {pdfs_insertados} PDFs guardados",
                               nivel='success', categoria='sistema')
                return pdfs_insertados

        except Exception as e:
            self.registrar(f"Error en consolidación parcial: {e}",
                           nivel='error', categoria='sistema')
            return 0

    def obtener_estado_detallado(self):
        """Retorna información detallada del estado del motor."""
        estado = {
            'estado_motor': self.estado_motor,
            'pausado': self.pausado,
            'cuenta_actual': self.cuenta_actual,
            'cuenta_index': self.cuenta_index,
            'total_cuentas': self.total_cuentas,
            'correo_actual': self.correo_actual,
            'total_correos_carpeta': self.total_correos_carpeta,
            'correos_en_memoria': self.correos_en_memoria,
            'total_en_rango': self.total_en_rango,
            'correos_saltados': self.correos_saltados_total,
            'pdfs_duplicados': self.pdfs_duplicados,
            'correos_procesados_total': self.correos_procesados_total,
            'pdfs_descargados_total': self.pdfs_descargados_total
        }

        # Estadísticas del buffer (PDFs pendientes de consolidar)
        if self.scan_buffer:
            stats = self.scan_buffer.obtener_estadisticas()
            estado['pdfs_en_buffer'] = stats['pdfs']
            estado['correos_en_buffer'] = stats['correos']
        else:
            estado['pdfs_en_buffer'] = 0
            estado['correos_en_buffer'] = 0

        # Agregar info del estado persistente
        if self.state_context:
            estado['estado_persistente'] = self.state_context.get_resumen()
            estado['puede_reanudar'] = self.state_context.can_resume

        return estado

    def tiene_estado_guardado(self) -> bool:
        """Verifica si existe un estado guardado para este escaneo."""
        if self.state_context:
            return self.state_context.can_resume
        return False

    def restaurar_desde_estado(self) -> bool:
        """Restaura el progreso desde un estado guardado."""
        if not self.state_context or not self.state_context.can_resume:
            return False

        progress = self.state_context.progress

        # Restaurar contadores
        self.hashes_descargados = set(progress.hashes_procesados)
        self.cuenta_index = progress.cuenta_actual_idx

        # Restaurar cuenta actual
        if progress.orden_cuentas and progress.cuenta_actual_idx < len(progress.orden_cuentas):
            self.cuenta_actual = progress.orden_cuentas[progress.cuenta_actual_idx]
            cuenta_prog = progress.cuentas.get(self.cuenta_actual)
            if cuenta_prog:
                self.carpeta_actual = cuenta_prog.carpeta_actual
                self.correo_actual = cuenta_prog.mensaje_idx

        self.registrar(f"Estado restaurado - PDFs: {progress.total_pdfs}, Correos: {progress.total_correos}")
        return True


# Almacén global de motores activos
motores_activos = {}


def obtener_motor(escaneo_id):
    """Obtiene un motor activo por ID de escaneo."""
    return motores_activos.get(escaneo_id)


def crear_motor(escaneo_id, app):
    """Crea y registra un nuevo motor."""
    motor = MotorExtractorWeb(escaneo_id, app)
    motores_activos[escaneo_id] = motor
    return motor


def eliminar_motor(escaneo_id):
    """Elimina un motor del almacén."""
    if escaneo_id in motores_activos:
        del motores_activos[escaneo_id]


def obtener_escaneos_reanudables():
    """Retorna lista de escaneos que pueden reanudarse."""
    from app.extractor.scan_state import obtener_escaneos_pausados
    return obtener_escaneos_pausados()


def reanudar_escaneo(escaneo_id: int, app) -> bool:
    """
    Reanuda un escaneo pausado/detenido.

    Args:
        escaneo_id: ID del escaneo a reanudar
        app: Instancia de la aplicación Flask

    Returns:
        True si se pudo reanudar, False si no
    """
    from app.extractor.scan_state import ScanStateContext

    # Verificar si hay estado guardado
    context = ScanStateContext(escaneo_id, usuario_id=0)  # usuario_id se carga del JSON
    if not context.can_resume:
        return False

    # Crear motor y restaurar estado
    motor = crear_motor(escaneo_id, app)
    motor.state_context = context

    # Obtener configuración del estado guardado
    progress = context.progress

    # Re-ejecutar con la configuración guardada
    from app.models import CuentaGmail
    with app.app_context():
        from app import db
        cuentas = db.session.query(CuentaGmail).filter(
            CuentaGmail.correo_gmail.in_(progress.orden_cuentas)
        ).all()

        if cuentas:
            motor.ejecutar_escaneo_multi(cuentas, progress.config, progress.directorio_salida)
            return True

    return False
