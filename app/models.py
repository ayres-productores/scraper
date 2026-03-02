"""
Modelos de base de datos
"""

from datetime import datetime
from flask_login import UserMixin
from app import db, bcrypt, login_manager
from cryptography.fernet import Fernet
from flask import current_app
import base64
import hashlib


def obtener_cipher():
    """
    Obtiene el cipher para encriptar/desencriptar credenciales.

    DEPRECADO: Este método usa SHA-256 sin salt (vulnerable).
    Usar app.utils.encryption para nuevas credenciales.
    Mantenido para compatibilidad con credenciales legacy.
    """
    key = current_app.config['ENCRYPTION_KEY']
    # Convertir a 32 bytes usando hash (método legacy)
    key_bytes = hashlib.sha256(key.encode()).digest()
    key_b64 = base64.urlsafe_b64encode(key_bytes)
    return Fernet(key_b64)


@login_manager.user_loader
def cargar_usuario(user_id):
    """Carga usuario por ID para Flask-Login."""
    return Usuario.query.get(int(user_id))


class Usuario(UserMixin, db.Model):
    """Modelo de usuario del sistema."""

    __tablename__ = 'usuarios'

    # Constantes de roles
    ROL_ADMIN = 'admin'
    ROL_POWERUSER = 'poweruser'
    ROL_COLLABORATOR = 'collaborator'

    ROLES = [
        (ROL_ADMIN, 'Administrador'),
        (ROL_POWERUSER, 'PowerUser'),
        (ROL_COLLABORATOR, 'Collaborator')
    ]

    id = db.Column(db.Integer, primary_key=True)
    correo = db.Column(db.String(120), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    contrasena_hash = db.Column(db.String(128), nullable=False)
    rol = db.Column(db.String(20), default='poweruser')  # 'admin', 'poweruser' o 'collaborator'
    activo = db.Column(db.Boolean, default=True)
    debe_cambiar_contrasena = db.Column(db.Boolean, default=True)
    intentos_fallidos = db.Column(db.Integer, default=0)
    bloqueado_hasta = db.Column(db.DateTime, nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_acceso = db.Column(db.DateTime, nullable=True)

    # Relaciones
    cuentas_gmail = db.relationship('CuentaGmail', backref='propietario', lazy='dynamic',
                                     cascade='all, delete-orphan')
    escaneos = db.relationship('Escaneo', backref='usuario', lazy='dynamic',
                                cascade='all, delete-orphan')
    logs = db.relationship('LogActividad', backref='usuario', lazy='dynamic',
                           cascade='all, delete-orphan')
    clientes = db.relationship('Cliente', backref='broker', lazy='dynamic',
                               cascade='all, delete-orphan')

    def establecer_contrasena(self, contrasena):
        """Hashea y guarda la contraseña."""
        self.contrasena_hash = bcrypt.generate_password_hash(contrasena).decode('utf-8')

    def verificar_contrasena(self, contrasena):
        """Verifica la contraseña contra el hash."""
        return bcrypt.check_password_hash(self.contrasena_hash, contrasena)

    def es_admin(self):
        """Verifica si el usuario es administrador."""
        return self.rol == self.ROL_ADMIN

    def es_poweruser(self):
        """Verifica si el usuario es PowerUser (incluye rol legacy 'usuario')."""
        return self.rol in (self.ROL_POWERUSER, 'usuario')

    def es_collaborator(self):
        """Verifica si el usuario es Collaborator."""
        return self.rol == self.ROL_COLLABORATOR

    def puede_gestionar_usuarios(self):
        """Verifica si puede acceder al ABM de usuarios."""
        return self.rol in (self.ROL_ADMIN, self.ROL_POWERUSER, 'usuario')

    def puede_gestionar_usuario(self, otro_usuario):
        """
        Verifica si puede crear/editar/eliminar a otro usuario.
        - Admin: puede gestionar a todos
        - PowerUser: solo puede gestionar Collaborators
        - Collaborator: no puede gestionar a nadie (solo su perfil)
        """
        if self.rol == self.ROL_ADMIN:
            return True
        if self.rol in (self.ROL_POWERUSER, 'usuario'):
            return otro_usuario.rol == self.ROL_COLLABORATOR
        return False

    def roles_que_puede_crear(self):
        """Retorna lista de roles que este usuario puede crear."""
        if self.rol == self.ROL_ADMIN:
            return [self.ROL_POWERUSER, self.ROL_COLLABORATOR]
        if self.rol in (self.ROL_POWERUSER, 'usuario'):
            return [self.ROL_COLLABORATOR]
        return []

    def obtener_nombre_rol(self):
        """Retorna el nombre legible del rol."""
        roles_dict = dict(self.ROLES)
        # Manejar rol legacy
        if self.rol == 'usuario':
            return 'PowerUser'
        return roles_dict.get(self.rol, self.rol)

    def esta_bloqueado(self):
        """Verifica si la cuenta está bloqueada temporalmente."""
        if self.bloqueado_hasta:
            if datetime.utcnow() < self.bloqueado_hasta:
                return True
            else:
                # Desbloquear automáticamente
                self.bloqueado_hasta = None
                self.intentos_fallidos = 0
                db.session.commit()
        return False

    def registrar_intento_fallido(self):
        """Registra un intento de login fallido."""
        from datetime import timedelta
        self.intentos_fallidos += 1
        if self.intentos_fallidos >= current_app.config['INTENTOS_LOGIN_MAX']:
            self.bloqueado_hasta = datetime.utcnow() + timedelta(
                minutes=current_app.config['BLOQUEO_MINUTOS']
            )
        db.session.commit()

    def resetear_intentos(self):
        """Resetea el contador de intentos fallidos."""
        self.intentos_fallidos = 0
        self.bloqueado_hasta = None
        self.ultimo_acceso = datetime.utcnow()
        db.session.commit()

    def __repr__(self):
        return f'<Usuario {self.correo}>'


class CuentaGmail(db.Model):
    """Modelo para cuentas de Gmail de los usuarios."""

    __tablename__ = 'cuentas_gmail'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    correo_gmail = db.Column(db.String(120), nullable=False)
    contrasena_app_encriptada = db.Column(db.Text, nullable=False)
    # Salt para derivación de clave (NULL = formato legacy sin salt)
    encryption_salt = db.Column(db.String(64), nullable=True)
    activa = db.Column(db.Boolean, default=True)
    fecha_agregada = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_escaneo = db.Column(db.DateTime, nullable=True)

    # Relación con escaneos
    escaneos = db.relationship('Escaneo', backref='cuenta_gmail', lazy='dynamic')

    def establecer_contrasena_app(self, contrasena):
        """
        Encripta y guarda la contraseña de aplicación.

        Usa el nuevo sistema de encriptación con salt único por cuenta.
        """
        from app.utils.encryption import encrypt_credential
        encrypted, salt = encrypt_credential(contrasena)
        self.contrasena_app_encriptada = encrypted
        self.encryption_salt = salt

    def obtener_contrasena_app(self):
        """
        Desencripta y devuelve la contraseña de aplicación.

        Soporta tanto formato nuevo (con salt) como legacy (sin salt)
        para compatibilidad con cuentas existentes.
        """
        from app.utils.encryption import decrypt_credential
        return decrypt_credential(
            self.contrasena_app_encriptada,
            salt=self.encryption_salt  # None para cuentas legacy
        )

    def usar_encriptacion_moderna(self):
        """Verifica si esta cuenta usa encriptación con salt."""
        return self.encryption_salt is not None

    def migrar_encriptacion(self):
        """
        Migra esta cuenta al nuevo sistema de encriptación con salt.

        Uso:
            cuenta.migrar_encriptacion()
            db.session.commit()

        Returns:
            bool: True si se migró, False si ya usaba el nuevo sistema
        """
        if self.usar_encriptacion_moderna():
            return False

        from app.utils.encryption import migrate_credential
        new_encrypted, new_salt = migrate_credential(self.contrasena_app_encriptada)
        self.contrasena_app_encriptada = new_encrypted
        self.encryption_salt = new_salt
        return True

    def __repr__(self):
        return f'<CuentaGmail {self.correo_gmail}>'


class Escaneo(db.Model):
    """Modelo para registrar escaneos realizados."""

    __tablename__ = 'escaneos'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    cuenta_gmail_id = db.Column(db.Integer, db.ForeignKey('cuentas_gmail.id'), nullable=True, index=True)
    fecha_inicio = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_fin = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(20), default='en_progreso', index=True)  # en_progreso, completado, error, cancelado
    correos_escaneados = db.Column(db.Integer, default=0)
    pdfs_descargados = db.Column(db.Integer, default=0)
    palabras_clave = db.Column(db.Text, nullable=True)  # DEPRECADO - usar dominios_filtro
    dominios_filtro = db.Column(db.Text, nullable=True)  # Dominios separados por coma, vacío = todos
    carpetas = db.Column(db.Text, nullable=True)
    fecha_desde = db.Column(db.Date, nullable=True)
    fecha_hasta = db.Column(db.Date, nullable=True)
    mensaje_error = db.Column(db.Text, nullable=True)

    # Campos para escaneo multi-cuenta
    es_multi_cuenta = db.Column(db.Boolean, default=False)
    cuentas_escaneadas = db.Column(db.Text, nullable=True)  # IDs separados por coma
    cuenta_actual = db.Column(db.String(120), nullable=True)  # Cuenta siendo procesada

    # Relación con archivos descargados
    archivos = db.relationship('ArchivoDescargado', backref='escaneo', lazy='dynamic',
                                cascade='all, delete-orphan')

    def obtener_lista_cuentas(self):
        """Devuelve lista de IDs de cuentas escaneadas."""
        if self.cuentas_escaneadas:
            return [int(x) for x in self.cuentas_escaneadas.split(',') if x]
        return []

    def __repr__(self):
        return f'<Escaneo {self.id} - {self.estado}>'


class LogEscaneo(db.Model):
    """Modelo para logs detallados y persistentes de cada escaneo."""

    __tablename__ = 'logs_escaneo'

    id = db.Column(db.Integer, primary_key=True)
    escaneo_id = db.Column(db.Integer, db.ForeignKey('escaneos.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Clasificación del log
    nivel = db.Column(db.String(10), default='info')  # info, success, warning, error
    categoria = db.Column(db.String(30), default='sistema')  # conexion, carpeta, correo, pdf, sistema, memoria

    # Información del evento
    mensaje = db.Column(db.String(500), nullable=False)
    cuenta_gmail = db.Column(db.String(120), nullable=True)
    carpeta = db.Column(db.String(100), nullable=True)
    correo_message_id = db.Column(db.String(200), nullable=True)
    archivo_nombre = db.Column(db.String(255), nullable=True)

    # Datos adicionales (JSON para flexibilidad)
    datos_extra = db.Column(db.Text, nullable=True)  # JSON con info adicional

    # Relación
    escaneo = db.relationship('Escaneo', backref=db.backref('logs', lazy='dynamic', cascade='all, delete-orphan'))

    @staticmethod
    def registrar(escaneo_id, mensaje, nivel='info', categoria='sistema',
                  cuenta_gmail=None, carpeta=None, correo_message_id=None,
                  archivo_nombre=None, datos_extra=None):
        """Registra un log en la base de datos."""
        import json
        log = LogEscaneo(
            escaneo_id=escaneo_id,
            mensaje=mensaje[:500] if mensaje else '',
            nivel=nivel,
            categoria=categoria,
            cuenta_gmail=cuenta_gmail,
            carpeta=carpeta,
            correo_message_id=correo_message_id,
            archivo_nombre=archivo_nombre,
            datos_extra=json.dumps(datos_extra) if datos_extra else None
        )
        db.session.add(log)
        # No commit aquí, se hace en batch para mejor rendimiento
        return log

    @staticmethod
    def obtener_resumen(escaneo_id):
        """Obtiene resumen estadístico de logs de un escaneo."""
        from sqlalchemy import func

        stats = db.session.query(
            LogEscaneo.nivel,
            func.count(LogEscaneo.id)
        ).filter_by(escaneo_id=escaneo_id).group_by(LogEscaneo.nivel).all()

        resumen = {'total': 0, 'info': 0, 'success': 0, 'warning': 0, 'error': 0}
        for nivel, cantidad in stats:
            resumen[nivel] = cantidad
            resumen['total'] += cantidad

        return resumen

    @staticmethod
    def obtener_errores(escaneo_id, limite=50):
        """Obtiene los errores de un escaneo."""
        return LogEscaneo.query.filter_by(
            escaneo_id=escaneo_id,
            nivel='error'
        ).order_by(LogEscaneo.timestamp.desc()).limit(limite).all()

    def __repr__(self):
        return f'<LogEscaneo [{self.nivel}] {self.mensaje[:30]}>'


class DominioRemitente(db.Model):
    """Modelo para dominios o direcciones de email de donde se han descargado PDFs."""

    __tablename__ = 'dominios_remitentes'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    dominio = db.Column(db.String(150), nullable=False, index=True)  # Puede ser dominio o email completo
    nombre_mostrar = db.Column(db.String(100), nullable=True)  # Nombre amigable
    es_email_completo = db.Column(db.Boolean, default=False)  # True si es dirección específica
    cantidad_pdfs = db.Column(db.Integer, default=0)
    ultimo_pdf = db.Column(db.DateTime, nullable=True)
    activo = db.Column(db.Boolean, default=True)  # Para habilitar/deshabilitar en búsquedas
    fecha_detectado = db.Column(db.DateTime, default=datetime.utcnow)

    # Relación con usuario
    usuario = db.relationship('Usuario', backref=db.backref('dominios_remitentes', lazy='dynamic'))

    # Índice único por usuario y dominio
    __table_args__ = (
        db.UniqueConstraint('usuario_id', 'dominio', name='unique_usuario_dominio'),
    )

    @staticmethod
    def registrar_dominio(usuario_id, remitente):
        """Registra o actualiza un dominio cuando se descarga un PDF."""
        import re

        if not remitente:
            return None

        # Extraer dominio del email
        match = re.search(r'@([a-zA-Z0-9.-]+)', remitente)
        if not match:
            return None

        dominio = match.group(1).lower()

        # Ignorar dominios genéricos de correo personal
        dominios_ignorar = {'gmail.com', 'hotmail.com', 'outlook.com', 'yahoo.com',
                           'yahoo.com.ar', 'hotmail.com.ar', 'live.com', 'live.com.ar'}
        if dominio in dominios_ignorar:
            return None

        # Buscar dominio existente
        dom = DominioRemitente.query.filter_by(
            usuario_id=usuario_id,
            dominio=dominio
        ).first()

        if dom:
            # Actualizar contador
            dom.cantidad_pdfs += 1
            dom.ultimo_pdf = datetime.utcnow()
        else:
            # Crear nuevo
            nombre = Compania.extraer_nombre_de_dominio(dominio)
            dom = DominioRemitente(
                usuario_id=usuario_id,
                dominio=dominio,
                nombre_mostrar=nombre,
                cantidad_pdfs=1,
                ultimo_pdf=datetime.utcnow()
            )
            db.session.add(dom)

        return dom

    @staticmethod
    def registrar_email_especifico(usuario_id, email, nombre_mostrar=None):
        """Registra una dirección de email específica como fuente de pólizas."""
        email = email.lower().strip()

        # Verificar si ya existe
        existente = DominioRemitente.query.filter_by(
            usuario_id=usuario_id,
            dominio=email
        ).first()

        if existente:
            return existente

        # Crear nuevo
        nuevo = DominioRemitente(
            usuario_id=usuario_id,
            dominio=email,
            nombre_mostrar=nombre_mostrar or email.split('@')[0].replace('.', ' ').title(),
            es_email_completo=True,
            cantidad_pdfs=0,
            activo=True
        )
        db.session.add(nuevo)
        db.session.commit()
        return nuevo

    @staticmethod
    def obtener_dominios_usuario(usuario_id, solo_activos=True):
        """Obtiene lista de dominios del usuario ordenados por cantidad de PDFs."""
        query = DominioRemitente.query.filter_by(usuario_id=usuario_id)
        if solo_activos:
            query = query.filter_by(activo=True)
        return query.order_by(DominioRemitente.cantidad_pdfs.desc()).all()

    def coincide_con_remitente(self, remitente):
        """Verifica si este filtro coincide con un remitente dado."""
        if not remitente:
            return False

        remitente_lower = remitente.lower()

        if self.es_email_completo:
            # Coincidencia exacta de email
            return self.dominio in remitente_lower
        else:
            # Coincidencia de dominio
            return f'@{self.dominio}' in remitente_lower

    def __repr__(self):
        tipo = 'Email' if self.es_email_completo else 'Dominio'
        return f'<DominioRemitente {tipo}: {self.dominio} ({self.cantidad_pdfs} PDFs)>'


class Compania(db.Model):
    """Modelo para compañías aseguradoras detectadas."""

    __tablename__ = 'companias'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, index=True)
    dominio_email = db.Column(db.String(100), nullable=True, unique=True)
    cantidad_documentos = db.Column(db.Integer, default=0)
    fecha_primer_documento = db.Column(db.DateTime, nullable=True)
    fecha_ultimo_documento = db.Column(db.DateTime, nullable=True)

    # Relación con archivos
    archivos = db.relationship('ArchivoDescargado', backref='compania', lazy='dynamic')

    @staticmethod
    def extraer_nombre_de_dominio(dominio):
        """Extrae un nombre legible de un dominio de email."""
        import re

        if not dominio:
            return "Desconocido"

        dominio = dominio.lower()

        # Diccionario de dominios conocidos con nombres personalizados
        dominios_conocidos = {
            'gmail.com': 'Gmail',
            'hotmail.com': 'Hotmail',
            'outlook.com': 'Outlook',
            'yahoo.com': 'Yahoo',
            'yahoo.com.ar': 'Yahoo AR',
            'hotmail.com.ar': 'Hotmail AR',
            'starlink.com': 'Starlink',
        }

        if dominio in dominios_conocidos:
            return dominios_conocidos[dominio]

        # Quitar extensiones de país y TLDs comunes
        # Primero quitar .com.ar, .gob.ar, etc (extensiones compuestas)
        dominio_limpio = re.sub(r'\.(com|gob|org|net|edu)\.(ar|mx|es|br|cl|co|uy|py)$', '', dominio)
        # Luego quitar extensiones simples
        dominio_limpio = re.sub(r'\.(com|net|org|edu|gob|ar|es|mx|br)$', '', dominio_limpio)

        # Dividir por puntos y tomar la parte principal
        partes = dominio_limpio.split('.')

        # Tomar la primera parte significativa (antes de subdominios como mail, www)
        nombre = partes[0]
        if nombre in ('mail', 'www', 'smtp', 'correo', 'email') and len(partes) > 1:
            nombre = partes[1]

        # Capitalizar correctamente
        # Si tiene "seguros" al final, separar
        if 'seguros' in nombre.lower():
            nombre = nombre.lower().replace('seguros', ' Seguros')

        return nombre.strip().title()

    @staticmethod
    def detectar_o_crear(remitente):
        """Detecta la compañía del remitente o crea una nueva."""
        import re

        if not remitente:
            return None

        # Extraer dominio del email
        match = re.search(r'@([a-zA-Z0-9.-]+)', remitente)
        if not match:
            return None

        dominio = match.group(1).lower()

        # Buscar compañía existente por dominio
        compania = Compania.query.filter_by(dominio_email=dominio).first()

        if not compania:
            # Crear nueva compañía con nombre extraído correctamente
            nombre = Compania.extraer_nombre_de_dominio(dominio)

            compania = Compania(
                nombre=nombre,
                dominio_email=dominio,
                cantidad_documentos=0,
                fecha_primer_documento=datetime.utcnow()
            )
            db.session.add(compania)
            db.session.flush()

        return compania

    def incrementar_contador(self):
        """Incrementa el contador de documentos."""
        self.cantidad_documentos += 1
        self.fecha_ultimo_documento = datetime.utcnow()

    @staticmethod
    def detectar_solo(remitente):
        """Detecta compañía por dominio del remitente SIN crear nueva.

        Para usar durante escaneos donde no queremos escribir a la BD.
        """
        if not remitente:
            return None

        match = re.search(r'@([a-zA-Z0-9.-]+)', remitente)
        if not match:
            return None

        dominio = match.group(1).lower()
        return Compania.query.filter_by(dominio_email=dominio).first()

    def __repr__(self):
        return f'<Compania {self.nombre}>'


class ArchivoRepositorio(db.Model):
    """Repositorio central de archivos únicos (deduplicación por hash)."""

    __tablename__ = 'archivos_repositorio'

    id = db.Column(db.Integer, primary_key=True)
    hash_sha256 = db.Column(db.String(64), unique=True, nullable=False, index=True)
    ruta_relativa = db.Column(db.String(300), nullable=False)  # ej: "ab/cd1234.../archivo.pdf"
    nombre_original = db.Column(db.String(255), nullable=False)
    tamano_bytes = db.Column(db.Integer, nullable=False)
    fecha_primera_descarga = db.Column(db.DateTime, default=datetime.utcnow)
    cantidad_referencias = db.Column(db.Integer, default=1)

    # Relación con ArchivoDescargado
    referencias = db.relationship('ArchivoDescargado', backref='archivo_repo', lazy='dynamic')

    def obtener_ruta_fisica(self):
        """Obtiene la ruta completa del archivo en disco."""
        from flask import current_app
        import os
        return os.path.join(
            current_app.config['REPOSITORIO_ARCHIVOS'],
            self.ruta_relativa
        )

    def incrementar_referencias(self):
        """Incrementa el contador de referencias."""
        self.cantidad_referencias += 1

    def decrementar_referencias(self):
        """Decrementa el contador de referencias."""
        if self.cantidad_referencias > 0:
            self.cantidad_referencias -= 1

    @staticmethod
    def buscar_por_hash(hash_sha256):
        """Busca un archivo en el repositorio por su hash."""
        return ArchivoRepositorio.query.filter_by(hash_sha256=hash_sha256).first()

    @staticmethod
    def guardar_o_reusar(contenido: bytes, nombre_sugerido: str):
        """Guarda archivo en repositorio o reutiliza si existe."""
        import hashlib
        import os
        from flask import current_app

        hash_sha256 = hashlib.sha256(contenido).hexdigest()

        # Buscar existente
        existente = ArchivoRepositorio.buscar_por_hash(hash_sha256)
        if existente:
            existente.incrementar_referencias()
            return existente, True  # (repo, reutilizado)

        # Crear nuevo
        subcarpeta = hash_sha256[:2]
        ruta_relativa = f"{subcarpeta}/{hash_sha256}/{nombre_sugerido}"
        ruta_completa = os.path.join(
            current_app.config['REPOSITORIO_ARCHIVOS'],
            ruta_relativa
        )

        # Crear directorios si no existen
        os.makedirs(os.path.dirname(ruta_completa), exist_ok=True)

        # Escribir archivo
        with open(ruta_completa, 'wb') as f:
            f.write(contenido)

        nuevo = ArchivoRepositorio(
            hash_sha256=hash_sha256,
            ruta_relativa=ruta_relativa,
            nombre_original=nombre_sugerido,
            tamano_bytes=len(contenido)
        )
        db.session.add(nuevo)
        db.session.flush()
        return nuevo, False  # (repo, reutilizado)

    def __repr__(self):
        return f'<ArchivoRepositorio {self.hash_sha256[:8]}... refs={self.cantidad_referencias}>'


class ArchivoDescargado(db.Model):
    """Modelo para registrar archivos PDF descargados."""

    __tablename__ = 'archivos_descargados'

    id = db.Column(db.Integer, primary_key=True)
    id_documento = db.Column(db.String(10), nullable=True, unique=True, index=True)  # ID visible: PDF-0001
    escaneo_id = db.Column(db.Integer, db.ForeignKey('escaneos.id'), nullable=False, index=True)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    ruta_archivo = db.Column(db.String(500), nullable=False)
    tamano_bytes = db.Column(db.Integer, nullable=True)
    hash_archivo = db.Column(db.String(64), nullable=True, index=True)  # SHA-256
    remitente = db.Column(db.String(255), nullable=True)
    asunto = db.Column(db.String(500), nullable=True)
    fecha_correo = db.Column(db.DateTime, nullable=True)
    fecha_descarga = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Campos para organización por compañía
    compania_id = db.Column(db.Integer, db.ForeignKey('companias.id'), nullable=True, index=True)
    nombre_compania_original = db.Column(db.String(255), nullable=True)
    cuenta_origen = db.Column(db.String(120), nullable=True)  # Email de la cuenta Gmail origen

    # ========== ESTADO DE CONFIRMACIÓN ==========
    estado_confirmacion = db.Column(db.String(20), default='pendiente')  # pendiente, definitivo
    fecha_confirmacion = db.Column(db.DateTime, nullable=True)
    confirmado_por = db.Column(db.String(50), nullable=True)  # 'whatsapp_read', 'manual'

    # ========== CORRECCIÓN DE COMPAÑÍA ==========
    correccion_compania = db.Column(db.Boolean, default=False)  # True si se corrigió la compañía
    fecha_correccion = db.Column(db.DateTime, nullable=True)
    compania_id_original = db.Column(db.Integer, nullable=True)  # Compañía antes de corregir

    # ========== REPOSITORIO CENTRAL ==========
    archivo_repo_id = db.Column(db.Integer, db.ForeignKey('archivos_repositorio.id'), nullable=True, index=True)

    # ========== DATOS ASEGURADO EXTRAÍDOS (al momento del escaneo) ==========
    asegurado_nombre_extraido = db.Column(db.String(255), nullable=True)
    asegurado_documento_extraido = db.Column(db.String(50), nullable=True, index=True)

    # ========== CLIENTE EXISTENTE DETECTADO ==========
    cliente_existente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True, index=True)
    cliente_match_tipo = db.Column(db.String(20), nullable=True)  # 'documento', 'nombre_fuzzy', None
    cliente_match_confianza = db.Column(db.Float, nullable=True)  # 0.0 - 1.0
    fecha_matching = db.Column(db.DateTime, nullable=True)

    # Relación con cliente existente
    cliente_existente = db.relationship('Cliente', foreign_keys=[cliente_existente_id],
                                        backref=db.backref('archivos_vinculados', lazy='dynamic'))

    def obtener_ruta_fisica(self):
        """Obtiene la ruta física del archivo (repositorio o legacy)."""
        if self.archivo_repo:
            return self.archivo_repo.obtener_ruta_fisica()
        # Fallback para archivos antiguos
        return self.ruta_archivo

    @staticmethod
    def generar_siguiente_id():
        """Genera el siguiente ID de documento disponible."""
        from sqlalchemy import func
        ultimo = db.session.query(func.max(ArchivoDescargado.id)).scalar() or 0
        # Buscar el número más alto en id_documento existente
        ultimo_doc = db.session.query(ArchivoDescargado.id_documento).filter(
            ArchivoDescargado.id_documento.isnot(None)
        ).order_by(ArchivoDescargado.id_documento.desc()).first()

        if ultimo_doc and ultimo_doc[0]:
            try:
                num = int(ultimo_doc[0].replace('PDF-', ''))
                return f"PDF-{num + 1:04d}"
            except (ValueError, TypeError, AttributeError):
                pass  # Formato de ID inesperado, usar secuencial
        return f"PDF-{ultimo + 1:04d}"

    def __repr__(self):
        return f'<ArchivoDescargado {self.id_documento or self.id}: {self.nombre_archivo}>'


class LogActividad(db.Model):
    """Modelo para registrar actividad del sistema (auditoría)."""

    __tablename__ = 'logs_actividad'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True, index=True)
    accion = db.Column(db.String(100), nullable=False, index=True)
    detalle = db.Column(db.Text, nullable=True)
    direccion_ip = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    @staticmethod
    def registrar(usuario_id, accion, detalle=None, request=None):
        """Registra una actividad en el log."""
        log = LogActividad(
            usuario_id=usuario_id,
            accion=accion,
            detalle=detalle,
            direccion_ip=request.remote_addr if request else None,
            user_agent=request.user_agent.string[:255] if request and request.user_agent else None
        )
        db.session.add(log)
        db.session.commit()
        return log

    def __repr__(self):
        return f'<LogActividad {self.accion} - {self.fecha}>'


# ============================================================================
# MODELOS DE DISTRIBUCIÓN DE PÓLIZAS
# ============================================================================

class Cliente(db.Model):
    """Modelo para clientes del broker."""

    __tablename__ = 'clientes'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False, index=True)
    apellido = db.Column(db.String(100), nullable=True, index=True)
    telefono_whatsapp = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    documento_identidad = db.Column(db.String(30), nullable=True, index=True)
    notas = db.Column(db.Text, nullable=True)
    mensaje_personalizado = db.Column(db.Text, nullable=True)
    usar_mensaje_estandar = db.Column(db.Boolean, default=True)
    activo = db.Column(db.Boolean, default=True, index=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_envio = db.Column(db.DateTime, nullable=True)

    # Estado de cliente actual (para seguimiento CRM)
    es_cliente_actual = db.Column(db.Boolean, default=True, index=True)
    fecha_evaluacion_actual = db.Column(db.DateTime, nullable=True)
    motivo_no_actual = db.Column(db.String(100), nullable=True)  # sin_comunicacion, sin_poliza_reciente, ambos

    # Relaciones
    polizas = db.relationship('PolizaCliente', backref='cliente', lazy='dynamic',
                              cascade='all, delete-orphan')
    envios = db.relationship('EnvioWhatsApp', backref='cliente', lazy='dynamic',
                             cascade='all, delete-orphan')

    @property
    def nombre_completo(self):
        """Devuelve el nombre completo del cliente."""
        if self.apellido:
            return f"{self.nombre} {self.apellido}"
        return self.nombre

    @property
    def telefono_formateado(self):
        """Devuelve el teléfono en formato internacional para Argentina."""
        if not self.telefono_whatsapp:
            return None
        # Limpiar caracteres no numéricos excepto +
        tel = ''.join(c for c in self.telefono_whatsapp if c.isdigit() or c == '+')

        # Si ya tiene código de país completo, retornar
        if tel.startswith('+'):
            return tel
        if tel.startswith('54') and len(tel) > 10:
            return '+' + tel

        # Quitar 0 inicial (prefijo local argentino)
        if tel.startswith('0'):
            tel = tel[1:]

        # Agregar código de Argentina
        return '+54' + tel

    @staticmethod
    def normalizar_telefono_argentina(telefono):
        """
        Normaliza un número de teléfono argentino al formato: 54 + 9 + código área + número.

        Formato final para WhatsApp Argentina: 5491112345678 (sin +, sin espacios)

        Ejemplos de entrada -> salida:
        - "+54 9 11 1234-5678" -> "5491112345678"
        - "011 15 1234-5678" -> "5491112345678"
        - "15 1234 5678" -> None (necesita código de área)
        - "11 1234 5678" -> "5491112345678"
        - "1112345678" -> "5491112345678"
        - "5491112345678" -> "5491112345678"

        Args:
            telefono: Número de teléfono en cualquier formato

        Returns:
            tuple: (numero_normalizado, error_mensaje)
                   Si es válido: ("5491112345678", None)
                   Si hay error: (None, "mensaje de error")
        """
        if not telefono:
            return None, "El teléfono es requerido"

        # Limpiar: solo dígitos
        digitos = ''.join(c for c in str(telefono) if c.isdigit())

        if not digitos:
            return None, "El teléfono no contiene números válidos"

        # Si ya tiene formato completo 549XXXXXXXXXX (13 dígitos)
        if digitos.startswith('549') and len(digitos) >= 12 and len(digitos) <= 14:
            return digitos, None

        # Si tiene 54 pero no 549, agregar el 9
        if digitos.startswith('54') and not digitos.startswith('549'):
            digitos = '549' + digitos[2:]
            if len(digitos) >= 12 and len(digitos) <= 14:
                return digitos, None

        # Quitar prefijos locales argentinos
        # 0XX (código de área con 0) o 15 (prefijo celular)
        if digitos.startswith('0'):
            digitos = digitos[1:]

        # Si empieza con 15, necesitamos el código de área
        if digitos.startswith('15'):
            return None, "Falta el código de área. Ejemplo: 11 15 1234-5678 para Buenos Aires"

        # Quitar 15 si está después del código de área
        # Detectar código de área (2-4 dígitos) seguido de 15
        # Códigos de 2 dígitos: 11 (CABA/GBA)
        # Códigos de 3 dígitos: 221 (La Plata), 351 (Córdoba), etc.
        # Códigos de 4 dígitos: 2901 (Ushuaia), etc.

        numero_sin_15 = digitos

        # Patrón: código de área + 15 + número
        # Buscar 15 en posiciones 2, 3 o 4
        for pos in [2, 3, 4]:
            if len(digitos) > pos + 2 and digitos[pos:pos+2] == '15':
                numero_sin_15 = digitos[:pos] + digitos[pos+2:]
                break

        digitos = numero_sin_15

        # Validar longitud: código de área (2-4) + número (8) = 10-12 dígitos
        if len(digitos) < 10:
            return None, f"Número muy corto ({len(digitos)} dígitos). Debe incluir código de área + número"

        if len(digitos) > 12:
            return None, f"Número muy largo ({len(digitos)} dígitos). Verificar formato"

        # Formato final: 549 + número
        resultado = '549' + digitos

        return resultado, None

    def establecer_telefono(self, telefono):
        """
        Establece el teléfono normalizándolo al formato argentino.

        Returns:
            tuple: (exito: bool, mensaje: str)
        """
        normalizado, error = Cliente.normalizar_telefono_argentina(telefono)
        if error:
            return False, error

        self.telefono_whatsapp = normalizado
        return True, f"Teléfono guardado: {normalizado}"

    def evaluar_si_actual(self):
        """
        Evalúa si el cliente cumple criterios de 'cliente actual'.

        Criterios:
        1. Comunicación exitosa en últimos 6 meses (WhatsApp enviado)
        2. Póliza emitida/vigente en el último año

        Returns:
            tuple: (es_actual: bool, detalles: dict)
        """
        from datetime import timedelta

        hoy = datetime.utcnow()

        # Criterio 1: Comunicación en últimos 6 meses
        hace_6_meses = hoy - timedelta(days=180)
        tiene_comunicacion = self.ultimo_envio is not None and self.ultimo_envio >= hace_6_meses

        # Criterio 2: Póliza emitida en último año (o con vigencia activa)
        hace_1_anio = (hoy - timedelta(days=365)).date()
        tiene_poliza_reciente = False

        for poliza in self.polizas:
            if poliza.estado not in ('activa', 'en_renovacion'):
                continue
            # Verificar si la póliza fue emitida en el último año
            if poliza.fecha_vigencia_desde and poliza.fecha_vigencia_desde >= hace_1_anio:
                tiene_poliza_reciente = True
                break
            # O si aún está vigente
            if poliza.fecha_vigencia_hasta and poliza.fecha_vigencia_hasta >= hoy.date():
                tiene_poliza_reciente = True
                break

        es_actual = tiene_comunicacion and tiene_poliza_reciente

        return es_actual, {
            'comunicacion': tiene_comunicacion,
            'poliza': tiene_poliza_reciente
        }

    def actualizar_estado_actual(self):
        """Actualiza el estado de cliente actual y guarda el motivo si no lo es."""
        es_actual, detalles = self.evaluar_si_actual()

        self.es_cliente_actual = es_actual
        self.fecha_evaluacion_actual = datetime.utcnow()

        if not es_actual:
            if not detalles['comunicacion'] and not detalles['poliza']:
                self.motivo_no_actual = 'ambos'
            elif not detalles['comunicacion']:
                self.motivo_no_actual = 'sin_comunicacion'
            else:
                self.motivo_no_actual = 'sin_poliza_reciente'
        else:
            self.motivo_no_actual = None

        return es_actual, detalles

    @staticmethod
    def normalizar_documento(documento):
        """
        Normaliza un documento (DNI/CUIT/CUIL) quitando caracteres no numéricos.

        Args:
            documento: String con el documento (ej: "20-12345678-9", "12.345.678")

        Returns:
            str: Documento solo con números, o None si está vacío
        """
        if not documento:
            return None
        # Quitar todo excepto números
        normalizado = ''.join(c for c in documento if c.isdigit())
        return normalizado if normalizado else None

    @classmethod
    def buscar_por_documento(cls, usuario_id, documento):
        """
        Busca un cliente existente por documento.

        Args:
            usuario_id: ID del usuario dueño del cliente
            documento: Documento a buscar (se normaliza automáticamente)

        Returns:
            Cliente o None
        """
        doc_normalizado = cls.normalizar_documento(documento)
        if not doc_normalizado:
            return None

        # Buscar cliente con documento que coincida (normalizado)
        clientes = cls.query.filter_by(
            usuario_id=usuario_id,
            activo=True
        ).filter(
            cls.documento_identidad.isnot(None)
        ).all()

        for cliente in clientes:
            if cls.normalizar_documento(cliente.documento_identidad) == doc_normalizado:
                return cliente

        return None

    @classmethod
    def obtener_o_crear(cls, usuario_id, nombre, telefono_whatsapp,
                        apellido=None, email=None, documento_identidad=None,
                        notas=None, actualizar_existente=True):
        """
        Obtiene un cliente existente por documento o crea uno nuevo.

        Si existe un cliente con el mismo documento (normalizado), retorna ese cliente.
        Opcionalmente actualiza los datos del cliente existente.

        Args:
            usuario_id: ID del usuario dueño del cliente
            nombre: Nombre del cliente
            telefono_whatsapp: Teléfono de WhatsApp
            apellido: Apellido (opcional)
            email: Email (opcional)
            documento_identidad: DNI/CUIT/CUIL (opcional)
            notas: Notas adicionales (opcional)
            actualizar_existente: Si True, actualiza datos del cliente existente

        Returns:
            tuple: (cliente, es_nuevo, mensaje)
                - cliente: Instancia de Cliente
                - es_nuevo: True si se creó, False si existía
                - mensaje: Descripción de la acción realizada
        """
        # Buscar cliente existente por documento
        cliente_existente = None
        if documento_identidad:
            cliente_existente = cls.buscar_por_documento(usuario_id, documento_identidad)

        if cliente_existente:
            mensaje = f"Cliente existente encontrado: {cliente_existente.nombre_completo}"

            if actualizar_existente:
                # Actualizar datos si están vacíos o si los nuevos son más completos
                cambios = []

                if telefono_whatsapp and telefono_whatsapp != cliente_existente.telefono_whatsapp:
                    cliente_existente.telefono_whatsapp = telefono_whatsapp
                    cambios.append("teléfono")

                if email and not cliente_existente.email:
                    cliente_existente.email = email
                    cambios.append("email")

                if apellido and not cliente_existente.apellido:
                    cliente_existente.apellido = apellido
                    cambios.append("apellido")

                if notas and not cliente_existente.notas:
                    cliente_existente.notas = notas
                    cambios.append("notas")

                if cambios:
                    mensaje += f" (actualizado: {', '.join(cambios)})"

            return cliente_existente, False, mensaje

        # Crear nuevo cliente
        nuevo_cliente = cls(
            usuario_id=usuario_id,
            nombre=nombre,
            apellido=apellido,
            telefono_whatsapp=telefono_whatsapp,
            email=email,
            documento_identidad=documento_identidad,
            notas=notas
        )
        db.session.add(nuevo_cliente)

        return nuevo_cliente, True, "Cliente creado exitosamente"

    def __repr__(self):
        return f'<Cliente {self.nombre_completo}>'


class PolizaCliente(db.Model):
    """Modelo para asociar pólizas con clientes."""

    __tablename__ = 'polizas_cliente'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False, index=True)
    archivo_id = db.Column(db.Integer, db.ForeignKey('archivos_descargados.id'), nullable=True, index=True)
    compania_id = db.Column(db.Integer, db.ForeignKey('companias.id'), nullable=True, index=True)
    inmobiliaria_id = db.Column(db.Integer, db.ForeignKey('inmobiliarias.id'), nullable=True, index=True)
    numero_poliza = db.Column(db.String(50), nullable=True, index=True)
    tipo_seguro = db.Column(db.String(50), nullable=True, index=True)
    fecha_vigencia_desde = db.Column(db.Date, nullable=True, index=True)
    fecha_vigencia_hasta = db.Column(db.Date, nullable=True, index=True)
    prima_anual = db.Column(db.Numeric(10, 2), nullable=True)
    notas = db.Column(db.Text, nullable=True)
    fecha_asignacion = db.Column(db.DateTime, default=datetime.utcnow)

    # ========== DATOS DEL ASEGURADO ==========
    asegurado_nombre = db.Column(db.String(150), nullable=True)
    asegurado_documento = db.Column(db.String(30), nullable=True)
    asegurado_direccion = db.Column(db.String(255), nullable=True)
    asegurado_telefono = db.Column(db.String(30), nullable=True)
    asegurado_email = db.Column(db.String(120), nullable=True)

    # ========== BIEN ASEGURADO ==========
    bien_asegurado_tipo = db.Column(db.String(50), nullable=True)  # vehiculo, inmueble, persona, otro
    bien_asegurado_descripcion = db.Column(db.Text, nullable=True)
    bien_asegurado_valor = db.Column(db.Numeric(12, 2), nullable=True)

    # ========== DATOS DE VEHÍCULO ==========
    vehiculo_marca = db.Column(db.String(50), nullable=True)
    vehiculo_modelo = db.Column(db.String(50), nullable=True)
    vehiculo_anio = db.Column(db.Integer, nullable=True)
    vehiculo_patente = db.Column(db.String(20), nullable=True)
    vehiculo_chasis = db.Column(db.String(50), nullable=True)
    vehiculo_motor = db.Column(db.String(50), nullable=True)
    vehiculo_color = db.Column(db.String(30), nullable=True)
    vehiculo_uso = db.Column(db.String(50), nullable=True)  # particular, comercial, etc.

    # ========== DATOS DE INMUEBLE ==========
    inmueble_direccion = db.Column(db.String(255), nullable=True)
    inmueble_tipo = db.Column(db.String(50), nullable=True)  # casa, departamento, local, etc.
    inmueble_superficie = db.Column(db.Numeric(10, 2), nullable=True)
    inmueble_construccion = db.Column(db.String(50), nullable=True)  # material, mixta, etc.

    # ========== COBERTURAS Y DEDUCIBLES ==========
    coberturas = db.Column(db.Text, nullable=True)  # JSON con lista de coberturas
    suma_asegurada = db.Column(db.Numeric(12, 2), nullable=True)
    deducible = db.Column(db.Numeric(10, 2), nullable=True)
    franquicia = db.Column(db.Numeric(10, 2), nullable=True)

    # ========== BENEFICIARIOS (seguros de vida) ==========
    beneficiarios = db.Column(db.Text, nullable=True)  # JSON con lista de beneficiarios

    # ========== ESTADO Y RENOVACIÓN ==========
    estado = db.Column(db.String(20), default='activa', index=True)  # activa, vencida, cancelada, en_renovacion, suspendida
    renovacion_automatica = db.Column(db.Boolean, default=False)
    poliza_anterior_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=True)
    motivo_cancelacion = db.Column(db.Text, nullable=True)
    fecha_cancelacion = db.Column(db.Date, nullable=True)

    # ========== ESTADO DE CONFIRMACIÓN ==========
    estado_confirmacion = db.Column(db.String(20), default='pendiente')  # pendiente, definitivo
    fecha_confirmacion = db.Column(db.DateTime, nullable=True)
    confirmado_por = db.Column(db.String(50), nullable=True)  # 'whatsapp_read', 'manual'

    # ========== FORMA DE PAGO ==========
    forma_pago = db.Column(db.String(20), nullable=True)  # anual, semestral, trimestral, mensual
    cantidad_cuotas = db.Column(db.Integer, nullable=True)
    dia_vencimiento_cuota = db.Column(db.Integer, nullable=True)
    medio_pago = db.Column(db.String(30), nullable=True)  # efectivo, transferencia, debito_auto, tarjeta

    # ========== CONTACTO PRODUCTOR/ASEGURADORA ==========
    productor_nombre = db.Column(db.String(100), nullable=True)
    productor_telefono = db.Column(db.String(30), nullable=True)
    productor_email = db.Column(db.String(120), nullable=True)
    sucursal = db.Column(db.String(100), nullable=True)

    # ========== DATOS EXTRAÍDOS AUTOMÁTICAMENTE ==========
    datos_extraidos = db.Column(db.Text, nullable=True)  # JSON con datos raw del PDF
    confianza_extraccion = db.Column(db.Float, nullable=True)  # 0-1, nivel de confianza
    requiere_revision = db.Column(db.Boolean, default=False)
    fecha_extraccion = db.Column(db.DateTime, nullable=True)

    # ========== BACKUP DEL PDF ==========
    ruta_pdf_backup = db.Column(db.String(500), nullable=True)  # Ruta al PDF guardado permanentemente
    fecha_backup = db.Column(db.DateTime, nullable=True)  # Cuando se hizo el backup

    # ========== AUDITORÍA ==========
    fecha_ultima_modificacion = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)
    modificado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    # Relaciones
    archivo = db.relationship('ArchivoDescargado', backref='polizas_asignadas')
    compania = db.relationship('Compania', backref='polizas_asignadas')
    inmobiliaria = db.relationship('Inmobiliaria', backref='polizas')
    envios = db.relationship('EnvioWhatsApp', backref='poliza', lazy='dynamic')
    poliza_anterior = db.relationship('PolizaCliente', remote_side=[id], backref='renovaciones')
    modificado_por = db.relationship('Usuario', foreign_keys=[modificado_por_id])

    TIPOS_SEGURO = [
        ('auto', 'Automóvil'),
        ('moto', 'Motocicleta'),
        ('vida', 'Vida'),
        ('hogar', 'Hogar'),
        ('incendio', 'Incendio'),
        ('salud', 'Salud'),
        ('accidentes', 'Accidentes Personales'),
        ('responsabilidad', 'Responsabilidad Civil'),
        ('comercio', 'Comercio'),
        ('industria', 'Industria'),
        ('transporte', 'Transporte'),
        ('caucion', 'Caución'),
        ('viaje', 'Viaje'),
        ('mascota', 'Mascota'),
        ('agricola', 'Agrícola'),
        ('tecnico', 'Riesgos Técnicos'),
        ('otro', 'Otro')
    ]

    TIPOS_BIEN = [
        ('vehiculo', 'Vehículo'),
        ('inmueble', 'Inmueble'),
        ('persona', 'Persona'),
        ('maquinaria', 'Maquinaria'),
        ('mercaderia', 'Mercadería'),
        ('otro', 'Otro')
    ]

    ESTADOS = [
        ('activa', 'Activa'),
        ('vencida', 'Vencida'),
        ('cancelada', 'Cancelada'),
        ('en_renovacion', 'En Renovación'),
        ('suspendida', 'Suspendida')
    ]

    FORMAS_PAGO = [
        ('anual', 'Anual'),
        ('semestral', 'Semestral'),
        ('trimestral', 'Trimestral'),
        ('mensual', 'Mensual'),
        ('unico', 'Pago Único')
    ]

    def dias_para_vencimiento(self):
        """Retorna días hasta el vencimiento de la póliza."""
        if self.fecha_vigencia_hasta:
            from datetime import date
            dias = (self.fecha_vigencia_hasta - date.today()).days
            return dias
        return None

    def esta_por_vencer(self, dias=30):
        """Verifica si la póliza vence en los próximos N días."""
        dias_restantes = self.dias_para_vencimiento()
        if dias_restantes is not None:
            return 0 <= dias_restantes <= dias
        return False

    def esta_vencida(self):
        """Verifica si la póliza está vencida."""
        dias_restantes = self.dias_para_vencimiento()
        if dias_restantes is not None:
            return dias_restantes < 0
        return False

    def actualizar_estado_automatico(self):
        """Actualiza el estado basado en la fecha de vigencia."""
        if self.estado not in ('cancelada', 'suspendida'):
            if self.esta_vencida():
                self.estado = 'vencida'
            elif self.esta_por_vencer(dias=15):
                self.estado = 'en_renovacion'
            else:
                self.estado = 'activa'

    def obtener_coberturas_lista(self):
        """Devuelve las coberturas como lista."""
        if self.coberturas:
            import json
            try:
                return json.loads(self.coberturas)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    def establecer_coberturas(self, lista_coberturas):
        """Guarda las coberturas desde una lista."""
        import json
        self.coberturas = json.dumps(lista_coberturas)

    def obtener_beneficiarios_lista(self):
        """Devuelve los beneficiarios como lista."""
        if self.beneficiarios:
            import json
            try:
                return json.loads(self.beneficiarios)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    def establecer_beneficiarios(self, lista_beneficiarios):
        """Guarda los beneficiarios desde una lista."""
        import json
        self.beneficiarios = json.dumps(lista_beneficiarios)

    def marcar_definitivo(self, origen='manual'):
        """Marca la póliza como definitiva/confirmada."""
        self.estado_confirmacion = 'definitivo'
        self.fecha_confirmacion = datetime.utcnow()
        self.confirmado_por = origen

    def obtener_nombre_compania(self):
        """
        Obtiene el nombre de la compañía de múltiples fuentes.

        Orden de prioridad:
        1. poliza.compania.nombre (relación directa)
        2. poliza.archivo.compania.nombre (a través del archivo)
        3. poliza.archivo.nombre_compania_original (string guardado)
        4. Extraer del nombre del archivo

        Returns:
            str: Nombre de la compañía o None si no se puede determinar
        """
        # 1. Compañía directa de la póliza
        if self.compania:
            return self.compania.nombre

        # 2 y 3. A través del archivo descargado
        if self.archivo:
            # 2. Compañía del archivo
            if self.archivo.compania:
                return self.archivo.compania.nombre

            # 3. Nombre original guardado
            if self.archivo.nombre_compania_original:
                return self.archivo.nombre_compania_original

            # 4. Extraer del nombre del archivo
            nombre_archivo = self.archivo.nombre_archivo
            if nombre_archivo:
                return self._extraer_compania_de_nombre(nombre_archivo)

        return None

    def _extraer_compania_de_nombre(self, nombre_archivo):
        """
        Intenta extraer el nombre de la compañía del nombre del archivo.

        Los archivos suelen tener formato: COMPANIA_tipo_numero.pdf
        Ejemplo: MERCANTIL_ANDINA_poliza_12345.pdf
        """
        import re

        # Diccionario de patrones conocidos en nombres de archivo
        PATRONES_COMPANIA = {
            r'mercantil|lamercantil': 'Mercantil Andina',
            r'liderar': 'Liderar',
            r'rio.?uruguay|riouruguay': 'Río Uruguay',
            r'berkley': 'Berkley',
            r'mapfre': 'MAPFRE',
            r'la.?caja|lacaja': 'La Caja',
            r'sancor': 'Sancor',
            r'allianz': 'Allianz',
            r'zurich': 'Zurich',
            r'sura': 'SURA',
            r'la.?segunda|lasegunda': 'La Segunda',
            r'provincia': 'Provincia Seguros',
            r'san.?cristobal|sancristobal': 'San Cristóbal',
            r'federacion|patronal': 'Federación Patronal',
            r'triunfo': 'Triunfo',
            r'integrity': 'Integrity',
            r'orbis': 'Orbis',
            r'rivadavia': 'Rivadavia',
            r'experta': 'Experta',
        }

        nombre_lower = nombre_archivo.lower()

        for patron, nombre_compania in PATRONES_COMPANIA.items():
            if re.search(patron, nombre_lower):
                return nombre_compania

        # Si no coincide ningún patrón, intentar extraer la primera palabra
        # antes de un guión bajo o número (heurística)
        match = re.match(r'^([A-Za-z]+(?:_[A-Za-z]+)?)', nombre_archivo)
        if match:
            posible_compania = match.group(1).replace('_', ' ').title()
            # Solo devolver si tiene más de 3 caracteres y parece un nombre
            if len(posible_compania) > 3 and not posible_compania.isdigit():
                return posible_compania

        return None

    def __repr__(self):
        return f'<PolizaCliente {self.numero_poliza or self.id}>'


class EnvioWhatsApp(db.Model):
    """Modelo para registrar envíos de WhatsApp."""

    __tablename__ = 'envios_whatsapp'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    poliza_cliente_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=True)
    archivo_id = db.Column(db.Integer, db.ForeignKey('archivos_descargados.id'), nullable=True)
    mensaje_enviado = db.Column(db.Text, nullable=True)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, enviado, error
    fecha_programada = db.Column(db.DateTime, nullable=True)
    fecha_envio = db.Column(db.DateTime, nullable=True)
    mensaje_error = db.Column(db.Text, nullable=True)
    intentos = db.Column(db.Integer, default=0)

    # ========== TRACKING WHATSAPP ==========
    wamid = db.Column(db.String(100), nullable=True, index=True)  # WhatsApp Message ID
    estado_mensaje = db.Column(db.String(20), nullable=True)  # sent, delivered, read, failed
    fecha_entregado = db.Column(db.DateTime, nullable=True)
    fecha_leido = db.Column(db.DateTime, nullable=True)

    # Relaciones
    archivo = db.relationship('ArchivoDescargado', backref='envios')

    def marcar_enviado(self):
        """Marca el envío como completado."""
        self.estado = 'enviado'
        self.fecha_envio = datetime.utcnow()
        self.cliente.ultimo_envio = datetime.utcnow()

    def marcar_error(self, mensaje):
        """Marca el envío como error."""
        self.estado = 'error'
        self.mensaje_error = mensaje
        self.intentos += 1

    def actualizar_estado_mensaje(self, nuevo_estado, timestamp=None):
        """Actualiza el estado del mensaje de WhatsApp y marca como definitivo si es leído."""
        self.estado_mensaje = nuevo_estado

        if nuevo_estado == 'delivered':
            self.fecha_entregado = timestamp or datetime.utcnow()
        elif nuevo_estado == 'read':
            self.fecha_leido = timestamp or datetime.utcnow()
            # Marcar póliza como definitiva
            if self.poliza:
                self.poliza.marcar_definitivo('whatsapp_read')
            # Marcar archivo como definitivo
            if self.archivo:
                self.archivo.estado_confirmacion = 'definitivo'
                self.archivo.fecha_confirmacion = datetime.utcnow()
                self.archivo.confirmado_por = 'whatsapp_read'

    @staticmethod
    def buscar_por_wamid(wamid):
        """Busca un envío por su WhatsApp Message ID."""
        return EnvioWhatsApp.query.filter_by(wamid=wamid).first()

    def __repr__(self):
        return f'<EnvioWhatsApp {self.id} - {self.estado}>'


class PlantillaMensaje(db.Model):
    """Modelo para plantillas de mensajes de WhatsApp."""

    __tablename__ = 'plantillas_mensaje'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    nombre_plantilla = db.Column(db.String(100), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    es_predeterminada = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_modificacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relación con usuario
    usuario = db.relationship('Usuario', backref='plantillas_mensaje')

    VARIABLES_DISPONIBLES = {
        '{nombre}': 'Nombre del cliente',
        '{apellido}': 'Apellido del cliente',
        '{nombre_completo}': 'Nombre completo',
        '{compania}': 'Nombre de la compañía',
        '{tipo_seguro}': 'Tipo de seguro',
        '{numero_poliza}': 'Número de póliza',
        '{vigencia_desde}': 'Fecha inicio vigencia',
        '{vigencia_hasta}': 'Fecha fin vigencia',
        '{prima}': 'Prima anual'
    }

    def renderizar(self, cliente, poliza=None):
        """Renderiza el mensaje sustituyendo las variables."""
        mensaje = self.mensaje

        # Variables del cliente
        mensaje = mensaje.replace('{nombre}', cliente.nombre or '')
        mensaje = mensaje.replace('{apellido}', cliente.apellido or '')
        mensaje = mensaje.replace('{nombre_completo}', cliente.nombre_completo or '')

        # Variables de la póliza
        if poliza:
            mensaje = mensaje.replace('{compania}', poliza.obtener_nombre_compania() or '')
            mensaje = mensaje.replace('{tipo_seguro}', poliza.tipo_seguro or '')
            mensaje = mensaje.replace('{numero_poliza}', poliza.numero_poliza or '')
            mensaje = mensaje.replace('{vigencia_desde}',
                poliza.fecha_vigencia_desde.strftime('%d/%m/%Y') if poliza.fecha_vigencia_desde else '')
            mensaje = mensaje.replace('{vigencia_hasta}',
                poliza.fecha_vigencia_hasta.strftime('%d/%m/%Y') if poliza.fecha_vigencia_hasta else '')
            mensaje = mensaje.replace('{prima}',
                f"{poliza.prima_anual:.2f}" if poliza.prima_anual else '')
        else:
            # Limpiar variables de póliza si no hay póliza
            for var in ['{compania}', '{tipo_seguro}', '{numero_poliza}',
                       '{vigencia_desde}', '{vigencia_hasta}', '{prima}']:
                mensaje = mensaje.replace(var, '')

        return mensaje.strip()

    @staticmethod
    def obtener_predeterminada(usuario_id):
        """Obtiene la plantilla predeterminada del usuario."""
        return PlantillaMensaje.query.filter_by(
            usuario_id=usuario_id,
            es_predeterminada=True
        ).first()

    def __repr__(self):
        return f'<PlantillaMensaje {self.nombre_plantilla}>'


# ============================================================================
# MODELOS CRM - GESTIÓN DE PÓLIZAS
# ============================================================================

class Pago(db.Model):
    """Modelo para gestión de pagos de primas."""

    __tablename__ = 'pagos'

    id = db.Column(db.Integer, primary_key=True)
    poliza_cliente_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=False)
    numero_cuota = db.Column(db.Integer, nullable=True)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    fecha_vencimiento = db.Column(db.Date, nullable=False)
    fecha_pago = db.Column(db.Date, nullable=True)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, pagado, vencido, anulado
    metodo_pago = db.Column(db.String(30), nullable=True)  # efectivo, transferencia, tarjeta, debito_auto, cheque
    comprobante = db.Column(db.String(100), nullable=True)
    notas = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    poliza = db.relationship('PolizaCliente', backref=db.backref('pagos', lazy='dynamic', cascade='all, delete-orphan'))

    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('pagado', 'Pagado'),
        ('vencido', 'Vencido'),
        ('anulado', 'Anulado')
    ]

    METODOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia Bancaria'),
        ('tarjeta', 'Tarjeta de Crédito/Débito'),
        ('debito_auto', 'Débito Automático'),
        ('cheque', 'Cheque'),
        ('otro', 'Otro')
    ]

    def marcar_pagado(self, fecha=None, metodo=None, comprobante=None):
        """Marca el pago como realizado."""
        from datetime import date
        self.estado = 'pagado'
        self.fecha_pago = fecha or date.today()
        if metodo:
            self.metodo_pago = metodo
        if comprobante:
            self.comprobante = comprobante

    def esta_vencido(self):
        """Verifica si el pago está vencido."""
        from datetime import date
        if self.estado == 'pendiente' and self.fecha_vencimiento:
            return self.fecha_vencimiento < date.today()
        return False

    def actualizar_estado_automatico(self):
        """Actualiza el estado si está vencido."""
        if self.estado == 'pendiente' and self.esta_vencido():
            self.estado = 'vencido'

    def __repr__(self):
        return f'<Pago {self.id} - Cuota {self.numero_cuota} - {self.estado}>'


class Interaccion(db.Model):
    """Modelo para historial de interacciones CRM con clientes."""

    __tablename__ = 'interacciones'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    poliza_cliente_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    tipo = db.Column(db.String(30), nullable=False)  # llamada, email, whatsapp, reunion, nota, visita
    direccion = db.Column(db.String(20), nullable=True)  # entrante, saliente
    asunto = db.Column(db.String(200), nullable=True)
    descripcion = db.Column(db.Text, nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    duracion_minutos = db.Column(db.Integer, nullable=True)

    # Seguimiento
    requiere_seguimiento = db.Column(db.Boolean, default=False)
    fecha_seguimiento = db.Column(db.Date, nullable=True)
    seguimiento_completado = db.Column(db.Boolean, default=False)
    notas_seguimiento = db.Column(db.Text, nullable=True)

    # Relaciones
    cliente = db.relationship('Cliente', backref=db.backref('interacciones', lazy='dynamic', cascade='all, delete-orphan'))
    poliza = db.relationship('PolizaCliente', backref=db.backref('interacciones', lazy='dynamic'))
    usuario = db.relationship('Usuario', backref=db.backref('interacciones_registradas', lazy='dynamic'))

    TIPOS = [
        ('llamada', 'Llamada Telefónica'),
        ('email', 'Correo Electrónico'),
        ('whatsapp', 'WhatsApp'),
        ('reunion', 'Reunión'),
        ('visita', 'Visita'),
        ('nota', 'Nota Interna')
    ]

    DIRECCIONES = [
        ('entrante', 'Entrante'),
        ('saliente', 'Saliente')
    ]

    def marcar_seguimiento_completado(self, notas=None):
        """Marca el seguimiento como completado."""
        self.seguimiento_completado = True
        if notas:
            self.notas_seguimiento = notas

    def __repr__(self):
        return f'<Interaccion {self.id} - {self.tipo}>'


class AlertaVencimiento(db.Model):
    """Modelo para alertas de vencimiento de pólizas y pagos."""

    __tablename__ = 'alertas_vencimiento'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    poliza_cliente_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=True)
    pago_id = db.Column(db.Integer, db.ForeignKey('pagos.id'), nullable=True)

    tipo = db.Column(db.String(30), nullable=False)  # vencimiento_poliza, vencimiento_pago, renovacion, seguimiento
    fecha_alerta = db.Column(db.Date, nullable=False)
    dias_anticipacion = db.Column(db.Integer, nullable=True)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, notificada, descartada, resuelta
    fecha_notificacion = db.Column(db.DateTime, nullable=True)
    mensaje = db.Column(db.Text, nullable=True)
    prioridad = db.Column(db.String(10), default='media')  # alta, media, baja

    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    usuario = db.relationship('Usuario', backref=db.backref('alertas', lazy='dynamic'))
    poliza = db.relationship('PolizaCliente', backref=db.backref('alertas', lazy='dynamic'))
    pago = db.relationship('Pago', backref=db.backref('alertas', lazy='dynamic'))

    TIPOS = [
        ('vencimiento_poliza', 'Vencimiento de Póliza'),
        ('vencimiento_pago', 'Vencimiento de Pago'),
        ('renovacion', 'Renovación Pendiente'),
        ('seguimiento', 'Seguimiento Pendiente')
    ]

    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('notificada', 'Notificada'),
        ('descartada', 'Descartada'),
        ('resuelta', 'Resuelta')
    ]

    PRIORIDADES = [
        ('alta', 'Alta'),
        ('media', 'Media'),
        ('baja', 'Baja')
    ]

    def marcar_notificada(self):
        """Marca la alerta como notificada."""
        self.estado = 'notificada'
        self.fecha_notificacion = datetime.utcnow()

    def marcar_resuelta(self):
        """Marca la alerta como resuelta."""
        self.estado = 'resuelta'

    def descartar(self):
        """Descarta la alerta."""
        self.estado = 'descartada'

    @staticmethod
    def generar_alertas_vencimiento_polizas(usuario_id, dias_anticipacion=[30, 15, 7]):
        """Genera alertas para pólizas próximas a vencer."""
        from datetime import date, timedelta

        polizas = PolizaCliente.query.join(Cliente).filter(
            Cliente.usuario_id == usuario_id,
            PolizaCliente.estado == 'activa',
            PolizaCliente.fecha_vigencia_hasta.isnot(None)
        ).all()

        alertas_creadas = 0
        for poliza in polizas:
            for dias in dias_anticipacion:
                fecha_alerta = poliza.fecha_vigencia_hasta - timedelta(days=dias)
                if fecha_alerta >= date.today():
                    # Verificar si ya existe esta alerta
                    existe = AlertaVencimiento.query.filter_by(
                        poliza_cliente_id=poliza.id,
                        tipo='vencimiento_poliza',
                        dias_anticipacion=dias,
                        estado='pendiente'
                    ).first()

                    if not existe:
                        alerta = AlertaVencimiento(
                            usuario_id=usuario_id,
                            poliza_cliente_id=poliza.id,
                            tipo='vencimiento_poliza',
                            fecha_alerta=fecha_alerta,
                            dias_anticipacion=dias,
                            mensaje=f'La póliza {poliza.numero_poliza or poliza.id} del cliente {poliza.cliente.nombre_completo} vence en {dias} días.',
                            prioridad='alta' if dias <= 7 else 'media'
                        )
                        db.session.add(alerta)
                        alertas_creadas += 1

        db.session.commit()
        return alertas_creadas

    def __repr__(self):
        return f'<AlertaVencimiento {self.id} - {self.tipo} - {self.estado}>'


# ============================================================================
# MODELOS DE MEMORIA DE ESCANEO - Evitar búsquedas repetidas
# ============================================================================

class CorreoProcesado(db.Model):
    """
    Modelo para registrar correos ya procesados y evitar reprocesamiento.

    CRITERIO PRINCIPAL: Cada correo se identifica por su Message-ID unico.
    Si un correo ya fue procesado (existe en esta tabla), se salta.
    Este es el UNICO criterio para determinar si un correo ya fue revisado.
    """

    __tablename__ = 'correos_procesados'

    id = db.Column(db.Integer, primary_key=True)
    cuenta_gmail_id = db.Column(db.Integer, db.ForeignKey('cuentas_gmail.id'), nullable=False)
    message_id = db.Column(db.String(255), nullable=False, index=True)  # Message-ID del correo
    carpeta = db.Column(db.String(100), nullable=False)
    fecha_correo = db.Column(db.DateTime, nullable=True)
    remitente = db.Column(db.String(255), nullable=True)
    asunto = db.Column(db.String(500), nullable=True)
    tiene_pdfs = db.Column(db.Boolean, default=False)
    pdfs_descargados = db.Column(db.Integer, default=0)
    fecha_procesado = db.Column(db.DateTime, default=datetime.utcnow)

    # Indice compuesto para búsquedas rápidas
    __table_args__ = (
        db.UniqueConstraint('cuenta_gmail_id', 'message_id', 'carpeta', name='uq_correo_procesado'),
        db.Index('ix_correo_cuenta_carpeta', 'cuenta_gmail_id', 'carpeta'),
    )

    # Relación
    cuenta = db.relationship('CuentaGmail', backref=db.backref('correos_procesados', lazy='dynamic'))

    @staticmethod
    def ya_procesado(cuenta_gmail_id, message_id, carpeta):
        """Verifica si un correo ya fue procesado."""
        return CorreoProcesado.query.filter_by(
            cuenta_gmail_id=cuenta_gmail_id,
            message_id=message_id,
            carpeta=carpeta
        ).first() is not None

    @staticmethod
    def registrar_procesado(cuenta_gmail_id, message_id, carpeta, fecha_correo=None,
                           remitente=None, asunto=None, tiene_pdfs=False, pdfs_descargados=0):
        """Registra un correo como procesado. Ignora si ya existe."""
        # Verificar si ya existe para evitar IntegrityError
        existente = CorreoProcesado.query.filter_by(
            cuenta_gmail_id=cuenta_gmail_id,
            message_id=message_id,
            carpeta=carpeta
        ).first()

        if existente:
            # Ya existe - actualizar si tiene nuevos PDFs
            if tiene_pdfs and not existente.tiene_pdfs:
                existente.tiene_pdfs = True
                existente.pdfs_descargados = pdfs_descargados
            return existente

        registro = CorreoProcesado(
            cuenta_gmail_id=cuenta_gmail_id,
            message_id=message_id,
            carpeta=carpeta,
            fecha_correo=fecha_correo,
            remitente=remitente,
            asunto=asunto,
            tiene_pdfs=tiene_pdfs,
            pdfs_descargados=pdfs_descargados
        )
        db.session.add(registro)
        return registro

    def __repr__(self):
        return f'<CorreoProcesado {self.message_id[:30]}...>'


class HistorialEscaneoCarpeta(db.Model):
    """
    Modelo para registrar estadisticas de escaneo por cuenta y carpeta.

    IMPORTANTE: Este modelo es SOLO INFORMATIVO/ESTADISTICO.
    NO se usa para filtrar correos (eso dejaria huecos en las fechas).
    El unico criterio para saltar correos es el Message-ID en CorreoProcesado.
    """

    __tablename__ = 'historial_escaneo_carpeta'

    id = db.Column(db.Integer, primary_key=True)
    cuenta_gmail_id = db.Column(db.Integer, db.ForeignKey('cuentas_gmail.id'), nullable=False)
    carpeta = db.Column(db.String(100), nullable=False)
    ultima_fecha_escaneada = db.Column(db.DateTime, nullable=True)  # Fecha del correo más reciente procesado
    ultimo_escaneo = db.Column(db.DateTime, default=datetime.utcnow)  # Cuándo se hizo el escaneo
    correos_totales = db.Column(db.Integer, default=0)
    correos_con_pdf = db.Column(db.Integer, default=0)
    pdfs_descargados = db.Column(db.Integer, default=0)

    # Índice compuesto
    __table_args__ = (
        db.UniqueConstraint('cuenta_gmail_id', 'carpeta', name='uq_historial_cuenta_carpeta'),
    )

    # Relación
    cuenta = db.relationship('CuentaGmail', backref=db.backref('historial_carpetas', lazy='dynamic'))

    @staticmethod
    def obtener_ultima_fecha(cuenta_gmail_id, carpeta):
        """Obtiene la última fecha escaneada para una cuenta y carpeta."""
        historial = HistorialEscaneoCarpeta.query.filter_by(
            cuenta_gmail_id=cuenta_gmail_id,
            carpeta=carpeta
        ).first()
        return historial.ultima_fecha_escaneada if historial else None

    @staticmethod
    def obtener_fecha_mas_reciente_procesada(cuenta_gmail_id, carpeta):
        """
        Obtiene la fecha del correo MAS RECIENTE ya procesado.
        Usado para optimizar: no re-escanear correos anteriores a esta fecha.
        """
        from sqlalchemy import func
        resultado = db.session.query(func.max(CorreoProcesado.fecha_correo)).filter_by(
            cuenta_gmail_id=cuenta_gmail_id,
            carpeta=carpeta
        ).scalar()
        return resultado

    @staticmethod
    def actualizar_historial(cuenta_gmail_id, carpeta, ultima_fecha, correos_totales=0,
                            correos_con_pdf=0, pdfs_descargados=0):
        """Actualiza o crea el historial de escaneo para una carpeta."""
        historial = HistorialEscaneoCarpeta.query.filter_by(
            cuenta_gmail_id=cuenta_gmail_id,
            carpeta=carpeta
        ).first()

        if historial:
            # Solo actualizar si la nueva fecha es más reciente
            if ultima_fecha and (not historial.ultima_fecha_escaneada or
                                ultima_fecha > historial.ultima_fecha_escaneada):
                historial.ultima_fecha_escaneada = ultima_fecha
            historial.ultimo_escaneo = datetime.utcnow()
            historial.correos_totales += correos_totales
            historial.correos_con_pdf += correos_con_pdf
            historial.pdfs_descargados += pdfs_descargados
        else:
            historial = HistorialEscaneoCarpeta(
                cuenta_gmail_id=cuenta_gmail_id,
                carpeta=carpeta,
                ultima_fecha_escaneada=ultima_fecha,
                correos_totales=correos_totales,
                correos_con_pdf=correos_con_pdf,
                pdfs_descargados=pdfs_descargados
            )
            db.session.add(historial)

        return historial

    @staticmethod
    def obtener_resumen_cuenta(cuenta_gmail_id):
        """Obtiene un resumen de todas las carpetas escaneadas de una cuenta."""
        return HistorialEscaneoCarpeta.query.filter_by(
            cuenta_gmail_id=cuenta_gmail_id
        ).all()

    def __repr__(self):
        return f'<HistorialEscaneoCarpeta {self.carpeta} - {self.ultima_fecha_escaneada}>'


class RangoCobertura(db.Model):
    """
    Rastrea rangos de fechas que fueron escaneados para cada cuenta/carpeta.
    Permite identificar gaps en la cobertura de escaneos.

    Cuando un usuario escanea un rango de fechas, se registra aquí.
    Si los rangos se solapan, se fusionan automáticamente.
    """
    __tablename__ = 'rangos_cobertura'

    id = db.Column(db.Integer, primary_key=True)
    cuenta_gmail_id = db.Column(db.Integer, db.ForeignKey('cuentas_gmail.id'), nullable=False)
    carpeta = db.Column(db.String(100), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    escaneo_id = db.Column(db.Integer, db.ForeignKey('escaneos.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_cobertura_cuenta_carpeta', 'cuenta_gmail_id', 'carpeta'),
    )

    cuenta = db.relationship('CuentaGmail', backref=db.backref('rangos_cobertura', lazy='dynamic'))
    escaneo = db.relationship('Escaneo', backref=db.backref('rangos_cobertura', lazy='dynamic'))

    @staticmethod
    def registrar_cobertura(cuenta_gmail_id, carpeta, fecha_inicio, fecha_fin, escaneo_id=None):
        """
        Registra un nuevo rango de cobertura y fusiona con rangos existentes si hay solapamiento.

        Args:
            cuenta_gmail_id: ID de la cuenta Gmail
            carpeta: Nombre de la carpeta escaneada
            fecha_inicio: Fecha de inicio del rango escaneado
            fecha_fin: Fecha de fin del rango escaneado
            escaneo_id: ID del escaneo que generó este rango (opcional)
        """
        from datetime import timedelta

        if not fecha_inicio or not fecha_fin:
            return None

        # Asegurar que fecha_inicio <= fecha_fin
        if fecha_inicio > fecha_fin:
            fecha_inicio, fecha_fin = fecha_fin, fecha_inicio

        # Buscar rangos existentes que se solapen o sean adyacentes
        # Un rango se considera adyacente si está a 1 día de distancia
        rangos_existentes = RangoCobertura.query.filter_by(
            cuenta_gmail_id=cuenta_gmail_id,
            carpeta=carpeta
        ).order_by(RangoCobertura.fecha_inicio).all()

        # Buscar rangos que se solapen o sean adyacentes al nuevo
        rangos_a_fusionar = []
        for rango in rangos_existentes:
            # Verificar si hay solapamiento o adyacencia
            # Solapamiento: rango.inicio <= nuevo.fin AND rango.fin >= nuevo.inicio
            # Adyacencia: rango.fin + 1 día = nuevo.inicio OR nuevo.fin + 1 día = rango.inicio
            if (rango.fecha_inicio <= fecha_fin + timedelta(days=1) and
                rango.fecha_fin >= fecha_inicio - timedelta(days=1)):
                rangos_a_fusionar.append(rango)

        if rangos_a_fusionar:
            # Fusionar todos los rangos encontrados con el nuevo
            nuevo_inicio = min(fecha_inicio, min(r.fecha_inicio for r in rangos_a_fusionar))
            nuevo_fin = max(fecha_fin, max(r.fecha_fin for r in rangos_a_fusionar))

            # Eliminar los rangos que se van a fusionar
            for rango in rangos_a_fusionar:
                db.session.delete(rango)

            # Crear el rango fusionado
            rango_fusionado = RangoCobertura(
                cuenta_gmail_id=cuenta_gmail_id,
                carpeta=carpeta,
                fecha_inicio=nuevo_inicio,
                fecha_fin=nuevo_fin,
                escaneo_id=escaneo_id
            )
            db.session.add(rango_fusionado)
            return rango_fusionado
        else:
            # No hay solapamiento, crear nuevo rango
            nuevo_rango = RangoCobertura(
                cuenta_gmail_id=cuenta_gmail_id,
                carpeta=carpeta,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                escaneo_id=escaneo_id
            )
            db.session.add(nuevo_rango)
            return nuevo_rango

    @staticmethod
    def obtener_cobertura(cuenta_gmail_id, carpeta=None):
        """
        Obtiene todos los rangos de cobertura para una cuenta.

        Args:
            cuenta_gmail_id: ID de la cuenta Gmail
            carpeta: Filtrar por carpeta específica (opcional)

        Returns:
            Lista de rangos ordenados por fecha de inicio
        """
        query = RangoCobertura.query.filter_by(cuenta_gmail_id=cuenta_gmail_id)
        if carpeta:
            query = query.filter_by(carpeta=carpeta)
        return query.order_by(RangoCobertura.fecha_inicio).all()

    @staticmethod
    def obtener_gaps(cuenta_gmail_id, carpeta, fecha_ref_inicio=None, fecha_ref_fin=None):
        """
        Calcula las ventanas de tiempo no observadas (gaps) entre rangos escaneados.

        Args:
            cuenta_gmail_id: ID de la cuenta Gmail
            carpeta: Nombre de la carpeta
            fecha_ref_inicio: Fecha de referencia inicial (opcional, para limitar el rango de búsqueda)
            fecha_ref_fin: Fecha de referencia final (opcional)

        Returns:
            Lista de tuplas (fecha_inicio_gap, fecha_fin_gap) representando los períodos no escaneados
        """
        from datetime import timedelta

        rangos = RangoCobertura.obtener_cobertura(cuenta_gmail_id, carpeta)

        if not rangos:
            # Si no hay rangos, todo el período de referencia es un gap
            if fecha_ref_inicio and fecha_ref_fin:
                return [(fecha_ref_inicio, fecha_ref_fin)]
            return []

        gaps = []

        # Gap inicial (antes del primer rango)
        if fecha_ref_inicio and rangos[0].fecha_inicio > fecha_ref_inicio:
            gaps.append((fecha_ref_inicio, rangos[0].fecha_inicio - timedelta(days=1)))

        # Gaps entre rangos consecutivos
        for i in range(len(rangos) - 1):
            fin_actual = rangos[i].fecha_fin
            inicio_siguiente = rangos[i + 1].fecha_inicio

            # Si hay más de 1 día entre el fin de uno y el inicio del siguiente
            if (inicio_siguiente - fin_actual).days > 1:
                gap_inicio = fin_actual + timedelta(days=1)
                gap_fin = inicio_siguiente - timedelta(days=1)
                gaps.append((gap_inicio, gap_fin))

        # Gap final (después del último rango)
        if fecha_ref_fin and rangos[-1].fecha_fin < fecha_ref_fin:
            gaps.append((rangos[-1].fecha_fin + timedelta(days=1), fecha_ref_fin))

        return gaps

    @staticmethod
    def obtener_resumen_cobertura(cuenta_gmail_id):
        """
        Obtiene un resumen de cobertura por carpeta.

        Returns:
            Dict con estructura: {carpeta: [(fecha_inicio, fecha_fin), ...]}
        """
        rangos = RangoCobertura.query.filter_by(
            cuenta_gmail_id=cuenta_gmail_id
        ).order_by(RangoCobertura.carpeta, RangoCobertura.fecha_inicio).all()

        resumen = {}
        for rango in rangos:
            if rango.carpeta not in resumen:
                resumen[rango.carpeta] = []
            resumen[rango.carpeta].append((rango.fecha_inicio, rango.fecha_fin))

        return resumen

    def __repr__(self):
        return f'<RangoCobertura {self.carpeta}: {self.fecha_inicio} - {self.fecha_fin}>'


class Siniestro(db.Model):
    """Modelo para gestión de siniestros."""

    __tablename__ = 'siniestros'

    id = db.Column(db.Integer, primary_key=True)
    poliza_cliente_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=False)
    numero_siniestro = db.Column(db.String(50), nullable=True)
    numero_siniestro_compania = db.Column(db.String(50), nullable=True)

    # Datos del siniestro
    fecha_ocurrencia = db.Column(db.Date, nullable=False)
    fecha_denuncia = db.Column(db.Date, nullable=True)
    hora_ocurrencia = db.Column(db.Time, nullable=True)
    descripcion = db.Column(db.Text, nullable=False)
    ubicacion = db.Column(db.String(255), nullable=True)
    tipo_siniestro = db.Column(db.String(50), nullable=True)  # robo, choque, incendio, etc.

    # Terceros involucrados
    terceros_involucrados = db.Column(db.Text, nullable=True)  # JSON con datos de terceros
    hay_lesionados = db.Column(db.Boolean, default=False)
    descripcion_lesiones = db.Column(db.Text, nullable=True)

    # Montos
    monto_reclamado = db.Column(db.Numeric(12, 2), nullable=True)
    monto_aprobado = db.Column(db.Numeric(12, 2), nullable=True)
    monto_pagado = db.Column(db.Numeric(12, 2), nullable=True)
    deducible_aplicado = db.Column(db.Numeric(10, 2), nullable=True)

    # Estado y seguimiento
    estado = db.Column(db.String(30), default='denunciado')  # denunciado, en_proceso, aprobado, rechazado, pagado, cerrado
    fecha_resolucion = db.Column(db.Date, nullable=True)
    motivo_rechazo = db.Column(db.Text, nullable=True)

    # Documentación
    documentos = db.Column(db.Text, nullable=True)  # JSON con lista de documentos adjuntos
    fotos = db.Column(db.Text, nullable=True)  # JSON con rutas de fotos

    notas = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_ultima_actualizacion = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relaciones
    poliza = db.relationship('PolizaCliente', backref=db.backref('siniestros', lazy='dynamic', cascade='all, delete-orphan'))

    ESTADOS = [
        ('denunciado', 'Denunciado'),
        ('en_proceso', 'En Proceso'),
        ('documentacion', 'Esperando Documentación'),
        ('peritaje', 'En Peritaje'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado'),
        ('pagado', 'Pagado'),
        ('cerrado', 'Cerrado')
    ]

    TIPOS_SINIESTRO = [
        ('choque', 'Choque/Colisión'),
        ('robo_total', 'Robo Total'),
        ('robo_parcial', 'Robo Parcial'),
        ('incendio', 'Incendio'),
        ('granizo', 'Granizo'),
        ('inundacion', 'Inundación'),
        ('vandalismo', 'Vandalismo'),
        ('rotura_cristales', 'Rotura de Cristales'),
        ('responsabilidad_civil', 'Responsabilidad Civil'),
        ('accidente_personal', 'Accidente Personal'),
        ('fallecimiento', 'Fallecimiento'),
        ('enfermedad', 'Enfermedad'),
        ('otro', 'Otro')
    ]

    def aprobar(self, monto_aprobado):
        """Aprueba el siniestro con un monto."""
        self.estado = 'aprobado'
        self.monto_aprobado = monto_aprobado

    def rechazar(self, motivo):
        """Rechaza el siniestro con un motivo."""
        self.estado = 'rechazado'
        self.motivo_rechazo = motivo
        self.fecha_resolucion = datetime.utcnow().date()

    def marcar_pagado(self, monto_pagado):
        """Marca el siniestro como pagado."""
        self.estado = 'pagado'
        self.monto_pagado = monto_pagado
        self.fecha_resolucion = datetime.utcnow().date()

    def cerrar(self):
        """Cierra el siniestro."""
        self.estado = 'cerrado'
        if not self.fecha_resolucion:
            self.fecha_resolucion = datetime.utcnow().date()

    def __repr__(self):
        return f'<Siniestro {self.numero_siniestro or self.id} - {self.estado}>'


class RegistroAnalisisPDF(db.Model):
    """
    Modelo para registrar el análisis de PDFs y su procesamiento.
    Permite saber qué PDFs fueron analizados, cuándo, y qué se creó a partir de ellos.
    """

    __tablename__ = 'registros_analisis_pdf'

    id = db.Column(db.Integer, primary_key=True)

    # PDF analizado
    archivo_id = db.Column(db.Integer, db.ForeignKey('archivos_descargados.id'), nullable=False)

    # Cuenta de origen (de dónde vino el PDF)
    cuenta_gmail_id = db.Column(db.Integer, db.ForeignKey('cuentas_gmail.id'), nullable=True)
    cuenta_origen = db.Column(db.String(120), nullable=True)  # Email de la cuenta

    # Rango de fechas del escaneo original
    fecha_correo = db.Column(db.DateTime, nullable=True)  # Fecha del correo que contenía el PDF

    # Estado del análisis
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, analizado, procesado, omitido, error
    fecha_analisis = db.Column(db.DateTime, nullable=True)  # Cuándo se analizó
    fecha_procesamiento = db.Column(db.DateTime, nullable=True)  # Cuándo se creó cliente/póliza

    # Resultados del análisis
    confianza_extraccion = db.Column(db.Float, nullable=True)  # 0.0 a 1.0
    datos_extraidos = db.Column(db.Text, nullable=True)  # JSON con datos extraídos
    compania_detectada = db.Column(db.String(100), nullable=True)
    tipo_seguro_detectado = db.Column(db.String(50), nullable=True)
    numero_poliza_detectado = db.Column(db.String(100), nullable=True)

    # Fechas de vigencia detectadas (para ordenamiento y filtrado)
    fecha_vigencia_desde_detectada = db.Column(db.Date, nullable=True)
    fecha_vigencia_hasta_detectada = db.Column(db.Date, nullable=True)
    asegurado_detectado = db.Column(db.String(200), nullable=True)

    # Resultados del procesamiento
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    poliza_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=True)
    cliente_creado = db.Column(db.Boolean, default=False)  # Si se creó cliente nuevo
    poliza_creada = db.Column(db.Boolean, default=False)  # Si se creó póliza nueva

    # Usuario que procesó
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    # Notas
    notas = db.Column(db.Text, nullable=True)
    motivo_omision = db.Column(db.String(255), nullable=True)  # Si fue omitido, por qué

    # Relaciones
    archivo = db.relationship('ArchivoDescargado', backref=db.backref('registro_analisis', uselist=False))
    cuenta = db.relationship('CuentaGmail', backref=db.backref('registros_analisis', lazy='dynamic'))
    cliente = db.relationship('Cliente', backref=db.backref('registros_analisis', lazy='dynamic'))
    poliza = db.relationship('PolizaCliente', backref=db.backref('registro_analisis', uselist=False))
    usuario = db.relationship('Usuario', backref=db.backref('registros_analisis', lazy='dynamic'))

    # Índices
    __table_args__ = (
        db.Index('ix_registro_analisis_estado', 'estado'),
        db.Index('ix_registro_analisis_fecha', 'fecha_analisis'),
        db.Index('ix_registro_analisis_vigencia', 'fecha_vigencia_hasta_detectada'),
    )

    ESTADOS = [
        ('pendiente', 'Pendiente de análisis'),
        ('analizado', 'Analizado (sin procesar)'),
        ('procesado', 'Procesado (cliente/póliza creada)'),
        ('omitido', 'Omitido manualmente'),
        ('error', 'Error en análisis'),
    ]

    @staticmethod
    def obtener_o_crear(archivo_id):
        """Obtiene o crea un registro de análisis para un archivo."""
        registro = RegistroAnalisisPDF.query.filter_by(archivo_id=archivo_id).first()
        if not registro:
            # Obtener datos del archivo
            archivo = ArchivoDescargado.query.get(archivo_id)
            if archivo:
                registro = RegistroAnalisisPDF(
                    archivo_id=archivo_id,
                    cuenta_origen=archivo.cuenta_origen,
                    fecha_correo=archivo.fecha_correo,
                )
                # Buscar cuenta por correo
                if archivo.cuenta_origen:
                    cuenta = CuentaGmail.query.filter_by(correo_gmail=archivo.cuenta_origen).first()
                    if cuenta:
                        registro.cuenta_gmail_id = cuenta.id
                db.session.add(registro)
                db.session.flush()
        return registro

    def marcar_analizado(self, datos_json, confianza, compania=None, tipo_seguro=None, numero_poliza=None,
                         fecha_vigencia_desde=None, fecha_vigencia_hasta=None, asegurado=None):
        """Marca el registro como analizado."""
        self.estado = 'analizado'
        self.fecha_analisis = datetime.utcnow()
        self.datos_extraidos = datos_json
        self.confianza_extraccion = confianza
        self.compania_detectada = compania
        self.tipo_seguro_detectado = tipo_seguro
        self.numero_poliza_detectado = numero_poliza
        self.fecha_vigencia_desde_detectada = fecha_vigencia_desde
        self.fecha_vigencia_hasta_detectada = fecha_vigencia_hasta
        self.asegurado_detectado = asegurado

    def marcar_procesado(self, cliente_id, poliza_id, cliente_nuevo=False, poliza_nueva=False, usuario_id=None):
        """Marca el registro como procesado."""
        self.estado = 'procesado'
        self.fecha_procesamiento = datetime.utcnow()
        self.cliente_id = cliente_id
        self.poliza_id = poliza_id
        self.cliente_creado = cliente_nuevo
        self.poliza_creada = poliza_nueva
        self.usuario_id = usuario_id

    def marcar_omitido(self, motivo=None, usuario_id=None):
        """Marca el registro como omitido."""
        self.estado = 'omitido'
        self.fecha_procesamiento = datetime.utcnow()
        self.motivo_omision = motivo
        self.usuario_id = usuario_id

    def marcar_error(self, notas=None):
        """Marca el registro como error."""
        self.estado = 'error'
        self.fecha_analisis = datetime.utcnow()
        self.notas = notas

    @staticmethod
    def obtener_estadisticas():
        """Obtiene estadísticas de procesamiento."""
        from sqlalchemy import func

        total = RegistroAnalisisPDF.query.count()
        por_estado = db.session.query(
            RegistroAnalisisPDF.estado,
            func.count(RegistroAnalisisPDF.id)
        ).group_by(RegistroAnalisisPDF.estado).all()

        return {
            'total': total,
            'por_estado': dict(por_estado),
            'pendientes': sum(1 for e, c in por_estado if e == 'pendiente'),
            'procesados': sum(1 for e, c in por_estado if e == 'procesado'),
        }

    @staticmethod
    def obtener_por_cuenta(cuenta_gmail_id=None):
        """Obtiene registros filtrados por cuenta."""
        query = RegistroAnalisisPDF.query
        if cuenta_gmail_id:
            query = query.filter_by(cuenta_gmail_id=cuenta_gmail_id)
        return query.order_by(RegistroAnalisisPDF.fecha_correo.desc()).all()

    def __repr__(self):
        return f'<RegistroAnalisisPDF {self.id} - {self.estado}>'


# ============================================================================
# MODELOS DE INMOBILIARIAS - Gestión de pólizas de incendio/hogar
# ============================================================================

class Inmobiliaria(db.Model):
    """
    Modelo para inmobiliarias administradoras de inmuebles.
    Las pólizas de tipo 'incendio' y 'hogar' pueden asignarse a una inmobiliaria.
    """

    __tablename__ = 'inmobiliarias'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    telefono_whatsapp = db.Column(db.String(30), nullable=True)  # Para notificaciones
    email = db.Column(db.String(120), nullable=True)
    persona_contacto = db.Column(db.String(100), nullable=True)
    activa = db.Column(db.Boolean, default=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    notas = db.Column(db.Text, nullable=True)

    # Relación con usuario
    usuario = db.relationship('Usuario', backref=db.backref('inmobiliarias', lazy='dynamic'))

    # Índice único por usuario y nombre
    __table_args__ = (
        db.UniqueConstraint('usuario_id', 'nombre', name='uq_inmobiliaria_usuario_nombre'),
    )

    @property
    def telefono_formateado(self):
        """Devuelve el teléfono en formato internacional."""
        if not self.telefono_whatsapp:
            return None
        tel = self.telefono_whatsapp.replace(' ', '').replace('-', '')
        if not tel.startswith('+'):
            tel = '+' + tel
        return tel

    def cantidad_polizas_activas(self):
        """Retorna la cantidad de pólizas activas asignadas a esta inmobiliaria."""
        return PolizaCliente.query.filter_by(
            inmobiliaria_id=self.id,
            estado='activa'
        ).count()

    def __repr__(self):
        return f'<Inmobiliaria {self.nombre}>'


class NotificacionInmobiliaria(db.Model):
    """
    Modelo para notificaciones pendientes a inmobiliarias.
    Se procesan junto con la cola de WhatsApp existente.
    """

    __tablename__ = 'notificaciones_inmobiliaria'

    id = db.Column(db.Integer, primary_key=True)
    inmobiliaria_id = db.Column(db.Integer, db.ForeignKey('inmobiliarias.id'), nullable=False)
    poliza_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=False)
    tipo = db.Column(db.String(30), nullable=False)  # vencimiento, renovacion, siniestro, cambio_estado
    mensaje = db.Column(db.Text, nullable=True)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, enviado, error
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_envio = db.Column(db.DateTime, nullable=True)
    intentos = db.Column(db.Integer, default=0)
    mensaje_error = db.Column(db.Text, nullable=True)

    # Relaciones
    inmobiliaria = db.relationship('Inmobiliaria', backref=db.backref('notificaciones', lazy='dynamic'))
    poliza = db.relationship('PolizaCliente', backref=db.backref('notificaciones_inmobiliaria', lazy='dynamic'))

    TIPOS = [
        ('vencimiento', 'Vencimiento Próximo'),
        ('renovacion', 'Renovación'),
        ('siniestro', 'Siniestro'),
        ('cambio_estado', 'Cambio de Estado'),
    ]

    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('enviado', 'Enviado'),
        ('error', 'Error'),
    ]

    def marcar_enviado(self):
        """Marca la notificación como enviada."""
        self.estado = 'enviado'
        self.fecha_envio = datetime.utcnow()

    def marcar_error(self, mensaje):
        """Marca la notificación como error."""
        self.estado = 'error'
        self.mensaje_error = mensaje
        self.intentos += 1

    @staticmethod
    def crear_notificacion(inmobiliaria_id, poliza_id, tipo, mensaje=None):
        """Crea una notificación pendiente."""
        notif = NotificacionInmobiliaria(
            inmobiliaria_id=inmobiliaria_id,
            poliza_id=poliza_id,
            tipo=tipo,
            mensaje=mensaje
        )
        db.session.add(notif)
        return notif

    @staticmethod
    def obtener_pendientes(limite=50):
        """Obtiene notificaciones pendientes de envío."""
        return NotificacionInmobiliaria.query.filter_by(
            estado='pendiente'
        ).order_by(
            NotificacionInmobiliaria.fecha_creacion.asc()
        ).limit(limite).all()

    def __repr__(self):
        return f'<NotificacionInmobiliaria {self.id} - {self.tipo} - {self.estado}>'


# ============================================================================
# SESIONES DE WHATSAPP WEB POR USUARIO
# ============================================================================

class WhatsAppSession(db.Model):
    """
    Modelo para gestionar sesiones de WhatsApp Web por usuario.
    Cada usuario puede tener su propio WhatsApp conectado para enviar pólizas.
    """
    __tablename__ = 'whatsapp_sessions'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), unique=True, nullable=False)

    # Estado de la sesión
    estado = db.Column(db.String(20), default='disconnected')
    # Valores: disconnected, qr_pending, authenticated, ready, error

    # Información del WhatsApp conectado
    telefono_conectado = db.Column(db.String(20), nullable=True)

    # Fechas
    fecha_conexion = db.Column(db.DateTime, nullable=True)
    fecha_ultimo_uso = db.Column(db.DateTime, nullable=True)
    fecha_desconexion = db.Column(db.DateTime, nullable=True)

    # Control
    activo = db.Column(db.Boolean, default=True)
    mensaje_error = db.Column(db.Text, nullable=True)

    # Relación
    usuario = db.relationship('Usuario', backref=db.backref('whatsapp_session', uselist=False))

    # Estados posibles
    ESTADOS = [
        ('disconnected', 'Desconectado'),
        ('qr_pending', 'Esperando QR'),
        ('authenticated', 'Autenticando'),
        ('ready', 'Conectado'),
        ('error', 'Error'),
    ]

    def marcar_conectado(self, telefono=None):
        """Marca la sesión como conectada."""
        self.estado = 'ready'
        self.telefono_conectado = telefono
        self.fecha_conexion = datetime.utcnow()
        self.fecha_ultimo_uso = datetime.utcnow()
        self.mensaje_error = None

    def marcar_desconectado(self):
        """Marca la sesión como desconectada."""
        self.estado = 'disconnected'
        self.fecha_desconexion = datetime.utcnow()

    def marcar_error(self, mensaje):
        """Marca la sesión con error."""
        self.estado = 'error'
        self.mensaje_error = mensaje

    def actualizar_uso(self):
        """Actualiza la fecha de último uso."""
        self.fecha_ultimo_uso = datetime.utcnow()

    @property
    def esta_conectado(self):
        """Verifica si la sesión está lista para usar."""
        return self.estado == 'ready' and self.activo

    @staticmethod
    def obtener_o_crear(usuario_id):
        """Obtiene la sesión del usuario o crea una nueva."""
        session = WhatsAppSession.query.filter_by(usuario_id=usuario_id).first()
        if not session:
            session = WhatsAppSession(usuario_id=usuario_id)
            db.session.add(session)
            db.session.commit()
        return session

    def __repr__(self):
        return f'<WhatsAppSession {self.usuario_id} - {self.estado}>'


# ============================================================================
# LOG DE CORRECCIONES DE EXTRACCION - Sistema de Aprendizaje Predictivo
# ============================================================================

class LogCorreccionExtraccion(db.Model):
    """
    Modelo para registrar correcciones que los usuarios hacen a los datos
    extraídos automáticamente de los PDFs.

    Estos registros se usan para:
    1. Entrenar el algoritmo de extracción predictiva
    2. Analizar patrones de error por compañía/tipo de seguro
    3. Mejorar la confianza de extracciones futuras
    """

    __tablename__ = 'log_correcciones_extraccion'

    id = db.Column(db.Integer, primary_key=True)

    # Referencias
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    archivo_id = db.Column(db.Integer, db.ForeignKey('archivos_descargados.id'), nullable=True)
    poliza_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)

    # Información del campo corregido
    campo = db.Column(db.String(50), nullable=False)  # ej: "cliente.nombre", "poliza.numero_poliza"
    texto_original = db.Column(db.Text, nullable=True)  # Texto crudo extraído del PDF
    valor_extraido = db.Column(db.Text, nullable=True)  # Valor que el algoritmo sugirió
    valor_corregido = db.Column(db.Text, nullable=True)  # Valor que el usuario guardó

    # Tipo de corrección
    tipo_cambio = db.Column(db.String(20), nullable=False)
    # Valores: edicion, agregado_manual, eliminacion

    # Contexto para el aprendizaje
    confianza_original = db.Column(db.Float, nullable=True)  # Confianza del algoritmo (0-1)
    compania = db.Column(db.String(50), nullable=True)  # Compañía aseguradora
    tipo_seguro = db.Column(db.String(30), nullable=True)  # auto, hogar, vida, etc.

    # Metadata
    fecha = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sesion_id = db.Column(db.String(36), nullable=True)  # UUID para agrupar correcciones de una sesión

    # Relaciones
    usuario = db.relationship('Usuario', backref=db.backref('correcciones_extraccion', lazy='dynamic'))
    archivo = db.relationship('ArchivoDescargado', backref=db.backref('correcciones', lazy='dynamic'))
    poliza = db.relationship('PolizaCliente', backref=db.backref('correcciones', lazy='dynamic'))
    cliente = db.relationship('Cliente', backref=db.backref('correcciones', lazy='dynamic'))

    # Tipos de cambio válidos
    TIPOS_CAMBIO = [
        ('edicion', 'Edición'),
        ('agregado_manual', 'Agregado Manual'),
        ('eliminacion', 'Eliminación'),
    ]

    # Índices para consultas frecuentes
    __table_args__ = (
        db.Index('ix_correccion_campo_compania', 'campo', 'compania'),
        db.Index('ix_correccion_fecha', 'fecha'),
        db.Index('ix_correccion_sesion', 'sesion_id'),
    )

    @staticmethod
    def registrar(usuario_id, campo, tipo_cambio, texto_original=None,
                  valor_extraido=None, valor_corregido=None, confianza_original=None,
                  compania=None, tipo_seguro=None, archivo_id=None, poliza_id=None,
                  cliente_id=None, sesion_id=None):
        """
        Registra una corrección de extracción.

        Returns:
            LogCorreccionExtraccion: El registro creado
        """
        log = LogCorreccionExtraccion(
            usuario_id=usuario_id,
            archivo_id=archivo_id,
            poliza_id=poliza_id,
            cliente_id=cliente_id,
            campo=campo,
            texto_original=texto_original,
            valor_extraido=valor_extraido,
            valor_corregido=valor_corregido,
            tipo_cambio=tipo_cambio,
            confianza_original=confianza_original,
            compania=compania,
            tipo_seguro=tipo_seguro,
            sesion_id=sesion_id
        )
        db.session.add(log)
        return log

    @staticmethod
    def obtener_estadisticas_campo(campo, compania=None, limite_dias=90):
        """
        Obtiene estadísticas de correcciones para un campo específico.

        Args:
            campo: Nombre del campo (ej: "cliente.nombre")
            compania: Filtrar por compañía (opcional)
            limite_dias: Días hacia atrás a considerar

        Returns:
            dict: Estadísticas del campo
        """
        from sqlalchemy import func

        fecha_limite = datetime.utcnow() - timedelta(days=limite_dias)

        query = LogCorreccionExtraccion.query.filter(
            LogCorreccionExtraccion.campo == campo,
            LogCorreccionExtraccion.fecha >= fecha_limite
        )

        if compania:
            query = query.filter(LogCorreccionExtraccion.compania == compania)

        total = query.count()

        por_tipo = db.session.query(
            LogCorreccionExtraccion.tipo_cambio,
            func.count(LogCorreccionExtraccion.id)
        ).filter(
            LogCorreccionExtraccion.campo == campo,
            LogCorreccionExtraccion.fecha >= fecha_limite
        ).group_by(LogCorreccionExtraccion.tipo_cambio).all()

        return {
            'campo': campo,
            'total_correcciones': total,
            'por_tipo': dict(por_tipo),
            'periodo_dias': limite_dias
        }

    @staticmethod
    def obtener_campos_problematicos(usuario_id=None, limite=10):
        """
        Obtiene los campos que más correcciones requieren.

        Returns:
            list: Lista de campos ordenados por cantidad de correcciones
        """
        from sqlalchemy import func

        query = db.session.query(
            LogCorreccionExtraccion.campo,
            LogCorreccionExtraccion.compania,
            func.count(LogCorreccionExtraccion.id).label('total')
        )

        if usuario_id:
            query = query.filter(LogCorreccionExtraccion.usuario_id == usuario_id)

        return query.group_by(
            LogCorreccionExtraccion.campo,
            LogCorreccionExtraccion.compania
        ).order_by(
            func.count(LogCorreccionExtraccion.id).desc()
        ).limit(limite).all()

    def __repr__(self):
        return f'<LogCorreccionExtraccion {self.id} - {self.campo} - {self.tipo_cambio}>'
