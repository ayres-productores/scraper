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
    """Obtiene el cipher para encriptar/desencriptar credenciales."""
    key = current_app.config['ENCRYPTION_KEY']
    # Convertir a 32 bytes usando hash
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

    id = db.Column(db.Integer, primary_key=True)
    correo = db.Column(db.String(120), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    contrasena_hash = db.Column(db.String(128), nullable=False)
    rol = db.Column(db.String(20), default='usuario')  # 'admin' o 'usuario'
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
        return self.rol == 'admin'

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
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    correo_gmail = db.Column(db.String(120), nullable=False)
    contrasena_app_encriptada = db.Column(db.Text, nullable=False)
    activa = db.Column(db.Boolean, default=True)
    fecha_agregada = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_escaneo = db.Column(db.DateTime, nullable=True)

    # Relación con escaneos
    escaneos = db.relationship('Escaneo', backref='cuenta_gmail', lazy='dynamic')

    def establecer_contrasena_app(self, contrasena):
        """Encripta y guarda la contraseña de aplicación."""
        cipher = obtener_cipher()
        self.contrasena_app_encriptada = cipher.encrypt(contrasena.encode()).decode()

    def obtener_contrasena_app(self):
        """Desencripta y devuelve la contraseña de aplicación."""
        cipher = obtener_cipher()
        return cipher.decrypt(self.contrasena_app_encriptada.encode()).decode()

    def __repr__(self):
        return f'<CuentaGmail {self.correo_gmail}>'


class Escaneo(db.Model):
    """Modelo para registrar escaneos realizados."""

    __tablename__ = 'escaneos'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    cuenta_gmail_id = db.Column(db.Integer, db.ForeignKey('cuentas_gmail.id'), nullable=True)
    fecha_inicio = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_fin = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(20), default='en_progreso')  # en_progreso, completado, error, cancelado
    correos_escaneados = db.Column(db.Integer, default=0)
    pdfs_descargados = db.Column(db.Integer, default=0)
    palabras_clave = db.Column(db.Text, nullable=True)
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
            # Crear nueva compañía
            # Normalizar nombre: "seguros.mapfre.com" -> "Mapfre"
            partes = dominio.replace('.com', '').replace('.es', '').replace('.net', '').split('.')
            nombre = partes[-1].capitalize() if partes else dominio

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

    def __repr__(self):
        return f'<Compania {self.nombre}>'


class ArchivoDescargado(db.Model):
    """Modelo para registrar archivos PDF descargados."""

    __tablename__ = 'archivos_descargados'

    id = db.Column(db.Integer, primary_key=True)
    escaneo_id = db.Column(db.Integer, db.ForeignKey('escaneos.id'), nullable=False)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    ruta_archivo = db.Column(db.String(500), nullable=False)
    tamano_bytes = db.Column(db.Integer, nullable=True)
    hash_archivo = db.Column(db.String(64), nullable=True)  # SHA-256
    remitente = db.Column(db.String(255), nullable=True)
    asunto = db.Column(db.String(500), nullable=True)
    fecha_correo = db.Column(db.DateTime, nullable=True)
    fecha_descarga = db.Column(db.DateTime, default=datetime.utcnow)

    # Campos para organización por compañía
    compania_id = db.Column(db.Integer, db.ForeignKey('companias.id'), nullable=True)
    nombre_compania_original = db.Column(db.String(255), nullable=True)
    cuenta_origen = db.Column(db.String(120), nullable=True)  # Email de la cuenta Gmail origen

    def __repr__(self):
        return f'<ArchivoDescargado {self.nombre_archivo}>'


class LogActividad(db.Model):
    """Modelo para registrar actividad del sistema (auditoría)."""

    __tablename__ = 'logs_actividad'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    accion = db.Column(db.String(100), nullable=False)
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
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=True)
    telefono_whatsapp = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    documento_identidad = db.Column(db.String(30), nullable=True)
    notas = db.Column(db.Text, nullable=True)
    mensaje_personalizado = db.Column(db.Text, nullable=True)
    usar_mensaje_estandar = db.Column(db.Boolean, default=True)
    activo = db.Column(db.Boolean, default=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_envio = db.Column(db.DateTime, nullable=True)

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
        """Devuelve el teléfono en formato internacional."""
        tel = self.telefono_whatsapp.replace(' ', '').replace('-', '')
        if not tel.startswith('+'):
            tel = '+' + tel
        return tel

    def __repr__(self):
        return f'<Cliente {self.nombre_completo}>'


class PolizaCliente(db.Model):
    """Modelo para asociar pólizas con clientes."""

    __tablename__ = 'polizas_cliente'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    archivo_id = db.Column(db.Integer, db.ForeignKey('archivos_descargados.id'), nullable=True)
    compania_id = db.Column(db.Integer, db.ForeignKey('companias.id'), nullable=True)
    numero_poliza = db.Column(db.String(50), nullable=True)
    tipo_seguro = db.Column(db.String(50), nullable=True)  # auto, vida, hogar, salud, etc.
    fecha_vigencia_desde = db.Column(db.Date, nullable=True)
    fecha_vigencia_hasta = db.Column(db.Date, nullable=True)
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
    estado = db.Column(db.String(20), default='activa')  # activa, vencida, cancelada, en_renovacion, suspendida
    renovacion_automatica = db.Column(db.Boolean, default=False)
    poliza_anterior_id = db.Column(db.Integer, db.ForeignKey('polizas_cliente.id'), nullable=True)
    motivo_cancelacion = db.Column(db.Text, nullable=True)
    fecha_cancelacion = db.Column(db.Date, nullable=True)

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

    # ========== AUDITORÍA ==========
    fecha_ultima_modificacion = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)
    modificado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    # Relaciones
    archivo = db.relationship('ArchivoDescargado', backref='polizas_asignadas')
    compania = db.relationship('Compania', backref='polizas_asignadas')
    envios = db.relationship('EnvioWhatsApp', backref='poliza', lazy='dynamic')
    poliza_anterior = db.relationship('PolizaCliente', remote_side=[id], backref='renovaciones')
    modificado_por = db.relationship('Usuario', foreign_keys=[modificado_por_id])

    TIPOS_SEGURO = [
        ('auto', 'Automóvil'),
        ('moto', 'Motocicleta'),
        ('vida', 'Vida'),
        ('hogar', 'Hogar'),
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
            except:
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
            except:
                return []
        return []

    def establecer_beneficiarios(self, lista_beneficiarios):
        """Guarda los beneficiarios desde una lista."""
        import json
        self.beneficiarios = json.dumps(lista_beneficiarios)

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
            mensaje = mensaje.replace('{compania}', poliza.compania.nombre if poliza.compania else '')
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
        """Registra un correo como procesado."""
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
