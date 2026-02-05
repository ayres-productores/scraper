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
from datetime import datetime, timedelta
from threading import Thread, Event
from time import sleep
from flask import current_app

# Importar sistema de estrategias por compañía
try:
    from app.extractor.companias import obtener_estrategia, obtener_compania
    ESTRATEGIAS_DISPONIBLES = True
except ImportError:
    ESTRATEGIAS_DISPONIBLES = False
    obtener_estrategia = None
    obtener_compania = None


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

    def __init__(self, escaneo_id, app):
        self.escaneo_id = escaneo_id
        self.app = app
        self.hashes_descargados = set()
        self.detener_solicitado = False
        self.pausado = False
        self.evento_pausa = Event()
        self.evento_pausa.set()  # Inicialmente no pausado (evento activo)
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
        self.logs_pendientes = 0  # Contador para commit periódico

    def registrar(self, mensaje, nivel='info', categoria='sistema',
                  correo_message_id=None, archivo_nombre=None, datos_extra=None):
        """Registra un mensaje de log (memoria + base de datos)."""
        prefijo = ""
        if self.cuenta_actual:
            prefijo = f"[{self.cuenta_actual}] "

        # Log en memoria para la UI en tiempo real
        self.logs.append({
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'mensaje': f"{prefijo}{mensaje}",
            'nivel': nivel
        })

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
            except:
                pass

    def probar_conexion(self, correo, contrasena):
        """Prueba la conexión a Gmail."""
        try:
            mail = imaplib.IMAP4_SSL(self.SERVIDOR_IMAP, self.PUERTO_IMAP)
            mail.login(correo, contrasena)
            mail.logout()
            return True, "Conexión exitosa"
        except imaplib.IMAP4.error as e:
            return False, f"Error de autenticación: {str(e)}"
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
        thread = Thread(target=self._escanear_multi_con_contexto,
                       args=(cuenta_ids, config, directorio_salida))
        thread.daemon = True
        thread.start()

    def _escanear_multi_con_contexto(self, cuenta_ids, config, directorio_salida):
        """Ejecuta el escaneo multi-cuenta dentro del contexto de la aplicación."""
        with self.app.app_context():
            self._escanear_multi(cuenta_ids, config, directorio_salida)

    def _escanear_multi(self, cuenta_ids, config, directorio_salida):
        """Realiza el escaneo de múltiples cuentas de Gmail secuencialmente."""
        from app import db
        from app.models import Escaneo, CuentaGmail

        escaneo = Escaneo.query.get(self.escaneo_id)
        if not escaneo:
            return

        # Re-consultar las cuentas dentro del contexto de este hilo
        cuentas = CuentaGmail.query.filter(CuentaGmail.id.in_(cuenta_ids)).all()
        if not cuentas:
            escaneo.estado = 'error'
            escaneo.mensaje_error = 'No se encontraron cuentas validas'
            escaneo.fecha_fin = datetime.utcnow()
            db.session.commit()
            return

        # Cargar hashes de archivos ya descargados para evitar duplicados
        from app.models import ArchivoDescargado
        hashes_existentes = ArchivoDescargado.query.filter(
            ArchivoDescargado.hash_archivo.isnot(None)
        ).with_entities(ArchivoDescargado.hash_archivo).all()
        self.hashes_descargados = set(h[0] for h in hashes_existentes)
        self.registrar(f"Cargados {len(self.hashes_descargados)} hashes de archivos existentes",
                       nivel='info', categoria='sistema')

        self.estado_motor = self.ESTADO_EJECUTANDO
        self.total_cuentas = len(cuentas)
        total_correos = 0
        total_pdfs = 0

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
                db.session.commit()

                self.registrar(f"Procesando cuenta {self.cuenta_index}/{self.total_cuentas}",
                               nivel='info', categoria='conexion')

                try:
                    correos, pdfs = self._escanear_cuenta(cuenta, config, directorio_salida, escaneo)
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

                # Actualizar totales después de cada cuenta
                escaneo.correos_escaneados = total_correos
                escaneo.pdfs_descargados = total_pdfs
                db.session.commit()

            # Finalizar escaneo exitosamente
            escaneo.estado = 'cancelado' if self.detener_solicitado else 'completado'
            escaneo.fecha_fin = datetime.utcnow()
            escaneo.cuenta_actual = None
            self.estado_motor = self.ESTADO_COMPLETADO if not self.detener_solicitado else self.ESTADO_DETENIDO
            db.session.commit()

            self.registrar(f"Escaneo finalizado: {total_correos} correos, {total_pdfs} PDFs",
                           nivel='success', categoria='sistema',
                           datos_extra={'correos': total_correos, 'pdfs': total_pdfs,
                                        'saltados': self.correos_saltados_total,
                                        'duplicados': self.pdfs_duplicados})
            self.commit_logs()  # Guardar logs pendientes

            # Verificar duplicados al finalizar el escaneo
            try:
                from app.extractor.verificador_duplicados import verificar_duplicados_post_escaneo
                self.registrar("Iniciando verificación de duplicados post-escaneo...",
                               nivel='info', categoria='sistema')
                resultados_dup = verificar_duplicados_post_escaneo(
                    escaneo_id=escaneo.id,
                    db_session=db.session,
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
            self.commit_logs()  # Guardar logs antes de terminar
            self.estado_motor = self.ESTADO_DETENIDO

            try:
                escaneo.estado = 'error'
                escaneo.mensaje_error = error_msg
                escaneo.fecha_fin = datetime.utcnow()
                escaneo.cuenta_actual = None
                escaneo.correos_escaneados = total_correos
                escaneo.pdfs_descargados = total_pdfs
                db.session.commit()
            except:
                pass  # Si falla el commit, al menos intentamos

    def _obtener_todas_carpetas(self, mail):
        """
        Obtiene todas las carpetas disponibles en la cuenta IMAP.
        Filtra carpetas del sistema y devuelve una lista limpia.
        """
        carpetas_disponibles = []

        # Carpetas a ignorar (sistema, spam, papelera)
        carpetas_ignorar = [
            '[Gmail]/Spam', '[Gmail]/Papelera', '[Gmail]/Trash',
            '[Gmail]/Borrador', '[Gmail]/Drafts', '[Gmail]/Borradores',
            '[Gmail]/Bin', '[Gmail]/Junk'
        ]
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

    def _escanear_cuenta(self, cuenta, config, directorio_salida, escaneo):
        """Escanea una cuenta individual de Gmail."""
        from app import db
        from app.models import ArchivoDescargado, Compania, CorreoProcesado, HistorialEscaneoCarpeta, DominioRemitente

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

        pdfs_encontrados = 0
        correos_escaneados = 0

        try:
            correo = cuenta.correo_gmail
            contrasena = cuenta.obtener_contrasena_app()

            mail = imaplib.IMAP4_SSL(self.SERVIDOR_IMAP, self.PUERTO_IMAP)
            mail.login(correo, contrasena)
            self.registrar(f"Conectado", nivel='success', categoria='conexion')

            # Actualizar último escaneo de la cuenta
            cuenta.ultimo_escaneo = datetime.utcnow()
            db.session.commit()

            # Obtener todas las carpetas disponibles si no se especificaron
            if carpetas == ['INBOX'] or not carpetas:
                carpetas = self._obtener_todas_carpetas(mail)
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
                        row[0] for row in db.session.query(CorreoProcesado.message_id).filter_by(
                            cuenta_gmail_id=cuenta.id,
                            carpeta=carpeta
                        ).all()
                    )
                    correos_en_memoria = len(message_ids_procesados)

                    self.total_correos_carpeta = total_en_carpeta
                    self.correos_en_memoria = correos_en_memoria
                    self.total_en_rango = total_en_carpeta

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

                    print(f"[DEBUG] Iniciando bucle: {total_en_carpeta} correos en {carpeta}", flush=True)

                    for idx, id_msg in enumerate(ids_mensajes, 1):
                        # Verificar pausa
                        if not self.esperar_si_pausado():
                            print(f"[DEBUG] SALIDA por esperar_si_pausado() en idx={idx}", flush=True)
                            break

                        if self.detener_solicitado:
                            print(f"[DEBUG] SALIDA por detener_solicitado en idx={idx}", flush=True)
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
                        self.correo_actual = correos_nuevos  # Mostrar progreso de correos NUEVOS

                        # Actualizar progreso periódicamente (cada 10 correos NUEVOS)
                        if correos_escaneados % 10 == 0:
                            escaneo.correos_escaneados = correos_escaneados
                            escaneo.pdfs_descargados = pdfs_encontrados
                            db.session.commit()

                        resultado, datos_msg = mail.fetch(id_msg, '(RFC822)')
                        if resultado != 'OK':
                            continue

                        correo_crudo = datos_msg[0][1]
                        msg = email.message_from_bytes(correo_crudo)

                        asunto = self.decodificar_cabecera(msg['Subject'])
                        remitente = self.decodificar_cabecera(msg['From'])
                        fecha_str = msg['Date']

                        # Parsear fecha
                        try:
                            tupla_fecha = email.utils.parsedate_tz(fecha_str)
                            if tupla_fecha:
                                fecha_correo = datetime.fromtimestamp(
                                    email.utils.mktime_tz(tupla_fecha)
                                )
                            else:
                                fecha_correo = datetime.now()
                        except:
                            fecha_correo = datetime.now()

                        # Actualizar fecha más reciente de esta carpeta
                        if fecha_mas_reciente is None or fecha_correo > fecha_mas_reciente:
                            fecha_mas_reciente = fecha_correo

                        # Verificar filtro por dominios (nuevo sistema)
                        # Si hay dominios_filtro, usar eso; si no, usar palabras_clave (deprecado)
                        if dominios_filtro:
                            if not self.coincide_dominio(remitente, dominios_filtro):
                                CorreoProcesado.registrar_procesado(
                                    cuenta.id, message_id, carpeta, fecha_correo,
                                    remitente[:255], asunto[:500], False, 0
                                )
                                continue
                        elif palabras_clave:
                            # Compatibilidad hacia atrás con palabras clave
                            if not self.coincide_palabras_clave(asunto, remitente, palabras_clave):
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

                                # Verificar duplicados
                                hash_archivo = self.obtener_hash_archivo(contenido)
                                if hash_archivo in self.hashes_descargados:
                                    self.pdfs_duplicados += 1
                                    self.registrar(f"PDF duplicado (ya descargado): {nombre_archivo}",
                                                   nivel='info', categoria='pdf',
                                                   archivo_nombre=nombre_archivo,
                                                   correo_message_id=message_id)
                                    continue

                                self.hashes_descargados.add(hash_archivo)

                                # Detectar o crear compañía
                                compania = Compania.detectar_o_crear(remitente)
                                if compania:
                                    compania.incrementar_contador()

                                # Construir nombre de archivo
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
                                        # Validar si es póliza
                                        resultado_val = extraer_y_validar_poliza(tmp_path, nombre_archivo)

                                        if not resultado_val['es_valida']:
                                            # No es póliza válida - no guardar
                                            os.unlink(tmp_path)
                                            motivo = resultado_val['motivo_rechazo'] or 'desconocido'
                                            self.registrar(f"  [SKIP] {nombre_archivo[:40]}... ({motivo})",
                                                           nivel='info', categoria='pdf',
                                                           archivo_nombre=nombre_archivo,
                                                           correo_message_id=message_id,
                                                           datos_extra={'motivo': motivo, 'remitente': remitente[:50]})
                                            continue

                                        # ============================================================
                                        # RENOMBRAR CON DATOS EXTRAÍDOS (nombre+apellido+bien_asegurado)
                                        # ============================================================
                                        datos_extraidos = resultado_val.get('datos', {})
                                        nuevo_nombre, ruta_salida = self._generar_nombre_desde_datos(
                                            datos_extraidos, fecha_correo, directorio_salida, nombre_cia
                                        )

                                        # Es válida - mover al destino final
                                        os.rename(tmp_path, ruta_salida)

                                    except Exception as e_val:
                                        # Si falla validación, guardar de todos modos
                                        try:
                                            os.rename(tmp_path, ruta_salida)
                                        except:
                                            with open(ruta_salida, 'wb') as f:
                                                f.write(contenido)
                                            try:
                                                os.unlink(tmp_path)
                                            except:
                                                pass
                                else:
                                    # Sin validación - guardar directamente
                                    with open(ruta_salida, 'wb') as f:
                                        f.write(contenido)

                                # Generar ID de documento
                                id_documento = ArchivoDescargado.generar_siguiente_id()

                                # Registrar en base de datos con compañía
                                archivo = ArchivoDescargado(
                                    id_documento=id_documento,
                                    escaneo_id=self.escaneo_id,
                                    nombre_archivo=nuevo_nombre,
                                    ruta_archivo=ruta_salida,
                                    tamano_bytes=len(contenido),
                                    hash_archivo=hash_archivo,
                                    remitente=remitente[:255],
                                    asunto=asunto[:500],
                                    fecha_correo=fecha_correo,
                                    compania_id=compania.id if compania else None,
                                    nombre_compania_original=remitente.split('<')[0].strip()[:255],
                                    cuenta_origen=correo
                                )
                                db.session.add(archivo)
                                db.session.flush()  # Para que el ID se asigne antes del próximo

                                # Registrar dominio del remitente para futuras búsquedas
                                DominioRemitente.registrar_dominio(escaneo.usuario_id, remitente)

                                pdfs_encontrados += 1
                                pdfs_carpeta += 1
                                pdfs_este_correo += 1
                                nombre_cia = compania.nombre if compania else 'Desconocida'
                                self.registrar(f"{id_documento}: {nuevo_nombre} [{nombre_cia}]",
                                               nivel='success', categoria='pdf',
                                               archivo_nombre=nuevo_nombre,
                                               correo_message_id=message_id,
                                               datos_extra={'compania': nombre_cia, 'tamano': len(contenido),
                                                            'remitente': remitente[:50]})

                        # ============================================================
                        # PROCESAR PDFs DESDE ENLACES (Mercantil Andina, etc.)
                        # Si no se encontraron adjuntos PDF, buscar enlaces de descarga
                        # ============================================================
                        nombre_cia_enlace, config_cia_enlace = self.es_correo_con_enlace_descarga(remitente)

                        # Calcular antigüedad del correo
                        dias_antiguedad = (datetime.now() - fecha_correo).days

                        if nombre_cia_enlace and pdfs_este_correo == 0 and dias_antiguedad <= 89:
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

                                for idx_enlace, url_descarga in enumerate(enlaces[:3]):  # Max 3 enlaces por correo
                                    if self.detener_solicitado:
                                        break

                                    contenido, error = self.descargar_pdf_desde_url(url_descarga)

                                    if contenido:
                                        # Verificar duplicados
                                        hash_archivo = self.obtener_hash_archivo(contenido)
                                        if hash_archivo in self.hashes_descargados:
                                            self.pdfs_duplicados += 1
                                            self.registrar(f"PDF duplicado (ya descargado): enlace {idx_enlace + 1}")
                                            continue

                                        self.hashes_descargados.add(hash_archivo)

                                        # Detectar o crear compañía
                                        compania = Compania.detectar_o_crear(remitente)
                                        if compania:
                                            compania.incrementar_contador()

                                        # Construir nombre de archivo
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
                                                # Validar si es póliza
                                                resultado_val = extraer_y_validar_poliza(tmp_path, nuevo_nombre)

                                                if not resultado_val['es_valida']:
                                                    # No es póliza válida - no guardar
                                                    os.unlink(tmp_path)
                                                    motivo = resultado_val['motivo_rechazo'] or 'desconocido'
                                                    self.registrar(f"  [SKIP enlace] {nuevo_nombre[:40]}... ({motivo})")
                                                    continue

                                                # ============================================================
                                                # RENOMBRAR CON DATOS EXTRAÍDOS (nombre+apellido+bien_asegurado)
                                                # ============================================================
                                                datos_extraidos = resultado_val.get('datos', {})
                                                nuevo_nombre, ruta_salida = self._generar_nombre_desde_datos(
                                                    datos_extraidos, fecha_correo, directorio_salida, nombre_cia
                                                )

                                                # Es válida - mover al destino final
                                                os.rename(tmp_path, ruta_salida)

                                            except Exception as e_val:
                                                # Si falla validación, guardar de todos modos
                                                try:
                                                    os.rename(tmp_path, ruta_salida)
                                                except:
                                                    with open(ruta_salida, 'wb') as f:
                                                        f.write(contenido)
                                                    try:
                                                        os.unlink(tmp_path)
                                                    except:
                                                        pass
                                        else:
                                            # Sin validación - guardar directamente
                                            with open(ruta_salida, 'wb') as f:
                                                f.write(contenido)

                                        # Generar ID de documento
                                        id_documento = ArchivoDescargado.generar_siguiente_id()

                                        # Registrar en base de datos
                                        archivo = ArchivoDescargado(
                                            id_documento=id_documento,
                                            escaneo_id=self.escaneo_id,
                                            nombre_archivo=nuevo_nombre,
                                            ruta_archivo=ruta_salida,
                                            tamano_bytes=len(contenido),
                                            hash_archivo=hash_archivo,
                                            remitente=remitente[:255],
                                            asunto=asunto[:500],
                                            fecha_correo=fecha_correo,
                                            compania_id=compania.id if compania else None,
                                            nombre_compania_original=remitente.split('<')[0].strip()[:255],
                                            cuenta_origen=correo
                                        )
                                        db.session.add(archivo)
                                        db.session.flush()

                                        # Registrar dominio del remitente para futuras búsquedas
                                        DominioRemitente.registrar_dominio(escaneo.usuario_id, remitente)

                                        pdfs_encontrados += 1
                                        pdfs_carpeta += 1
                                        pdfs_este_correo += 1
                                        nombre_cia = compania.nombre if compania else nombre_cia_enlace
                                        self.registrar(f"{id_documento}: {nuevo_nombre} [{nombre_cia}] (desde enlace)",
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
                        db.session.commit()

                    # Resumen de la carpeta
                    print(f"[DEBUG] Bucle terminado normalmente. idx final={idx}, total={total_en_carpeta}", flush=True)
                    print(f"[DEBUG] correos_nuevos={correos_nuevos}, correos_saltados={correos_saltados}", flush=True)
                    self.registrar(f"Carpeta completada: {correos_nuevos} nuevos procesados, {correos_saltados} en memoria (saltados), {pdfs_carpeta} PDFs",
                                   nivel='success', categoria='carpeta',
                                   datos_extra={'correos_nuevos': correos_nuevos,
                                                'correos_saltados': correos_saltados,
                                                'pdfs': pdfs_carpeta,
                                                'correos_con_pdf': correos_con_pdf_carpeta})

                except Exception as e:
                    print(f"[DEBUG] EXCEPCION en carpeta {carpeta}: {e}", flush=True)
                    self.registrar(f"Error en {carpeta}: {e}", nivel='error', categoria='carpeta',
                                   datos_extra={'exception': str(e)})

            mail.logout()
            self.carpeta_actual = None
            print(f"[DEBUG] Cuenta {correo} completada exitosamente", flush=True)
            self.registrar(f"Cuenta completada: {correos_escaneados} nuevos | {self.correos_saltados_total} saltados | {pdfs_encontrados} PDFs",
                           nivel='success', categoria='conexion',
                           datos_extra={'correos': correos_escaneados, 'saltados': self.correos_saltados_total,
                                        'pdfs': pdfs_encontrados})
            self.commit_logs()  # Guardar logs de esta cuenta

        except Exception as e:
            print(f"[DEBUG] EXCEPCION en cuenta: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.registrar(f"Error: {e}", nivel='error', categoria='conexion',
                           datos_extra={'exception': str(e), 'tipo': type(e).__name__})
            self.commit_logs()

        return correos_escaneados, pdfs_encontrados

    # Mantener compatibilidad con escaneo individual
    def ejecutar_escaneo(self, cuenta, config, directorio_salida):
        """Ejecuta el escaneo de una sola cuenta (compatibilidad)."""
        self.ejecutar_escaneo_multi([cuenta], config, directorio_salida)

    def detener(self):
        """Solicita detener el escaneo."""
        self.detener_solicitado = True
        self.estado_motor = self.ESTADO_DETENIDO
        # Si está pausado, reanudar para que pueda terminar
        if self.pausado:
            self.reanudar()
        self.registrar("Detención solicitada...")

    def pausar(self):
        """Pausa el escaneo."""
        if not self.pausado and self.estado_motor == self.ESTADO_EJECUTANDO:
            self.pausado = True
            self.evento_pausa.clear()  # Bloquea el hilo
            self.estado_motor = self.ESTADO_PAUSADO
            self.registrar("Escaneo pausado")
            return True
        return False

    def reanudar(self):
        """Reanuda el escaneo pausado."""
        if self.pausado:
            self.pausado = False
            self.evento_pausa.set()  # Desbloquea el hilo
            self.estado_motor = self.ESTADO_EJECUTANDO
            self.registrar("Escaneo reanudado")
            return True
        return False

    def esperar_si_pausado(self):
        """Espera si el escaneo está pausado. Retorna False si debe detenerse."""
        while self.pausado and not self.detener_solicitado:
            self.evento_pausa.wait(timeout=0.5)
        return not self.detener_solicitado

    def obtener_estado_detallado(self):
        """Retorna información detallada del estado del motor."""
        return {
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
            'pdfs_duplicados': self.pdfs_duplicados
        }


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
