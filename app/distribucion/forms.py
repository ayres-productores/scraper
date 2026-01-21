"""
Formularios del módulo de distribución
"""

from flask_wtf import FlaskForm
from wtforms import (StringField, TextAreaField, BooleanField, SelectField,
                     DecimalField, DateField, SubmitField, SelectMultipleField,
                     IntegerField, TimeField, FloatField)
from wtforms.validators import DataRequired, Optional, Length, Regexp, NumberRange
from wtforms.widgets import CheckboxInput, ListWidget


class ClienteForm(FlaskForm):
    """Formulario para crear/editar cliente."""
    nombre = StringField('Nombre', validators=[
        DataRequired(message='El nombre es requerido'),
        Length(max=100)
    ])
    apellido = StringField('Apellido', validators=[
        Optional(),
        Length(max=100)
    ])
    telefono_whatsapp = StringField('Teléfono WhatsApp', validators=[
        DataRequired(message='El teléfono es requerido'),
        Regexp(r'^\+?[0-9\s\-]{8,20}$', message='Formato de teléfono inválido')
    ])
    email = StringField('Email', validators=[
        Optional(),
        Length(max=120)
    ])
    documento_identidad = StringField('Documento de Identidad', validators=[
        Optional(),
        Length(max=30)
    ])
    notas = TextAreaField('Notas', validators=[Optional()])
    usar_mensaje_estandar = BooleanField('Usar mensaje estándar', default=True)
    mensaje_personalizado = TextAreaField('Mensaje personalizado', validators=[Optional()])
    submit = SubmitField('Guardar Cliente')


class AsignarPolizaForm(FlaskForm):
    """Formulario para asignar póliza a cliente."""
    cliente_id = SelectField('Cliente', coerce=int, validators=[
        DataRequired(message='Selecciona un cliente')
    ])
    archivo_id = SelectField('Archivo PDF', coerce=int, validators=[
        DataRequired(message='Selecciona un archivo')
    ])
    numero_poliza = StringField('Número de Póliza', validators=[
        Optional(),
        Length(max=50)
    ])
    tipo_seguro = SelectField('Tipo de Seguro', choices=[
        ('', 'Seleccionar...'),
        ('auto', 'Automóvil'),
        ('vida', 'Vida'),
        ('hogar', 'Hogar'),
        ('salud', 'Salud'),
        ('accidentes', 'Accidentes'),
        ('responsabilidad', 'Responsabilidad Civil'),
        ('comercio', 'Comercio'),
        ('viaje', 'Viaje'),
        ('mascota', 'Mascota'),
        ('otro', 'Otro')
    ], validators=[Optional()])
    fecha_vigencia_desde = DateField('Vigencia Desde', format='%Y-%m-%d', validators=[Optional()])
    fecha_vigencia_hasta = DateField('Vigencia Hasta', format='%Y-%m-%d', validators=[Optional()])
    prima_anual = DecimalField('Prima Anual', places=2, validators=[Optional()])
    notas = TextAreaField('Notas', validators=[Optional()])
    enviar_inmediatamente = BooleanField('Enviar por WhatsApp inmediatamente', default=False)
    submit = SubmitField('Asignar Póliza')


class PlantillaMensajeForm(FlaskForm):
    """Formulario para crear/editar plantilla de mensaje."""
    nombre_plantilla = StringField('Nombre de la Plantilla', validators=[
        DataRequired(message='El nombre es requerido'),
        Length(max=100)
    ])
    mensaje = TextAreaField('Mensaje', validators=[
        DataRequired(message='El mensaje es requerido')
    ])
    es_predeterminada = BooleanField('Usar como plantilla predeterminada', default=False)
    submit = SubmitField('Guardar Plantilla')


class EnvioForm(FlaskForm):
    """Formulario para envío manual."""
    mensaje = TextAreaField('Mensaje', validators=[
        DataRequired(message='El mensaje es requerido')
    ])
    submit = SubmitField('Enviar')


class FiltroClientesForm(FlaskForm):
    """Formulario de filtro para listado de clientes."""
    busqueda = StringField('Buscar', validators=[Optional()])
    solo_activos = BooleanField('Solo activos', default=True)


class EnvioMasivoForm(FlaskForm):
    """Formulario para envío masivo."""
    clientes = SelectMultipleField('Clientes', coerce=int, validators=[
        DataRequired(message='Selecciona al menos un cliente')
    ])
    plantilla_id = SelectField('Plantilla de Mensaje', coerce=int, validators=[
        DataRequired(message='Selecciona una plantilla')
    ])
    submit = SubmitField('Programar Envíos')


# ============================================================================
# FORMULARIOS CRM - GESTIÓN DE PÓLIZAS
# ============================================================================

class PolizaCompletaForm(FlaskForm):
    """Formulario completo para crear/editar póliza con todos los datos."""

    # === DATOS BÁSICOS ===
    cliente_id = SelectField('Cliente', coerce=int, validators=[
        DataRequired(message='Selecciona un cliente')
    ])
    archivo_id = SelectField('Archivo PDF', coerce=int, validators=[Optional()])
    compania_id = SelectField('Compañía', coerce=int, validators=[Optional()])
    numero_poliza = StringField('Número de Póliza', validators=[
        Optional(), Length(max=50)
    ])
    tipo_seguro = SelectField('Tipo de Seguro', choices=[
        ('', 'Seleccionar...'),
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
    ], validators=[Optional()])
    fecha_vigencia_desde = DateField('Vigencia Desde', format='%Y-%m-%d', validators=[Optional()])
    fecha_vigencia_hasta = DateField('Vigencia Hasta', format='%Y-%m-%d', validators=[Optional()])
    prima_anual = DecimalField('Prima Anual', places=2, validators=[Optional()])

    # === DATOS DEL ASEGURADO ===
    asegurado_nombre = StringField('Nombre del Asegurado', validators=[
        Optional(), Length(max=150)
    ])
    asegurado_documento = StringField('Documento', validators=[
        Optional(), Length(max=30)
    ])
    asegurado_direccion = StringField('Dirección', validators=[
        Optional(), Length(max=255)
    ])
    asegurado_telefono = StringField('Teléfono', validators=[
        Optional(), Length(max=30)
    ])
    asegurado_email = StringField('Email', validators=[
        Optional(), Length(max=120)
    ])

    # === BIEN ASEGURADO ===
    bien_asegurado_tipo = SelectField('Tipo de Bien', choices=[
        ('', 'Seleccionar...'),
        ('vehiculo', 'Vehículo'),
        ('inmueble', 'Inmueble'),
        ('persona', 'Persona'),
        ('maquinaria', 'Maquinaria'),
        ('mercaderia', 'Mercadería'),
        ('otro', 'Otro')
    ], validators=[Optional()])
    bien_asegurado_descripcion = TextAreaField('Descripción del Bien', validators=[Optional()])
    bien_asegurado_valor = DecimalField('Valor del Bien', places=2, validators=[Optional()])

    # === DATOS DE VEHÍCULO ===
    vehiculo_marca = StringField('Marca', validators=[Optional(), Length(max=50)])
    vehiculo_modelo = StringField('Modelo', validators=[Optional(), Length(max=50)])
    vehiculo_anio = IntegerField('Año', validators=[Optional(), NumberRange(min=1900, max=2100)])
    vehiculo_patente = StringField('Patente/Placa', validators=[Optional(), Length(max=20)])
    vehiculo_chasis = StringField('Número de Chasis', validators=[Optional(), Length(max=50)])
    vehiculo_motor = StringField('Número de Motor', validators=[Optional(), Length(max=50)])
    vehiculo_color = StringField('Color', validators=[Optional(), Length(max=30)])
    vehiculo_uso = SelectField('Uso del Vehículo', choices=[
        ('', 'Seleccionar...'),
        ('particular', 'Particular'),
        ('comercial', 'Comercial'),
        ('taxi', 'Taxi/Remis'),
        ('transporte', 'Transporte de Carga'),
        ('otro', 'Otro')
    ], validators=[Optional()])

    # === DATOS DE INMUEBLE ===
    inmueble_direccion = StringField('Dirección del Inmueble', validators=[Optional(), Length(max=255)])
    inmueble_tipo = SelectField('Tipo de Inmueble', choices=[
        ('', 'Seleccionar...'),
        ('casa', 'Casa'),
        ('departamento', 'Departamento'),
        ('ph', 'PH'),
        ('local', 'Local Comercial'),
        ('oficina', 'Oficina'),
        ('galpon', 'Galpón/Depósito'),
        ('terreno', 'Terreno'),
        ('otro', 'Otro')
    ], validators=[Optional()])
    inmueble_superficie = DecimalField('Superficie (m²)', places=2, validators=[Optional()])
    inmueble_construccion = SelectField('Tipo de Construcción', choices=[
        ('', 'Seleccionar...'),
        ('material', 'Material/Ladrillo'),
        ('mixta', 'Mixta'),
        ('madera', 'Madera'),
        ('prefabricada', 'Prefabricada'),
        ('otro', 'Otro')
    ], validators=[Optional()])

    # === COBERTURAS Y SUMAS ===
    suma_asegurada = DecimalField('Suma Asegurada', places=2, validators=[Optional()])
    deducible = DecimalField('Deducible', places=2, validators=[Optional()])
    franquicia = DecimalField('Franquicia', places=2, validators=[Optional()])
    coberturas_texto = TextAreaField('Coberturas (una por línea)', validators=[Optional()])

    # === BENEFICIARIOS (vida) ===
    beneficiarios_texto = TextAreaField('Beneficiarios (nombre - porcentaje, uno por línea)', validators=[Optional()])

    # === ESTADO Y RENOVACIÓN ===
    estado = SelectField('Estado', choices=[
        ('activa', 'Activa'),
        ('vencida', 'Vencida'),
        ('cancelada', 'Cancelada'),
        ('en_renovacion', 'En Renovación'),
        ('suspendida', 'Suspendida')
    ], default='activa')
    renovacion_automatica = BooleanField('Renovación Automática', default=False)

    # === FORMA DE PAGO ===
    forma_pago = SelectField('Forma de Pago', choices=[
        ('', 'Seleccionar...'),
        ('anual', 'Anual'),
        ('semestral', 'Semestral'),
        ('trimestral', 'Trimestral'),
        ('mensual', 'Mensual'),
        ('unico', 'Pago Único')
    ], validators=[Optional()])
    cantidad_cuotas = IntegerField('Cantidad de Cuotas', validators=[Optional()])
    dia_vencimiento_cuota = IntegerField('Día de Vencimiento', validators=[
        Optional(), NumberRange(min=1, max=31)
    ])
    medio_pago = SelectField('Medio de Pago', choices=[
        ('', 'Seleccionar...'),
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
        ('debito_auto', 'Débito Automático'),
        ('tarjeta', 'Tarjeta')
    ], validators=[Optional()])

    # === CONTACTO PRODUCTOR ===
    productor_nombre = StringField('Nombre del Productor', validators=[Optional(), Length(max=100)])
    productor_telefono = StringField('Teléfono del Productor', validators=[Optional(), Length(max=30)])
    productor_email = StringField('Email del Productor', validators=[Optional(), Length(max=120)])
    sucursal = StringField('Sucursal', validators=[Optional(), Length(max=100)])

    # === NOTAS ===
    notas = TextAreaField('Notas', validators=[Optional()])

    submit = SubmitField('Guardar Póliza')


class InteraccionForm(FlaskForm):
    """Formulario para registrar interacciones con clientes."""

    tipo = SelectField('Tipo de Interacción', choices=[
        ('llamada', 'Llamada Telefónica'),
        ('email', 'Correo Electrónico'),
        ('whatsapp', 'WhatsApp'),
        ('reunion', 'Reunión'),
        ('visita', 'Visita'),
        ('nota', 'Nota Interna')
    ], validators=[DataRequired(message='Selecciona un tipo')])

    direccion = SelectField('Dirección', choices=[
        ('', 'Seleccionar...'),
        ('entrante', 'Entrante'),
        ('saliente', 'Saliente')
    ], validators=[Optional()])

    poliza_cliente_id = SelectField('Póliza Relacionada', coerce=int, validators=[Optional()])

    asunto = StringField('Asunto', validators=[Optional(), Length(max=200)])
    descripcion = TextAreaField('Descripción', validators=[
        DataRequired(message='La descripción es requerida')
    ])
    duracion_minutos = IntegerField('Duración (minutos)', validators=[Optional()])

    requiere_seguimiento = BooleanField('Requiere Seguimiento', default=False)
    fecha_seguimiento = DateField('Fecha de Seguimiento', format='%Y-%m-%d', validators=[Optional()])

    submit = SubmitField('Registrar Interacción')


class PagoForm(FlaskForm):
    """Formulario para registrar pagos."""

    numero_cuota = IntegerField('Número de Cuota', validators=[Optional()])
    monto = DecimalField('Monto', places=2, validators=[
        DataRequired(message='El monto es requerido')
    ])
    fecha_vencimiento = DateField('Fecha de Vencimiento', format='%Y-%m-%d', validators=[
        DataRequired(message='La fecha de vencimiento es requerida')
    ])
    fecha_pago = DateField('Fecha de Pago', format='%Y-%m-%d', validators=[Optional()])

    estado = SelectField('Estado', choices=[
        ('pendiente', 'Pendiente'),
        ('pagado', 'Pagado'),
        ('vencido', 'Vencido'),
        ('anulado', 'Anulado')
    ], default='pendiente')

    metodo_pago = SelectField('Método de Pago', choices=[
        ('', 'Seleccionar...'),
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia Bancaria'),
        ('tarjeta', 'Tarjeta de Crédito/Débito'),
        ('debito_auto', 'Débito Automático'),
        ('cheque', 'Cheque'),
        ('otro', 'Otro')
    ], validators=[Optional()])

    comprobante = StringField('Comprobante/Referencia', validators=[Optional(), Length(max=100)])
    notas = TextAreaField('Notas', validators=[Optional()])

    submit = SubmitField('Guardar Pago')


class GenerarCuotasForm(FlaskForm):
    """Formulario para generar cuotas automáticamente."""

    cantidad_cuotas = IntegerField('Cantidad de Cuotas', validators=[
        DataRequired(message='Ingresa la cantidad de cuotas'),
        NumberRange(min=1, max=24, message='Entre 1 y 24 cuotas')
    ])
    monto_cuota = DecimalField('Monto por Cuota', places=2, validators=[
        DataRequired(message='El monto es requerido')
    ])
    fecha_primera_cuota = DateField('Fecha Primera Cuota', format='%Y-%m-%d', validators=[
        DataRequired(message='La fecha es requerida')
    ])
    periodicidad = SelectField('Periodicidad', choices=[
        ('mensual', 'Mensual'),
        ('bimestral', 'Bimestral'),
        ('trimestral', 'Trimestral'),
        ('semestral', 'Semestral'),
        ('anual', 'Anual')
    ], default='mensual')

    submit = SubmitField('Generar Cuotas')


class SiniestroForm(FlaskForm):
    """Formulario para registrar siniestros."""

    numero_siniestro = StringField('Número de Siniestro Interno', validators=[
        Optional(), Length(max=50)
    ])
    numero_siniestro_compania = StringField('Número de Siniestro (Compañía)', validators=[
        Optional(), Length(max=50)
    ])

    fecha_ocurrencia = DateField('Fecha de Ocurrencia', format='%Y-%m-%d', validators=[
        DataRequired(message='La fecha de ocurrencia es requerida')
    ])
    fecha_denuncia = DateField('Fecha de Denuncia', format='%Y-%m-%d', validators=[Optional()])

    tipo_siniestro = SelectField('Tipo de Siniestro', choices=[
        ('', 'Seleccionar...'),
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
    ], validators=[Optional()])

    descripcion = TextAreaField('Descripción del Siniestro', validators=[
        DataRequired(message='La descripción es requerida')
    ])
    ubicacion = StringField('Ubicación', validators=[Optional(), Length(max=255)])

    hay_lesionados = BooleanField('¿Hay Lesionados?', default=False)
    descripcion_lesiones = TextAreaField('Descripción de Lesiones', validators=[Optional()])
    terceros_texto = TextAreaField('Terceros Involucrados (nombre - teléfono, uno por línea)', validators=[Optional()])

    monto_reclamado = DecimalField('Monto Reclamado', places=2, validators=[Optional()])

    estado = SelectField('Estado', choices=[
        ('denunciado', 'Denunciado'),
        ('en_proceso', 'En Proceso'),
        ('documentacion', 'Esperando Documentación'),
        ('peritaje', 'En Peritaje'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado'),
        ('pagado', 'Pagado'),
        ('cerrado', 'Cerrado')
    ], default='denunciado')

    notas = TextAreaField('Notas', validators=[Optional()])

    submit = SubmitField('Guardar Siniestro')


class FiltroAlertasForm(FlaskForm):
    """Formulario de filtro para alertas."""

    tipo = SelectField('Tipo', choices=[
        ('', 'Todos'),
        ('vencimiento_poliza', 'Vencimiento de Póliza'),
        ('vencimiento_pago', 'Vencimiento de Pago'),
        ('renovacion', 'Renovación'),
        ('seguimiento', 'Seguimiento')
    ], validators=[Optional()])

    estado = SelectField('Estado', choices=[
        ('', 'Todos'),
        ('pendiente', 'Pendiente'),
        ('notificada', 'Notificada'),
        ('resuelta', 'Resuelta')
    ], validators=[Optional()])

    prioridad = SelectField('Prioridad', choices=[
        ('', 'Todas'),
        ('alta', 'Alta'),
        ('media', 'Media'),
        ('baja', 'Baja')
    ], validators=[Optional()])


class ConfiguracionAlertasForm(FlaskForm):
    """Formulario para configurar alertas automáticas."""

    dias_alerta_poliza_1 = IntegerField('Primera alerta (días antes)', default=30, validators=[
        NumberRange(min=1, max=90)
    ])
    dias_alerta_poliza_2 = IntegerField('Segunda alerta (días antes)', default=15, validators=[
        NumberRange(min=1, max=60)
    ])
    dias_alerta_poliza_3 = IntegerField('Tercera alerta (días antes)', default=7, validators=[
        NumberRange(min=1, max=30)
    ])

    alertar_pagos_vencidos = BooleanField('Alertar pagos vencidos', default=True)
    dias_alerta_pago = IntegerField('Días antes del vencimiento de pago', default=5, validators=[
        NumberRange(min=1, max=30)
    ])

    submit = SubmitField('Guardar Configuración')
