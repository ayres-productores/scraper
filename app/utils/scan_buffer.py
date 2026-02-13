"""
Buffer JSON para almacenamiento temporal durante escaneos.

Evita escribir a la BD durante el escaneo para prevenir "database is locked".
Los datos se consolidan a la BD al finalizar el escaneo.

Uso:
    buffer = ScanBuffer(escaneo_id=123)
    buffer.agregar_pdf(datos_pdf)
    buffer.agregar_correo_procesado(datos_correo)

    # Al finalizar:
    buffer.consolidar_a_bd(db_session)
"""

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional, Any

logger = logging.getLogger('app.utils.scan_buffer')

# Detectar directorio base
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BUFFER_DIR = os.path.join(BASE_DIR, 'logs', 'scan_buffers')
os.makedirs(BUFFER_DIR, exist_ok=True)

# Lock global para escritura thread-safe
_buffer_lock = Lock()


def _retry_on_db_lock(func, max_retries=5, base_delay=1.0):
    """
    Ejecuta una función con retry y backoff exponencial en caso de database lock.

    Args:
        func: Función a ejecutar (sin argumentos)
        max_retries: Número máximo de reintentos
        base_delay: Delay base en segundos (se multiplica exponencialmente)

    Returns:
        El resultado de func()

    Raises:
        La última excepción si se agotan los reintentos
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            if 'database is locked' in str(e).lower():
                last_exception = e
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)  # 1, 2, 4, 8, 16 segundos
                    logger.debug(f"DB locked, reintentando en {delay}s (intento {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                continue
            raise  # Re-raise si no es database locked
    raise last_exception


class ScanBuffer:
    """
    Buffer en memoria + JSON para datos de escaneo.

    Almacena temporalmente:
    - PDFs descargados (metadata)
    - Correos procesados
    - Dominios de remitentes

    Al finalizar, consolida todo a la BD en una sola transacción.
    """

    def __init__(self, escaneo_id: int, usuario_id: int = None):
        self.escaneo_id = escaneo_id
        self.usuario_id = usuario_id
        self.archivo_json = os.path.join(BUFFER_DIR, f'escaneo_{escaneo_id}.json')

        # Datos en memoria
        self.pdfs: List[Dict] = []
        self.correos_procesados: List[Dict] = []
        self.dominios: set = set()
        self.archivos_repositorio: List[Dict] = []  # Nuevos archivos en repositorio

        # Contadores
        self.total_pdfs = 0
        self.total_correos = 0
        self.errores = 0

        # Contador interno para IDs temporales únicos
        self._id_counter = 0

        # Cargar datos existentes si hay un buffer previo (recuperación)
        self._cargar_si_existe()

    def generar_id_temporal(self) -> str:
        """Genera un ID temporal único para el buffer."""
        self._id_counter += 1
        return f"TMP-{self.escaneo_id}-{self._id_counter:04d}"

    def _cargar_si_existe(self):
        """Carga datos de un buffer previo si existe (para recuperación)."""
        if os.path.exists(self.archivo_json):
            try:
                with open(self.archivo_json, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    self.pdfs = datos.get('pdfs', [])
                    self.correos_procesados = datos.get('correos_procesados', [])
                    self.dominios = set(datos.get('dominios', []))
                    self.archivos_repositorio = datos.get('archivos_repositorio', [])
                    self.total_pdfs = datos.get('total_pdfs', len(self.pdfs))
                    self.total_correos = datos.get('total_correos', len(self.correos_procesados))
            except Exception:
                pass  # Si falla, empezar limpio

    def _guardar_json(self):
        """Guarda el estado actual a JSON."""
        datos = {
            'escaneo_id': self.escaneo_id,
            'usuario_id': self.usuario_id,
            'timestamp': datetime.utcnow().isoformat(),
            'pdfs': self.pdfs,
            'correos_procesados': self.correos_procesados,
            'dominios': list(self.dominios),
            'archivos_repositorio': self.archivos_repositorio,
            'total_pdfs': self.total_pdfs,
            'total_correos': self.total_correos,
            'errores': self.errores
        }

        with _buffer_lock:
            try:
                # Escribir a archivo temporal primero, luego renombrar (atómico)
                temp_file = self.archivo_json + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(datos, f, ensure_ascii=False, indent=2, default=str)

                # Renombrar es atómico en la mayoría de sistemas
                if os.path.exists(self.archivo_json):
                    os.remove(self.archivo_json)
                os.rename(temp_file, self.archivo_json)
            except Exception as e:
                logger.error(f"Error guardando JSON: {e}")

    def agregar_archivo_repositorio(self, hash_archivo: str, nombre_archivo: str,
                                     ruta_relativa: str, tamano_bytes: int):
        """Registra un nuevo archivo en el repositorio."""
        self.archivos_repositorio.append({
            'hash_archivo': hash_archivo,
            'nombre_original': nombre_archivo,
            'ruta_relativa': ruta_relativa,
            'tamano_bytes': tamano_bytes,
            'fecha_creacion': datetime.utcnow().isoformat()
        })
        self._guardar_json()

    def agregar_pdf(self, id_documento: str, nombre_archivo: str, ruta_archivo: str,
                    tamano_bytes: int, hash_archivo: str, remitente: str, asunto: str,
                    fecha_correo: datetime, compania_id: int = None,
                    nombre_compania: str = None, cuenta_origen: str = None,
                    archivo_repo_id: int = None, archivo_repo_hash: str = None):
        """Agrega un PDF al buffer."""
        self.pdfs.append({
            'id_documento': id_documento,
            'nombre_archivo': nombre_archivo,
            'ruta_archivo': ruta_archivo,
            'tamano_bytes': tamano_bytes,
            'hash_archivo': hash_archivo,
            'remitente': remitente,
            'asunto': asunto,
            'fecha_correo': fecha_correo.isoformat() if fecha_correo else None,
            'compania_id': compania_id,
            'nombre_compania': nombre_compania,
            'cuenta_origen': cuenta_origen,
            'archivo_repo_id': archivo_repo_id,
            'archivo_repo_hash': archivo_repo_hash,
            'timestamp': datetime.utcnow().isoformat()
        })
        self.total_pdfs += 1
        self._guardar_json()

    def agregar_correo_procesado(self, cuenta_gmail_id: int, message_id: str,
                                  carpeta: str, fecha_correo: datetime,
                                  tiene_adjuntos: bool = False):
        """Registra un correo como procesado."""
        self.correos_procesados.append({
            'cuenta_gmail_id': cuenta_gmail_id,
            'message_id': message_id,
            'carpeta': carpeta,
            'fecha_correo': fecha_correo.isoformat() if fecha_correo else None,
            'tiene_adjuntos': tiene_adjuntos
        })
        self.total_correos += 1

        # Guardar cada 50 correos para no escribir demasiado
        if self.total_correos % 50 == 0:
            self._guardar_json()

    def agregar_dominio(self, dominio: str):
        """Registra un dominio de remitente."""
        if dominio:
            self.dominios.add(dominio)

    def registrar_error(self):
        """Incrementa el contador de errores."""
        self.errores += 1

    def obtener_estadisticas(self) -> Dict:
        """Retorna estadísticas del buffer."""
        return {
            'pdfs': self.total_pdfs,
            'correos': self.total_correos,
            'dominios': len(self.dominios),
            'errores': self.errores
        }

    def consolidar_a_bd(self, db_session, max_retries: int = 5) -> Dict[str, Any]:
        """
        Consolida todos los datos del buffer a la base de datos.
        Incluye retry con backoff exponencial para manejar database locks.

        Args:
            db_session: Sesión SQLAlchemy
            max_retries: Número máximo de reintentos en caso de database lock

        Returns:
            Dict con estadísticas de la consolidación
        """
        from app.models import (ArchivoDescargado, ArchivoRepositorio,
                                CorreoProcesado, DominioRemitente)
        from datetime import datetime as dt

        resultados = {
            'pdfs_insertados': 0,
            'correos_insertados': 0,
            'dominios_insertados': 0,
            'repos_insertados': 0,
            'errores': []
        }

        # Intentar consolidación con retry
        for attempt in range(max_retries + 1):
            try:
                return self._consolidar_interno(db_session, resultados)
            except Exception as e:
                if 'database is locked' in str(e).lower() and attempt < max_retries:
                    delay = 2.0 * (2 ** attempt)  # 2, 4, 8, 16, 32 segundos
                    logger.debug(f"DB locked en consolidación, reintentando en {delay}s (intento {attempt + 1}/{max_retries})")
                    db_session.rollback()
                    time.sleep(delay)
                    continue
                raise

        return resultados

    def _consolidar_interno(self, db_session, resultados: Dict) -> Dict[str, Any]:
        """Lógica interna de consolidación (llamada con retry desde consolidar_a_bd)."""
        from app.models import (ArchivoDescargado, ArchivoRepositorio,
                                CorreoProcesado, DominioRemitente, Compania)
        from datetime import datetime as dt

        try:
            total_repos = len(self.archivos_repositorio)
            total_pdfs = len(self.pdfs)
            total_correos = len(self.correos_procesados)
            logger.debug(f"Consolidación iniciando: {total_repos} repos, {total_pdfs} PDFs, {total_correos} correos")

            # 1. Insertar archivos de repositorio nuevos
            if total_repos > 0:
                logger.debug(f"Consolidación paso 1/4: Insertando {total_repos} archivos de repositorio...")
            for repo_data in self.archivos_repositorio:
                try:
                    hash_valor = repo_data.get('hash_archivo') or repo_data.get('hash_sha256')
                    existente = ArchivoRepositorio.buscar_por_hash(hash_valor)
                    if not existente:
                        repo = ArchivoRepositorio(
                            hash_sha256=hash_valor,
                            nombre_original=repo_data['nombre_original'],
                            ruta_relativa=repo_data['ruta_relativa'],
                            tamano_bytes=repo_data['tamano_bytes'],
                            cantidad_referencias=1
                        )
                        db_session.add(repo)
                        resultados['repos_insertados'] += 1
                except Exception as e:
                    resultados['errores'].append(f"Repo {hash_valor[:8] if hash_valor else 'N/A'}: {e}")

            # 2. Insertar PDFs descargados
            if total_pdfs > 0:
                logger.debug(f"Consolidación paso 2/4: Insertando {total_pdfs} PDFs...")

            # Pre-cargar/crear cache de compañías para evitar queries repetidas
            companias_cache = {}
            nombres_unicos = set(pdf.get('nombre_compania') for pdf in self.pdfs if pdf.get('nombre_compania') and not pdf.get('compania_id'))
            if nombres_unicos:
                logger.debug(f"Consolidación resolviendo {len(nombres_unicos)} compañías...")
                for nombre in nombres_unicos:
                    compania = db_session.query(Compania).filter(
                        Compania.nombre.ilike(f'%{nombre}%')
                    ).first()
                    if not compania:
                        # Crear la compañía ahora (durante consolidación, no durante escaneo)
                        compania = Compania(
                            nombre=nombre,
                            cantidad_documentos=0,
                            fecha_primer_documento=dt.utcnow()
                        )
                        db_session.add(compania)
                        db_session.flush()  # Obtener ID
                        logger.debug(f"Consolidación: nueva compañía creada: {nombre}")
                    companias_cache[nombre] = compania.id

            primer_id = ArchivoDescargado.generar_siguiente_id()
            try:
                id_base = int(primer_id.replace('PDF-', ''))
            except (ValueError, TypeError, AttributeError):
                id_base = 1

            for idx, pdf_data in enumerate(self.pdfs):
                try:
                    archivo_repo = None
                    if pdf_data.get('archivo_repo_hash'):
                        archivo_repo = ArchivoRepositorio.buscar_por_hash(pdf_data['archivo_repo_hash'])

                    fecha_correo = None
                    if pdf_data.get('fecha_correo'):
                        fecha_correo = dt.fromisoformat(pdf_data['fecha_correo'])

                    # Usar cache de compañías
                    compania_id = pdf_data.get('compania_id')
                    nombre_compania = pdf_data.get('nombre_compania')
                    if not compania_id and nombre_compania:
                        compania_id = companias_cache.get(nombre_compania)

                    id_documento_real = f"PDF-{id_base + idx:04d}"

                    archivo = ArchivoDescargado(
                        id_documento=id_documento_real,
                        escaneo_id=self.escaneo_id,
                        nombre_archivo=pdf_data['nombre_archivo'],
                        ruta_archivo=pdf_data['ruta_archivo'],
                        tamano_bytes=pdf_data['tamano_bytes'],
                        hash_archivo=pdf_data['hash_archivo'],
                        remitente=pdf_data.get('remitente'),
                        asunto=pdf_data.get('asunto'),
                        fecha_correo=fecha_correo,
                        compania_id=compania_id,
                        nombre_compania_original=nombre_compania,
                        cuenta_origen=pdf_data.get('cuenta_origen'),
                        archivo_repo_id=archivo_repo.id if archivo_repo else None
                    )
                    db_session.add(archivo)
                    resultados['pdfs_insertados'] += 1
                except Exception as e:
                    resultados['errores'].append(f"PDF {pdf_data.get('nombre_archivo')}: {e}")

            # NOTA: La extracción de datos del asegurado y matching de clientes
            # se hace en la API de visualización (api_extraer_datos_pdf) para
            # evitar problemas de sesión durante la consolidación masiva.
            # Los campos asegurado_nombre_extraido/documento_extraido se llenan
            # cuando el usuario abre el PDF en el visor.

            # 3. Insertar correos procesados
            if total_correos > 0:
                logger.debug(f"Consolidación paso 3/4: Insertando {total_correos} correos procesados...")
            for correo_data in self.correos_procesados:
                try:
                    fecha_correo = None
                    if correo_data.get('fecha_correo'):
                        fecha_correo = dt.fromisoformat(correo_data['fecha_correo'])

                    correo = CorreoProcesado(
                        cuenta_gmail_id=correo_data['cuenta_gmail_id'],
                        message_id=correo_data['message_id'],
                        carpeta=correo_data['carpeta'],
                        fecha_correo=fecha_correo,
                        tiene_adjuntos=correo_data.get('tiene_adjuntos', False)
                    )
                    db_session.add(correo)
                    resultados['correos_insertados'] += 1
                except Exception as e:
                    if 'UNIQUE constraint' not in str(e):
                        resultados['errores'].append(f"Correo: {e}")

            # 4. Insertar dominios (sin flush intermedio)
            logger.debug("Consolidación paso 4/4: Commit final...")
            for dominio in self.dominios:
                try:
                    if self.usuario_id:
                        DominioRemitente.registrar_dominio(self.usuario_id, dominio)
                        resultados['dominios_insertados'] += 1
                except Exception:
                    pass

            # UN SOLO commit al final (sin flushes intermedios)
            db_session.commit()
            logger.info(f"Consolidación completada: {resultados['pdfs_insertados']} PDFs, {resultados['correos_insertados']} correos")

            # Limpiar archivo JSON después de consolidación exitosa
            self._eliminar_json()

            # Limpiar datos en memoria para evitar duplicados si el buffer se reutiliza
            self.pdfs.clear()
            self.correos_procesados.clear()
            self.archivos_repositorio.clear()
            # No limpiar dominios - son acumulativos y sin riesgo de duplicados

        except Exception as e:
            db_session.rollback()
            resultados['errores'].append(f"Error general: {e}")
            raise

        return resultados

    def _eliminar_json(self):
        """Elimina el archivo JSON del buffer."""
        try:
            if os.path.exists(self.archivo_json):
                os.remove(self.archivo_json)
            temp_file = self.archivo_json + '.tmp'
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass

    def _extraer_y_vincular_cliente(self, archivo, ruta_pdf: str, db_session):
        """
        Extrae datos del asegurado del PDF y busca cliente existente.

        Este método se ejecuta al momento de crear cada ArchivoDescargado,
        permitiendo detectar clientes existentes antes de que el usuario
        procese manualmente el PDF.

        Args:
            archivo: Instancia de ArchivoDescargado (ya agregada a la sesión)
            ruta_pdf: Ruta física del archivo PDF
            db_session: Sesión de SQLAlchemy activa
        """
        from datetime import datetime as dt
        import os

        # Verificar que el archivo existe
        if not os.path.exists(ruta_pdf):
            return

        # Importar extractor y matcher
        try:
            from app.extractor.pdf_parser import ExtractorDatosPoliza
            from app.extractor.cliente_matcher import ClienteMatcher
        except ImportError as e:
            logger.warning(f"No se pudo importar módulos de extracción: {e}")
            return

        # Extraer datos básicos del asegurado
        try:
            extractor = ExtractorDatosPoliza()
            datos = extractor.extraer_datos(ruta_pdf)
        except Exception as e:
            logger.debug(f"Error extrayendo datos de {ruta_pdf}: {e}")
            return

        # Guardar datos del asegurado extraídos
        asegurado_nombre = datos.get('asegurado_nombre')
        asegurado_documento = datos.get('asegurado_documento')

        if asegurado_nombre:
            archivo.asegurado_nombre_extraido = str(asegurado_nombre)[:255]
        if asegurado_documento:
            archivo.asegurado_documento_extraido = str(asegurado_documento)[:50]

        # Si no tenemos datos para hacer matching, terminar aquí
        if not asegurado_nombre and not asegurado_documento:
            return

        # Buscar cliente existente
        if not self.usuario_id:
            logger.debug("No hay usuario_id para hacer matching de cliente")
            return

        try:
            matcher = ClienteMatcher(db_session=db_session)
            cliente, tipo_match, confianza = matcher.buscar_cliente(
                usuario_id=self.usuario_id,
                documento=asegurado_documento,
                nombre=asegurado_nombre
            )

            if cliente:
                archivo.cliente_existente_id = cliente.id
                archivo.cliente_match_tipo = tipo_match
                archivo.cliente_match_confianza = confianza
                archivo.fecha_matching = dt.utcnow()
                logger.debug(
                    f"Cliente existente encontrado para {archivo.nombre_archivo}: "
                    f"{cliente.nombre_completo} (tipo={tipo_match}, conf={confianza:.2f})"
                )
        except Exception as e:
            logger.debug(f"Error buscando cliente existente: {e}")

    def descartar(self):
        """Descarta el buffer sin consolidar (para cancelaciones)."""
        self._eliminar_json()
        self.pdfs.clear()
        self.correos_procesados.clear()
        self.dominios.clear()
        self.archivos_repositorio.clear()


def obtener_buffers_pendientes() -> List[str]:
    """Retorna lista de escaneos con buffers pendientes de consolidar."""
    pendientes = []
    if os.path.exists(BUFFER_DIR):
        for archivo in os.listdir(BUFFER_DIR):
            if archivo.startswith('escaneo_') and archivo.endswith('.json'):
                try:
                    escaneo_id = int(archivo.replace('escaneo_', '').replace('.json', ''))
                    pendientes.append(escaneo_id)
                except ValueError:
                    pass
    return pendientes


def consolidar_pendientes(app):
    """Consolida todos los buffers pendientes al iniciar la app."""
    from app.utils.db_session import thread_session

    pendientes = obtener_buffers_pendientes()
    if not pendientes:
        return

    logger.info(f"Encontrados {len(pendientes)} buffers pendientes")

    # Esperar 2 segundos para que otras operaciones de inicio terminen
    time.sleep(2)

    for escaneo_id in pendientes:
        def _consolidar_escaneo():
            with thread_session(app) as session:
                # Obtener usuario_id del escaneo
                from app.models import Escaneo
                escaneo = session.query(Escaneo).get(escaneo_id)
                if escaneo:
                    buffer = ScanBuffer(escaneo_id, escaneo.usuario_id)
                    resultado = buffer.consolidar_a_bd(session)

                    # Actualizar contador de PDFs en el escaneo
                    pdfs_insertados = resultado['pdfs_insertados']
                    escaneo.pdfs_descargados = (escaneo.pdfs_descargados or 0) + pdfs_insertados
                    session.commit()

                    logger.info(f"Escaneo {escaneo_id} consolidado: {pdfs_insertados} PDFs")
                    return pdfs_insertados
                else:
                    # Escaneo no existe, eliminar buffer
                    buffer = ScanBuffer(escaneo_id)
                    buffer.descartar()
                    return 0

        try:
            _retry_on_db_lock(_consolidar_escaneo, max_retries=5, base_delay=2.0)
        except Exception as e:
            logger.error(f"Error consolidando escaneo {escaneo_id} tras reintentos: {e}")
