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
from datetime import datetime
from threading import Thread, Event
from time import sleep
from flask import current_app


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
        self.total_cuentas = 0
        self.cuenta_index = 0
        self.estado_motor = self.ESTADO_IDLE
        self.correo_actual = 0
        self.total_correos_carpeta = 0

    def registrar(self, mensaje):
        """Registra un mensaje de log."""
        prefijo = ""
        if self.cuenta_actual:
            prefijo = f"[{self.cuenta_actual}] "
        self.logs.append({
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'mensaje': f"{prefijo}{mensaje}"
        })

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
        """Verifica si el correo coincide con alguna palabra clave."""
        if not palabras_clave:
            return True
        texto = f"{asunto} {remitente}".lower()
        return any(pc.lower() in texto for pc in palabras_clave)

    def ejecutar_escaneo_multi(self, cuentas, config, directorio_salida):
        """Ejecuta el escaneo de múltiples cuentas en un hilo separado."""
        thread = Thread(target=self._escanear_multi_con_contexto,
                       args=(cuentas, config, directorio_salida))
        thread.daemon = True
        thread.start()

    def _escanear_multi_con_contexto(self, cuentas, config, directorio_salida):
        """Ejecuta el escaneo multi-cuenta dentro del contexto de la aplicación."""
        with self.app.app_context():
            self._escanear_multi(cuentas, config, directorio_salida)

    def _escanear_multi(self, cuentas, config, directorio_salida):
        """Realiza el escaneo de múltiples cuentas de Gmail secuencialmente."""
        from app import db
        from app.models import Escaneo

        escaneo = Escaneo.query.get(self.escaneo_id)
        if not escaneo:
            return

        self.estado_motor = self.ESTADO_EJECUTANDO
        self.total_cuentas = len(cuentas)
        total_correos = 0
        total_pdfs = 0

        try:
            self.registrar(f"Iniciando escaneo de {self.total_cuentas} cuenta(s)")

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

                self.registrar(f"Procesando cuenta {self.cuenta_index}/{self.total_cuentas}")

                try:
                    correos, pdfs = self._escanear_cuenta(cuenta, config, directorio_salida, escaneo)
                    total_correos += correos
                    total_pdfs += pdfs
                except Exception as e:
                    error_msg = f"Error en cuenta {cuenta.correo_gmail}: {str(e)}"
                    self.registrar(f"ERROR: {error_msg}")
                    # Continuar con siguiente cuenta si hay más
                    if index < len(cuentas) - 1:
                        self.registrar("Continuando con siguiente cuenta...")
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

            self.registrar(f"Escaneo finalizado: {total_correos} correos, {total_pdfs} PDFs")

        except Exception as e:
            # Capturar cualquier excepción y marcar como error
            error_msg = f"Error fatal: {str(e)}"
            self.registrar(f"ERROR CRÍTICO: {error_msg}")
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

    def _escanear_cuenta(self, cuenta, config, directorio_salida, escaneo):
        """Escanea una cuenta individual de Gmail."""
        from app import db
        from app.models import ArchivoDescargado, Compania, CorreoProcesado, HistorialEscaneoCarpeta

        carpetas = config.get('carpetas', ['INBOX'])
        palabras_clave = config.get('palabras_clave', [])
        fecha_desde = config.get('fecha_desde')
        fecha_hasta = config.get('fecha_hasta')

        # Opcion para forzar re-escaneo completo (ignorar memoria)
        forzar_escaneo = config.get('forzar_escaneo', False)

        pdfs_encontrados = 0
        correos_escaneados = 0

        try:
            correo = cuenta.correo_gmail
            contrasena = cuenta.obtener_contrasena_app()

            mail = imaplib.IMAP4_SSL(self.SERVIDOR_IMAP, self.PUERTO_IMAP)
            mail.login(correo, contrasena)
            self.registrar(f"Conectado")

            # Actualizar último escaneo de la cuenta
            cuenta.ultimo_escaneo = datetime.utcnow()
            db.session.commit()

            for carpeta in carpetas:
                if self.detener_solicitado:
                    break

                try:
                    resultado, _ = mail.select(f'"{carpeta}"')
                    if resultado != 'OK':
                        self.registrar(f"No se pudo seleccionar: {carpeta}")
                        continue

                    self.registrar(f"Escaneando: {carpeta}")

                    # Construir criterios de búsqueda
                    criterios = []

                    # Si no se fuerza escaneo, usar la última fecha escaneada
                    fecha_busqueda = fecha_desde
                    if not forzar_escaneo and not fecha_desde:
                        ultima_fecha = HistorialEscaneoCarpeta.obtener_ultima_fecha(cuenta.id, carpeta)
                        if ultima_fecha:
                            fecha_busqueda = ultima_fecha.date()
                            self.registrar(f"Buscando solo correos desde: {fecha_busqueda.strftime('%d/%m/%Y')}")

                    if fecha_busqueda:
                        criterios.append(f'SINCE {fecha_busqueda.strftime("%d-%b-%Y")}')
                    if fecha_hasta:
                        criterios.append(f'BEFORE {fecha_hasta.strftime("%d-%b-%Y")}')

                    cadena_busqueda = ' '.join(criterios) if criterios else 'ALL'

                    resultado, mensajes = mail.search(None, cadena_busqueda)
                    if resultado != 'OK':
                        continue

                    ids_mensajes = mensajes[0].split()
                    total_en_carpeta = len(ids_mensajes)
                    self.total_correos_carpeta = total_en_carpeta
                    self.registrar(f"Encontrados {total_en_carpeta} correos en carpeta")

                    # Contadores para esta carpeta
                    correos_nuevos = 0
                    correos_saltados = 0
                    correos_con_pdf_carpeta = 0
                    pdfs_carpeta = 0
                    fecha_mas_reciente = None

                    for idx, id_msg in enumerate(ids_mensajes, 1):
                        # Verificar pausa
                        if not self.esperar_si_pausado():
                            break

                        if self.detener_solicitado:
                            break

                        correos_escaneados += 1
                        self.correo_actual = idx  # Posición dentro de la carpeta actual

                        # Actualizar progreso periódicamente (cada 10 correos)
                        if correos_escaneados % 10 == 0:
                            escaneo.correos_escaneados = correos_escaneados  # CORREGIDO: asignar, no sumar
                            escaneo.pdfs_descargados = pdfs_encontrados      # CORREGIDO: asignar, no sumar
                            db.session.commit()

                        resultado, datos_msg = mail.fetch(id_msg, '(RFC822)')
                        if resultado != 'OK':
                            continue

                        correo_crudo = datos_msg[0][1]
                        msg = email.message_from_bytes(correo_crudo)

                        # Obtener Message-ID para verificar si ya fue procesado
                        message_id = msg.get('Message-ID', '') or msg.get('Message-Id', '')
                        if not message_id:
                            # Generar un ID basado en otros campos si no hay Message-ID
                            message_id = hashlib.md5(correo_crudo[:1000]).hexdigest()

                        # Verificar si este correo ya fue procesado
                        if not forzar_escaneo and CorreoProcesado.ya_procesado(cuenta.id, message_id, carpeta):
                            correos_saltados += 1
                            continue

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

                        correos_nuevos += 1

                        # Verificar filtro
                        if not self.coincide_palabras_clave(asunto, remitente, palabras_clave):
                            # Registrar como procesado aunque no coincida con filtro
                            CorreoProcesado.registrar_procesado(
                                cuenta.id, message_id, carpeta, fecha_correo,
                                remitente[:255], asunto[:500], False, 0
                            )
                            continue

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

                                # Guardar archivo
                                with open(ruta_salida, 'wb') as f:
                                    f.write(contenido)

                                # Registrar en base de datos con compañía
                                archivo = ArchivoDescargado(
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

                                pdfs_encontrados += 1
                                pdfs_carpeta += 1
                                nombre_cia = compania.nombre if compania else 'Desconocida'
                                self.registrar(f"Descargado: {nuevo_nombre} [{nombre_cia}]")

                        # Registrar correo como procesado
                        tiene_pdfs = pdfs_carpeta > 0
                        if tiene_pdfs:
                            correos_con_pdf_carpeta += 1
                        CorreoProcesado.registrar_procesado(
                            cuenta.id, message_id, carpeta, fecha_correo,
                            remitente[:255] if remitente else None,
                            asunto[:500] if asunto else None,
                            tiene_pdfs, pdfs_carpeta
                        )

                    # Actualizar historial de la carpeta al terminar
                    if correos_nuevos > 0 or correos_saltados > 0:
                        HistorialEscaneoCarpeta.actualizar_historial(
                            cuenta.id, carpeta, fecha_mas_reciente,
                            correos_nuevos, correos_con_pdf_carpeta, pdfs_carpeta
                        )
                        db.session.commit()

                    if correos_saltados > 0:
                        self.registrar(f"Saltados {correos_saltados} correos ya procesados")

                except Exception as e:
                    self.registrar(f"Error en {carpeta}: {e}")

            mail.logout()
            self.registrar(f"Cuenta completada: {correos_escaneados} correos, {pdfs_encontrados} PDFs")

        except Exception as e:
            self.registrar(f"Error: {e}")

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
            'total_correos_carpeta': self.total_correos_carpeta
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
