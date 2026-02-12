"""
Extractor de datos de polizas desde archivos PDF.
Utiliza PyMuPDF para extraer texto y patrones regex para identificar datos.
Version mejorada con patrones especificos por compania aseguradora argentina.
"""

import json
import logging
import re
import fitz  # PyMuPDF
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger('app.extractor.pdf_parser')


class ExtractorDatosPoliza:
    """Extrae datos estructurados de PDFs de polizas de seguros."""

    # Patrones genericos para datos comunes
    PATRONES = {
        # Numeros de poliza (varios formatos)
        'numero_poliza': [
            r'[Pp][oó]liza\s*(?:[Nn][oº°]?\.?\s*)?:?\s*([A-Z0-9][\w\-\/\.]+)',
            r'[Nn][oº°]?\s*(?:de\s*)?[Pp][oó]liza:?\s*([A-Z0-9][\w\-\/\.]+)',
            r'[Cc]ontrato\s*[Nn][oº°]?\.?:?\s*([A-Z0-9][\w\-\/\.]+)',
            r'[Cc]ertificado\s*[Nn][oº°]?\.?:?\s*([A-Z0-9][\w\-\/\.]+)',
            r'[Pp]ropuesta\s*[Nn][oº°]?\.?:?\s*([A-Z0-9][\w\-\/\.]+)',
            r'[Pp][oó]liza/[Cc]ertificado:?\s*([A-Z0-9][\w\-\/\.]+)',
        ],

        # Fechas de vigencia
        'fecha_desde': [
            r'[Vv]igencia\s*[Dd]esde:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ii]nicio\s*(?:de\s*)?[Vv]igencia:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ff]echa\s*[Ii]nicio:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Dd]esde\s*(?:el)?:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Vv]igente\s*[Dd]esde:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Pp]er[ií]odo\s*[Dd]esde:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Dd]esde:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\s*[Hh]asta',
            r'[Vv]igencia:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\s*(?:al?|hasta)',
        ],
        'fecha_hasta': [
            r'[Vv]igencia\s*[Hh]asta:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ff]in\s*(?:de\s*)?[Vv]igencia:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ff]echa\s*[Ff]in:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Hh]asta\s*(?:el)?:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Vv]encimiento:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Vv]ence:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ff]echa\s*[Vv]encimiento:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Hh]asta:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'(?:al?|hasta)\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        ],

        # Prima y costos
        'prima': [
            r'[Pp]rima\s*[Tt]otal:?\s*\$?\s*([\d\.,]+)',
            r'[Pp]rima\s*[Aa]nual:?\s*\$?\s*([\d\.,]+)',
            r'[Pp]remio\s*[Tt]otal:?\s*\$?\s*([\d\.,]+)',
            r'[Pp]remio:?\s*\$?\s*([\d\.,]+)',
            r'[Tt]otal\s*a\s*[Pp]agar:?\s*\$?\s*([\d\.,]+)',
            r'[Cc]osto\s*[Tt]otal:?\s*\$?\s*([\d\.,]+)',
            r'[Pp]rima\s*[Nn]eta:?\s*\$?\s*([\d\.,]+)',
            r'[Ii]mporte\s*[Tt]otal:?\s*\$?\s*([\d\.,]+)',
            r'[Tt]otal\s*[Pp]rima:?\s*\$?\s*([\d\.,]+)',
            r'[Pp]recio\s*[Ff]inal:?\s*\$?\s*([\d\.,]+)',
        ],

        # Suma asegurada
        'suma_asegurada': [
            r'[Ss]uma\s*[Aa]segurada:?\s*\$?\s*([\d\.,]+)',
            r'[Cc]apital\s*[Aa]segurado:?\s*\$?\s*([\d\.,]+)',
            r'[Mm]onto\s*[Aa]segurado:?\s*\$?\s*([\d\.,]+)',
            r'[Vv]alor\s*[Aa]segurado:?\s*\$?\s*([\d\.,]+)',
            r'[Ss]uma\s*[Tt]otal:?\s*\$?\s*([\d\.,]+)',
            r'[Cc]obertura\s*[Mm][aá]xima:?\s*\$?\s*([\d\.,]+)',
        ],

        # Deducible / Franquicia
        'deducible': [
            r'[Dd]educible:?\s*\$?\s*([\d\.,]+)',
            r'[Ff]ranquicia:?\s*\$?\s*([\d\.,]+)',
            r'[Dd]escubierto:?\s*\$?\s*([\d\.,]+)',
            r'[Dd]educible\s*[Ff]ijo:?\s*\$?\s*([\d\.,]+)',
        ],

        # Datos del asegurado
        'asegurado_nombre': [
            r'[Aa]segurado:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|DNI|CUIT|CUIL|Documento)',
            r'[Tt]omador:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|DNI|CUIT|CUIL|Documento)',
            r'[Cc]ontratante:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|DNI|CUIT|CUIL|Documento)',
            r'[Nn]ombre\s*(?:y\s*[Aa]pellido)?:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|DNI)',
            r'[Rr]az[oó]n\s*[Ss]ocial:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.0-9]+?)(?:\n|CUIT)',
            r'[Cc]liente:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|DNI|Tel)',
        ],
        'asegurado_documento': [
            # DNI con formato XX.XXX.XXX o X.XXX.XXX (con puntos)
            r'[Dd]\.?[Nn]\.?[Ii]\.?:?\s*[Nn]?[oº°]?:?\s*(\d{1,2}\.\d{3}\.\d{3})',
            # DNI sin puntos (7-8 digitos)
            r'[Dd]\.?[Nn]\.?[Ii]\.?:?\s*[Nn]?[oº°]?:?\s*(\d{7,8})(?!\d)',
            # CUIT/CUIL formato XX-XXXXXXXX-X
            r'[Cc]\.?[Uu]\.?[Ii]\.?[Tt]\.?:?\s*(\d{2}[\-\s]?\d{8}[\-\s]?\d{1})',
            r'[Cc]\.?[Uu]\.?[Ii]\.?[Ll]\.?:?\s*(\d{2}[\-\s]?\d{8}[\-\s]?\d{1})',
            # CUIT sin guiones (11 digitos)
            r'[Cc]\.?[Uu]\.?[Ii]\.?[Tt]\.?:?\s*(\d{11})(?!\d)',
            # Documento generico
            r'[Dd]ocumento:?\s*(\d{7,11})',
            r'[Nn][oº°]?\s*[Dd]ocumento:?\s*(\d{7,11})',
            r'[Dd][Nn][Ii]/[Cc][Uu][Ii][Tt]:?\s*(\d{7,11})',
            # DNI cerca de palabras clave (Asegurado, Tomador)
            r'(?:[Aa]segurado|[Tt]omador|[Cc]ontratante)[:\s]+[^\d]*?[Dd]\.?[Nn]\.?[Ii]\.?:?\s*(\d{1,2}[\.\s]?\d{3}[\.\s]?\d{3})',
            r'(?:[Aa]segurado|[Tt]omador|[Cc]ontratante)[:\s]+[^\d]*?(\d{2}\.\d{3}\.\d{3})',
            # Numero suelto de 7-8 digitos despues de nombre (patron comun)
            r'(?:[Aa]segurado|[Tt]omador)[:\s]+[A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+\s+(\d{7,8})(?!\d)',
        ],
        'asegurado_direccion': [
            r'[Dd]omicilio:?\s*([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|CP|Tel|C\.P)',
            r'[Dd]irecci[oó]n:?\s*([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|CP|Tel|C\.P)',
            r'[Dd]omicilio\s*[Rr]eal:?\s*([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|CP)',
            r'[Uu]bicaci[oó]n\s*[Rr]iesgo:?\s*([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|CP)',
        ],
        'asegurado_telefono': [
            r'[Tt]el[eé]fono:?\s*([\d\s\-\(\)]+)',
            r'[Tt]el:?\s*([\d\s\-\(\)]+)',
            r'[Cc]elular:?\s*([\d\s\-\(\)]+)',
            r'[Mm][oó]vil:?\s*([\d\s\-\(\)]+)',
        ],
        'asegurado_email': [
            r'[Ee][\-]?[Mm]ail:?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'[Cc]orreo:?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        ],

        # Vehiculo
        'vehiculo_marca': [
            r'[Mm]arca:?\s*([A-Za-z0-9\-]+)',
            r'[Mm]arca\s*[Vv]eh[ií]culo:?\s*([A-Za-z0-9\-]+)',
        ],
        'vehiculo_modelo': [
            r'[Mm]odelo:?\s*([A-Za-z0-9\s\-\.]+?)(?:\n|Año|Color|Patente|Dominio)',
            r'[Vv]ersi[oó]n:?\s*([A-Za-z0-9\s\-\.]+?)(?:\n|Año)',
            r'[Dd]escripci[oó]n:?\s*([A-Za-z0-9\s\-\.]+?)(?:\n|Año|Motor)',
        ],
        'vehiculo_anio': [
            r'[Aa][ñn]o:?\s*((?:19|20)\d{2})',
            r'[Aa][ñn]o\s*[Ff]ab(?:ricaci[oó]n)?:?\s*((?:19|20)\d{2})',
            r'[Aa][ñn]o\s*[Mm]odelo:?\s*((?:19|20)\d{2})',
            r'[Mm]odelo\s*[Aa][ñn]o:?\s*((?:19|20)\d{2})',
            r'[Ff]abricaci[oó]n:?\s*((?:19|20)\d{2})',
        ],
        'vehiculo_patente': [
            r'[Pp]atente:?\s*([A-Z]{2,3}[\s\-]?\d{3}[\s\-]?[A-Z]{0,2})',
            r'[Dd]ominio:?\s*([A-Z]{2,3}[\s\-]?\d{3}[\s\-]?[A-Z]{0,2})',
            r'[Pp]laca:?\s*([A-Z]{2,3}[\s\-]?\d{3}[\s\-]?[A-Z]{0,2})',
            r'[Mm]atr[ií]cula:?\s*([A-Z]{2,3}[\s\-]?\d{3}[\s\-]?[A-Z]{0,2})',
            # Patente nueva (AA 123 BB)
            r'([A-Z]{2}[\s\-]?\d{3}[\s\-]?[A-Z]{2})',
            # Patente vieja (ABC 123)
            r'([A-Z]{3}[\s\-]?\d{3})',
        ],
        'vehiculo_chasis': [
            r'[Cc]hasis:?\s*([A-Z0-9]{17})',
            r'[Vv][Ii][Nn]:?\s*([A-Z0-9]{17})',
            r'[Nn][oº°]?\s*[Cc]hasis:?\s*([A-Z0-9]{17})',
            r'[Cc]uadro:?\s*([A-Z0-9]{17})',
        ],
        'vehiculo_motor': [
            r'[Mm]otor:?\s*([A-Z0-9\-]{5,20})',
            r'[Nn][oº°]?\s*[Mm]otor:?\s*([A-Z0-9\-]{5,20})',
        ],
        'vehiculo_color': [
            r'[Cc]olor:?\s*([A-Za-zÁÉÍÓÚáéíóú]+)',
        ],
        'vehiculo_uso': [
            r'[Uu]so:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+?)(?:\n|$)',
            r'[Dd]estino:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+?)(?:\n|$)',
            r'[Tt]ipo\s*[Uu]so:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+?)(?:\n|$)',
        ],

        # Inmueble
        'inmueble_direccion': [
            r'[Uu]bicaci[oó]n\s*[Rr]iesgo:?\s*([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|CP)',
            r'[Dd]irecci[oó]n\s*[Ii]nmueble:?\s*([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|CP)',
            r'[Bb]ien\s*[Uu]bicado:?\s*([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|CP)',
        ],
        'inmueble_tipo': [
            r'[Tt]ipo\s*[Ii]nmueble:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+)',
            r'[Tt]ipo\s*[Vv]ivienda:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+)',
            r'[Cc]aracter[ií]stica:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+)',
        ],
        'inmueble_superficie': [
            r'[Ss]uperficie:?\s*(\d+[\.,]?\d*)\s*(?:m2|m²|mts)',
            r'[Mm]etros\s*[Cc]uadrados:?\s*(\d+[\.,]?\d*)',
            r'[Mm]2:?\s*(\d+[\.,]?\d*)',
        ],

        # Productor/Agente
        'productor_nombre': [
            r'[Pp]roductor:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|Mat|Tel|$)',
            r'[Aa]gente:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|Mat|Tel|$)',
            r'[Aa]sesor:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|Mat|Tel|$)',
            r'[Oo]rganizador:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s,\.]+?)(?:\n|Mat|$)',
        ],
        'productor_matricula': [
            r'[Mm]atr[ií]cula:?\s*(\d+)',
            r'[Mm]at\.?:?\s*(\d+)',
            r'[Nn][oº°]?\s*[Mm]atr[ií]cula:?\s*(\d+)',
        ],

        # Forma de pago
        'forma_pago': [
            r'[Ff]orma\s*[Pp]ago:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+?)(?:\n|$)',
            r'[Mm]odalidad\s*[Pp]ago:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+?)(?:\n|$)',
            r'[Cc]ondici[oó]n\s*[Pp]ago:?\s*([A-Za-zÁÉÍÓÚáéíóú\s]+?)(?:\n|$)',
        ],
        'cantidad_cuotas': [
            r'(\d+)\s*[Cc]uotas?',
            r'[Cc]uotas?:?\s*(\d+)',
            r'[Ee]n\s*(\d+)\s*pagos?',
            r'[Cc]antidad\s*[Cc]uotas?:?\s*(\d+)',
        ],

        # Coberturas (lista)
        'coberturas': [
            r'[Cc]oberturas?:?\s*([\s\S]+?)(?:\n\n|Prima|Suma|Deducible|$)',
        ],
    }

    # Companias conocidas y sus patrones especificos
    COMPANIAS = {
        'mapfre': {
            'patrones_nombre': ['mapfre', 'MAPFRE'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{4}[\-\/]\d+)',
            'nombre_formal': 'Mapfre Argentina',
        },
        'la_caja': {
            'patrones_nombre': ['la caja', 'LA CAJA', 'caja seguros', 'lacaja'],
            'patron_poliza': r'[Pp][oó]liza\s*[Nn][oº°]?\s*:?\s*(\d+)',
            'nombre_formal': 'La Caja Seguros',
        },
        'federacion_patronal': {
            'patrones_nombre': ['federacion patronal', 'FEDERACION PATRONAL', 'fed. patronal', 'fedpat'],
            'patron_poliza': r'[Pp][oó]liza:?\s*([A-Z]?\d{6,})',
            'nombre_formal': 'Federación Patronal Seguros',
        },
        'sancor': {
            'patrones_nombre': ['sancor', 'SANCOR'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{7,})',
            'nombre_formal': 'Sancor Seguros',
        },
        'allianz': {
            'patrones_nombre': ['allianz', 'ALLIANZ'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{10,})',
            'nombre_formal': 'Allianz Argentina',
        },
        'zurich': {
            'patrones_nombre': ['zurich', 'ZURICH'],
            'patron_poliza': r'[Pp][oó]liza:?\s*([A-Z0-9]{8,})',
            'nombre_formal': 'Zurich Argentina',
        },
        'sura': {
            'patrones_nombre': ['sura', 'SURA', 'royal & sun', 'rsa'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{8,})',
            'nombre_formal': 'Seguros SURA',
        },
        'la_segunda': {
            'patrones_nombre': ['la segunda', 'LA SEGUNDA', 'lasegunda'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
            'nombre_formal': 'La Segunda Seguros',
        },
        'provincia': {
            'patrones_nombre': ['provincia seguros', 'seguros provincia', 'provinciaseguros.com'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
            'nombre_formal': 'Provincia Seguros',
        },
        'rivadavia': {
            'patrones_nombre': ['rivadavia', 'RIVADAVIA'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
            'nombre_formal': 'Rivadavia Seguros',
        },
        'mercantil_andina': {
            'patrones_nombre': ['mercantil andina', 'MERCANTIL ANDINA', 'la mercantil', 'lamercantil'],
            'patron_poliza': r'[Pp][oó]liza\s*(?:N[°º]?|Nro\.?)?\s*:?\s*(\d{9,12})',
            'nombre_formal': 'Compañía de Seguros La Mercantil Andina S.A.',
            'extraccion_especifica': True,
        },
        'san_cristobal': {
            'patrones_nombre': ['san cristobal', 'SAN CRISTOBAL', 'san cristóbal'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
            'nombre_formal': 'San Cristóbal Seguros',
        },
        'seguros_bernardino': {
            'patrones_nombre': ['bernardino', 'BERNARDINO', 'bernardino rivadavia'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{5,})',
            'nombre_formal': 'Bernardino Rivadavia Seguros',
        },
        'integrity': {
            'patrones_nombre': ['integrity', 'INTEGRITY'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
            'nombre_formal': 'Integrity Seguros',
        },
        'triunfo': {
            'patrones_nombre': ['triunfo', 'TRIUNFO'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
            'nombre_formal': 'Triunfo Seguros',
        },
        'experta': {
            'patrones_nombre': ['experta', 'EXPERTA'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
            'nombre_formal': 'Experta Seguros',
        },
        'orbis': {
            'patrones_nombre': ['orbis', 'ORBIS'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
            'nombre_formal': 'Orbis Seguros',
        },
        'liderar': {
            'patrones_nombre': ['liderar', 'LIDERAR', 'liderarseguros'],
            'patron_poliza': r'(\d{9})\s*/\s*\d{6}',
            'nombre_formal': 'Liderar Compañía General de Seguros S.A.',
            'extraccion_especifica': True,
        },
        'berkley': {
            'patrones_nombre': ['berkley', 'BERKLEY', 'berkley international'],
            'patron_poliza': r'(?:POLIZA\s*\n.*?\n\s*)?(\d)\s*-\s*(\d{6,8})',
            'nombre_formal': 'Berkley International Seguros S.A.',
            'extraccion_especifica': True,
        },
        'rio_uruguay': {
            'patrones_nombre': ['rio uruguay', 'RIO URUGUAY', 'rus ', 'riouruguay', 'r.u.s'],
            'patron_poliza': r'(\d{1,2}-\d{7,8})',  # Formato: 4-12597560
            'nombre_formal': 'Río Uruguay Cooperativa de Seguros Ltda.',
            'extraccion_especifica': True,
        },
    }

    # Tipos de seguro detectables
    TIPOS_SEGURO = {
        'auto': ['automotor', 'automóvil', 'automovil', 'vehiculo', 'vehículo', 'auto ', 'carro', 'automotores'],
        'moto': ['motocicleta', 'moto ', 'ciclomotor', 'motovehiculo'],
        'incendio': ['incendio', 'riesgo de incendio', 'cobertura incendio', 'todo riesgo incendio'],
        'hogar': ['hogar', 'vivienda', 'casa ', 'departamento', 'domicilio', 'combinado familiar'],
        'vida': ['vida', 'fallecimiento', 'muerte', 'sepelio', 'vida individual', 'vida colectivo'],
        'salud': ['salud', 'medico', 'médico', 'hospitalario', 'cobertura medica', 'asistencia medica'],
        'accidentes': ['accidentes personales', 'ap ', 'accidente personal', 'acc. personales'],
        'responsabilidad_civil': ['responsabilidad civil', 'rc ', 'terceros completo', 'rc profesional'],
        'comercio': ['comercio', 'negocio', 'local comercial', 'pyme', 'integral comercio'],
        'consorcio': ['consorcio', 'edificio', 'propiedad horizontal', 'consorcios'],
        'transporte': ['transporte', 'carga', 'mercaderia', 'mercadería', 'flete', 'transporte de carga'],
        'caucion': ['caucion', 'caución', 'fianza', 'garantia', 'garantía'],
        'art': ['art ', 'riesgos del trabajo', 'riesgos trabajo', 'accidentes laborales'],
        'tecnico': ['todo riesgo', 'equipo electronico', 'electrónico', 'rotura de maquinaria'],
        'agro': ['agropecuario', 'rural', 'cosecha', 'ganado', 'agricola', 'agrícola'],
    }

    def __init__(self):
        self.texto_completo = ""
        self.texto_por_pagina = []
        self.datos_extraidos = {}
        self.confianza = 0.0
        self.compania_detectada = None
        self.campos_encontrados = []
        self.campos_no_encontrados = []

    def extraer_texto_pdf(self, ruta_pdf):
        """Extrae todo el texto de un archivo PDF."""
        try:
            doc = fitz.open(ruta_pdf)
            texto = ""
            self.texto_por_pagina = []

            for pagina in doc:
                texto_pagina = pagina.get_text()
                self.texto_por_pagina.append(texto_pagina)
                texto += texto_pagina + "\n"

            doc.close()
            self.texto_completo = texto
            return texto
        except Exception as e:
            logger.warning(f"Error al leer PDF {ruta_pdf}: {e}")
            return ""

    def detectar_compania(self, texto=None):
        """Detecta la compania aseguradora del texto.

        Estrategia de detección en orden de prioridad:
        1. URLs y emails de la compañía (muy específicos)
        2. Nombres completos con "seguros" o "compañía"
        3. Patrones con word boundaries para evitar falsos positivos
        """
        if texto is None:
            texto = self.texto_completo

        texto_lower = texto.lower()

        # Patrones que son nombres de calles comunes (excluir)
        calles_comunes = ['rivadavia', 'san martin', 'belgrano', 'mitre', 'sarmiento']

        # FASE 1: Buscar patrones muy específicos (URLs, emails, nombres completos)
        patrones_especificos = [
            ('liderar', r'liderarseguros\.com|liderar\s+c[ioí]a|liderar\s+compa[ñn][ií]a'),
            ('mapfre', r'mapfre\.com|mapfre\s+seguros|mapfre\s+argentina'),
            ('la_caja', r'lacaja\.com|la\s+caja\s+seguros'),
            ('sancor', r'sancorseguros\.com|sancor\s+seguros'),
            ('allianz', r'allianz\.com|allianz\s+argentina'),
            ('zurich', r'zurich\.com|zurich\s+argentina|zurich\s+seguros'),
            ('sura', r'segurossura\.com|sura\s+seguros'),
            ('la_segunda', r'lasegunda\.com|la\s+segunda\s+seguros'),
            ('mercantil_andina', r'mercantil\s*andina|lamercantil'),
            ('san_cristobal', r'san\s*crist[oó]bal\s+seguros'),
            ('federacion_patronal', r'federaci[oó]n\s+patronal|fedpat'),
            ('provincia', r'provinciaseguros\.com|provincia\s+seguros'),
            ('berkley', r'berkley\s+international|berkley\s+seguros'),
            ('rio_uruguay', r'rio\s*uruguay|r\.u\.s'),
        ]

        for nombre_clave, patron in patrones_especificos:
            if re.search(patron, texto_lower):
                self.compania_detectada = nombre_clave
                return nombre_clave

        # FASE 2: Buscar patrones del diccionario con word boundaries
        for nombre_clave, config in self.COMPANIAS.items():
            for patron in config['patrones_nombre']:
                patron_lower = patron.lower()

                # Saltar si es un nombre de calle común (evitar falsos positivos)
                if patron_lower in calles_comunes:
                    # Solo aceptar si aparece con "seguros" cerca
                    if not re.search(patron_lower + r'.{0,20}seguros', texto_lower):
                        continue

                # Usar word boundary para todos los patrones
                regex_patron = r'\b' + re.escape(patron_lower) + r'\b'
                if re.search(regex_patron, texto_lower):
                    self.compania_detectada = nombre_clave
                    return nombre_clave

        return None

    def obtener_nombre_compania_formal(self):
        """Retorna el nombre formal de la compania detectada."""
        if self.compania_detectada and self.compania_detectada in self.COMPANIAS:
            return self.COMPANIAS[self.compania_detectada].get('nombre_formal', self.compania_detectada)
        return None

    def _buscar_patron(self, patrones, texto=None, limpiar=True):
        """Busca el primer match de una lista de patrones."""
        if texto is None:
            texto = self.texto_completo

        for patron in patrones:
            match = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
            if match:
                resultado = match.group(1).strip()
                if limpiar:
                    # Limpiar espacios multiples y saltos de linea
                    resultado = ' '.join(resultado.split())
                return resultado
        return None

    def _buscar_todos_patrones(self, patrones, texto=None):
        """Busca todos los matches de una lista de patrones."""
        if texto is None:
            texto = self.texto_completo

        resultados = []
        for patron in patrones:
            matches = re.findall(patron, texto, re.IGNORECASE | re.MULTILINE)
            resultados.extend(matches)
        return list(set(resultados))  # Eliminar duplicados

    def _parsear_fecha(self, texto_fecha):
        """Convierte texto de fecha a objeto date."""
        if not texto_fecha:
            return None

        # Limpiar el texto
        texto_fecha = texto_fecha.strip()

        formatos = [
            '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y',
            '%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d', '%Y/%m/%d'
        ]
        for fmt in formatos:
            try:
                return datetime.strptime(texto_fecha, fmt).date()
            except:
                continue
        return None

    def _parsear_monto(self, texto_monto, formato_americano=False):
        """Convierte texto de monto a Decimal.

        Args:
            texto_monto: Texto con el monto a parsear
            formato_americano: Si es True, asume coma=miles, punto=decimal (ej: 70,387.28)
                              Si es False, asume punto=miles, coma=decimal (ej: 70.387,28)
        """
        if not texto_monto:
            return None

        try:
            # Quitar espacios y símbolos de moneda
            limpio = texto_monto.replace(' ', '').replace('$', '')

            # Detectar formato automáticamente si no se especifica
            # Si tiene punto seguido de exactamente 2 dígitos al final, es formato americano
            # Ej: 70,387.28 -> formato americano
            # Ej: 70.387,28 -> formato argentino
            tiene_punto = '.' in limpio
            tiene_coma = ',' in limpio

            if tiene_punto and tiene_coma:
                # Ambos separadores presentes
                pos_punto = limpio.rfind('.')
                pos_coma = limpio.rfind(',')

                if pos_punto > pos_coma:
                    # Punto después de coma: formato americano (70,387.28)
                    formato_americano = True
                else:
                    # Coma después de punto: formato argentino (70.387,28)
                    formato_americano = False
            elif tiene_punto and not tiene_coma:
                # Solo punto: podría ser decimal o miles
                # Si hay exactamente 2 dígitos después del punto, es decimal
                partes = limpio.split('.')
                if len(partes) == 2 and len(partes[1]) == 2:
                    formato_americano = True  # Es decimal americano

            if formato_americano:
                # Formato americano: quitar comas (miles), mantener punto (decimal)
                limpio = limpio.replace(',', '')
            else:
                # Formato argentino: quitar puntos (miles), cambiar coma por punto (decimal)
                limpio = limpio.replace('.', '').replace(',', '.')

            valor = Decimal(limpio)
            # Validar que sea un monto razonable (no negativo, no excesivamente grande)
            if valor >= 0 and valor < Decimal('999999999999'):
                return valor
            return None
        except:
            return None

    def _limpiar_nombre(self, nombre):
        """Limpia y normaliza un nombre."""
        if not nombre:
            return None
        # Quitar caracteres especiales al final
        nombre = re.sub(r'[,\.\-:]+$', '', nombre)
        # Normalizar espacios
        nombre = ' '.join(nombre.split())
        # Titulo case si es todo mayusculas o minusculas
        if nombre.isupper() or nombre.islower():
            nombre = nombre.title()
        return nombre if len(nombre) > 2 else None

    def _limpiar_documento(self, documento):
        """Limpia y normaliza un numero de documento (DNI o CUIT/CUIL)."""
        if not documento:
            return None

        # Quitar puntos, guiones y espacios
        limpio = re.sub(r'[\.\-\s]', '', str(documento))

        # Verificar que sea solo digitos
        if not limpio.isdigit():
            return None

        # Formatear segun longitud
        if len(limpio) == 11:
            # CUIT/CUIL: XX-XXXXXXXX-X
            return f"{limpio[:2]}-{limpio[2:10]}-{limpio[10]}"
        elif len(limpio) == 8:
            # DNI 8 digitos: XX.XXX.XXX
            return f"{limpio[:2]}.{limpio[2:5]}.{limpio[5:8]}"
        elif len(limpio) == 7:
            # DNI 7 digitos: X.XXX.XXX
            return f"{limpio[0]}.{limpio[1:4]}.{limpio[4:7]}"
        elif len(limpio) >= 7:
            # Otro formato, devolver sin formatear
            return limpio

        return None

    def _limpiar_patente(self, patente):
        """Limpia y normaliza una patente."""
        if not patente:
            return None
        # Quitar espacios y guiones
        limpia = re.sub(r'[\s\-]', '', patente).upper()
        # Validar formato (viejo: ABC123, nuevo: AB123CD)
        if re.match(r'^[A-Z]{3}\d{3}$', limpia) or re.match(r'^[A-Z]{2}\d{3}[A-Z]{2}$', limpia):
            return limpia
        return patente.upper().strip()

    def _extraer_datos_liderar(self, texto):
        """Extraccion especifica para polizas de Liderar.

        Estructura tipica del PDF de Liderar:
        - Numero poliza: 017889422 / 000000
        - CUIT despues de "Cons. Final": 20-11549534-9
        - Nombre: SANTUORO, RAUL ARMANDO
        - Codigo productor: 01050816 ( 3)
        - Direccion en lineas separadas: ALVEAR 40 / (2156) - FRAY LUIS BELTRAN / SANTA FE
        - Vehiculo: Marca: RVM TEKKEN 250 / - 2023 - Patente: A191QBD
        """
        datos = {}

        # Numero de poliza: formato 017536021 / 000000
        match = re.search(r'(\d{9})\s*/\s*\d{6}', texto)
        if match:
            datos['numero_poliza'] = match.group(1)

        # CUIT - en Liderar aparece despues de "Cons. Final" o "Resp. Inscripto"
        # Formato: 20-11549534-9
        match = re.search(r'(?:Cons\.?\s*Final|Resp\.?\s*Inscripto|Monotributo)\s*\n?\s*(\d{2}-\d{8}-\d)', texto)
        if match:
            datos['asegurado_documento'] = match.group(1)
        else:
            # Buscar CUIT en formato con o sin guiones
            match = re.search(r'(\d{2})-(\d{8})-(\d)', texto)
            if match:
                datos['asegurado_documento'] = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

        # Nombre del asegurado - viene despues del CUIT, en formato APELLIDO, NOMBRE
        # Buscar: 20-11549534-9\nSANTUORO, RAUL ARMANDO\n01050816
        # NOTA: Incluimos # en el patron porque la Ñ a veces se extrae como #
        if 'asegurado_documento' in datos:
            cuit_pattern = datos['asegurado_documento'].replace('-', r'[-\s]?')
            # Patron que incluye # para capturar Ñ mal codificada (ej: LUDUE#A = LUDUEÑA)
            match = re.search(cuit_pattern + r'\s*\n?\s*([A-ZÁÉÍÓÚÑ#][A-ZÁÉÍÓÚÑ#]+,\s*[A-ZÁÉÍÓÚÑ#][A-ZÁÉÍÓÚÑ#\s]+?)(?:\n|\d{8})', texto)
            if match:
                nombre = match.group(1).strip()
                # Reemplazar # por Ñ (caracter mal codificado)
                nombre = nombre.replace('#', 'Ñ')
                datos['asegurado_nombre'] = self._limpiar_nombre(nombre)

        # Si no encontramos con el patron anterior, buscar nombre en formato APELLIDO, NOMBRE
        if 'asegurado_nombre' not in datos:
            # Patron que incluye # para Ñ mal codificada
            match = re.search(r'\n([A-ZÁÉÍÓÚÑ#]{2,}[A-ZÁÉÍÓÚÑ#]+,\s*[A-ZÁÉÍÓÚÑ#][A-ZÁÉÍÓÚÑ#\s]+?)\s*\n\d{8}', texto)
            if match:
                nombre = match.group(1).strip()
                # Excluir palabras de la cabecera del documento
                palabras_excluir = ['PESOS', 'PRIMA', 'LIDERAR', 'SEGUROS', 'RECARGO', 'EMISION', 'ASEGURADO', 'SECCION', 'POLIZA']
                if len(nombre) > 5 and not any(x in nombre.upper() for x in palabras_excluir):
                    # Reemplazar # por Ñ
                    nombre = nombre.replace('#', 'Ñ')
                    datos['asegurado_nombre'] = self._limpiar_nombre(nombre)

        # Direccion del asegurado - viene despues del codigo de productor
        # Formato: 01050816 ( 3)\nALVEAR 40\n(2156) - FRAY LUIS BELTRAN\nSANTA FE\nPESOS
        match = re.search(r'\d{8}\s*\(\s*\d\s*\)\s*\n([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ0-9\s\.]+\d+)\s*\n\((\d{4,5})\)\s*-\s*([A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)\s*\n([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+?)\s*\n(?:PESOS|DOLARES|\*)', texto)
        if match:
            calle = match.group(1).strip()
            cp = match.group(2).strip()
            localidad = match.group(3).strip()
            provincia = match.group(4).strip()
            # Limpiar provincia
            provincia = re.sub(r'\s+', ' ', provincia).strip()
            datos['asegurado_direccion'] = f"{calle}, ({cp}) {localidad}, {provincia}"
        else:
            # Intentar captura alternativa sin "PESOS" como terminador
            match = re.search(r'\d{8}\s*\(\s*\d\s*\)\s*\n([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ0-9\s\.]+\d+)\s*\n\((\d{4,5})\)\s*-\s*([A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)\s*\n([A-Z][A-Z\s]+?)(?=\n)', texto)
            if match:
                calle = match.group(1).strip()
                cp = match.group(2).strip()
                localidad = match.group(3).strip()
                provincia = match.group(4).strip()
                if provincia.upper() not in ['PESOS', 'DOLARES', 'USD']:
                    datos['asegurado_direccion'] = f"{calle}, ({cp}) {localidad}, {provincia}"
                else:
                    datos['asegurado_direccion'] = f"{calle}, ({cp}) {localidad}"
            else:
                # Solo calle
                match = re.search(r'\d{8}\s*\(\s*\d\s*\)\s*\n([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ0-9\s\.]+\d+)', texto)
                if match:
                    datos['asegurado_direccion'] = match.group(1).strip()

        # Fechas de vigencia en Liderar - formato:
        # 26/03/2025\n26/07/2025\nCons. Final
        match = re.search(r'(\d{2}/\d{2}/\d{4})\s*\n\s*(\d{2}/\d{2}/\d{4})\s*\n\s*(?:Cons\.?\s*Final|Resp\.?\s*Inscripto|Monotributo)', texto)
        if match:
            datos['fecha_desde_texto'] = match.group(1)
            datos['fecha_hasta_texto'] = match.group(2)
        else:
            # Fallback: buscar fechas consecutivas en el area de datos
            fechas = re.findall(r'(\d{2}/\d{2}/202[4-9])', texto[:3000])
            if len(fechas) >= 2:
                # Ignorar la primera (emisión) y tomar las siguientes
                fechas_unicas = []
                for f in fechas:
                    if f not in fechas_unicas:
                        fechas_unicas.append(f)
                if len(fechas_unicas) >= 3:
                    datos['fecha_desde_texto'] = fechas_unicas[1]
                    datos['fecha_hasta_texto'] = fechas_unicas[2]
                elif len(fechas_unicas) == 2:
                    datos['fecha_desde_texto'] = fechas_unicas[0]
                    datos['fecha_hasta_texto'] = fechas_unicas[1]

        # Premio y Prima en Liderar - valores con asteriscos
        # La estructura es: ***3,219.22 (prima) ... ***676.04 (IVA) ... ***3,982.19 (premio)
        # Formato: coma para miles, punto para decimales (ej: 3,219.22 = 3219.22)
        # Buscar específicamente en la sección de valores monetarios antes de "Fec.Pago"
        seccion_valores = texto[:texto.find('Fec.Pago')] if 'Fec.Pago' in texto else texto[:3000]
        valores = re.findall(r'\*+(\d[\d\.,]+)', seccion_valores)
        if valores:
            # Filtrar valores típicos de primas (entre 500 y 500,000)
            # Excluir sumas aseguradas que suelen ser mayores
            valores_primas = []
            for v in valores:
                try:
                    # Formato: 3,219.22 → quitar comas (separador de miles)
                    num = float(v.replace(',', ''))
                    if num > 500 and num < 500000:  # Rango típico de primas
                        valores_primas.append((v, num))
                except:
                    pass

            if valores_primas:
                # El premio es el mayor en este rango, la prima el segundo
                valores_ordenados = sorted(valores_primas, key=lambda x: x[1], reverse=True)
                if len(valores_ordenados) >= 1:
                    datos['premio_texto'] = valores_ordenados[0][0]
                if len(valores_ordenados) >= 2:
                    datos['prima_texto'] = valores_ordenados[1][0]

        # Vehiculo - Liderar usa formato: Marca: RVM TEKKEN 250
        match = re.search(r'Marca:\s*([A-Z0-9][A-Z0-9\s\-\.]+?)(?:\n|$)', texto, re.IGNORECASE)
        if match:
            marca_modelo = match.group(1).strip()
            partes = marca_modelo.split()
            if partes:
                datos['vehiculo_marca'] = partes[0]
                if len(partes) > 1:
                    datos['vehiculo_modelo'] = ' '.join(partes[1:])

        # Año y patente: - 2023 - Patente: A191QBD
        match = re.search(r'-\s*((?:19|20)\d{2})\s*-\s*Patente:\s*([A-Z0-9]+)', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_anio'] = int(match.group(1))
            datos['vehiculo_patente'] = match.group(2).strip()
        else:
            # Buscar año solo
            match = re.search(r'Marca:.*?\n-\s*((?:19|20)\d{2})\s*-', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_anio'] = int(match.group(1))
            # Buscar patente sola
            match = re.search(r'Patente:\s*([A-Z]{1,2}\d{3}[A-Z]{2,3}|[A-Z]{3}\d{3})', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_patente'] = match.group(1).upper()

        # Tipo de vehiculo
        match = re.search(r'Tipo\s*:\s*([A-Za-z0-9\.\s]+?)(?:\n|Carroceria)', texto)
        if match:
            datos['vehiculo_tipo'] = match.group(1).strip()

        # Uso del vehiculo
        match = re.search(r'Uso\s*:\s*([A-Za-z]+)', texto)
        if match:
            datos['vehiculo_uso'] = match.group(1)

        # Motor - formato: Motor: 171YMMYC012971
        match = re.search(r'Motor:\s*([A-Z0-9]{8,20})', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_motor'] = match.group(1)

        # Chasis - formato: Chasis: 8CFT4GMT5PA015918
        match = re.search(r'Chasis:\s*([A-Z0-9]{10,20})', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_chasis'] = match.group(1)

        # Productor en Liderar - formato: 00977 ISOLA ANA-CTA.1\n52922
        # Buscar específicamente después de la sección de cuotas (Fec.Pago)
        match = re.search(r'(?:Prorrogas de vigencia|Fec\.Pago).*?\n(\d{5})\s+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\-\.]+?)(?:-CTA\.\d+)?\s*\n\s*(\d{4,6})', texto, re.DOTALL)
        if match:
            datos['productor_codigo'] = match.group(1)
            datos['productor_nombre'] = match.group(2).strip()
            datos['productor_matricula'] = match.group(3)
        else:
            # Buscar patrón más simple
            match = re.search(r'\n(\d{5})\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s*(?:-CTA\.\d+)?\s*\n\s*(\d{4,6})\s*\n', texto)
            if match:
                datos['productor_codigo'] = match.group(1)
                datos['productor_nombre'] = match.group(2).strip()
                datos['productor_matricula'] = match.group(3)

        # Coberturas - buscar despues de "RIESGOS CUBIERTOS"
        match = re.search(r'RIESGOS CUBIERTOS\s*:\s*(.+?)(?:\*ADVERTENCIA|ADVERTENCIA|$)', texto, re.DOTALL)
        if match:
            coberturas_texto = match.group(1).strip()
            # Limpiar y formatear coberturas
            coberturas_texto = re.sub(r'\s+', ' ', coberturas_texto)
            datos['coberturas_texto'] = coberturas_texto[:500]  # Limitar longitud

        return datos

    def _extraer_datos_berkley(self, texto):
        """Extraccion especifica para polizas de Berkley."""
        datos = {}

        # Numero de poliza Berkley - múltiples formatos:
        # Formato 1: Con saltos de línea "POLIZA\n...\n8\n838469"
        match = re.search(r'POLIZA\n.*?\n(\d)\n(\d{6,8})', texto, re.DOTALL)
        if match:
            datos['numero_poliza'] = f"{match.group(1)}-{match.group(2)}"
        else:
            # Formato 2: "8 - 838469" en una línea
            match = re.search(r'(\d)\s*-\s*(\d{6,8})', texto)
            if match:
                datos['numero_poliza'] = f"{match.group(1)}-{match.group(2)}"
            else:
                # Formato 3: buscar patron con guion (Pol.: 09032269-004)
                match = re.search(r'P[oó]l\.?:\s*(\d{7,9})-', texto)
                if match:
                    datos['numero_poliza'] = match.group(1)

        # Nombre del asegurado - múltiples formatos según tipo de póliza
        # Lista de nombres a excluir (provincias, ciudades, localidades)
        excluir = ['SANTA FE', 'BUENOS AIRES', 'CORDOBA', 'ROSARIO', 'MENDOZA', 'SAN LORENZO',
                   'CAPITAL FEDERAL', 'TUCUMAN', 'SALTA', 'NEUQUEN', 'ENTRE RIOS']

        # Formato 1: "DNI XXXXXXXX\nAPELLIDO, NOMBRE" (común en pólizas de incendio)
        match = re.search(r'DNI\s+\d{7,8}\s*\n([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ]+,\s*[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+?)\s*\n', texto)
        if match:
            nombre = match.group(1).strip()
            if nombre.upper() not in excluir and len(nombre) > 3:
                datos['asegurado_nombre'] = nombre

        # Formato 2: Después del CUIT, razón social (puede tener números y puntos)
        if 'asegurado_nombre' not in datos:
            match = re.search(r'CUIT:\s*\d{2}-\d{8}-\d\s*\n\s*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ0-9\s\.,]+?)(?:\n|RUTA|CALLE|AV\.)', texto)
            if match:
                nombre = match.group(1).strip()
                if nombre.upper() not in excluir and len(nombre) > 3:
                    datos['asegurado_nombre'] = nombre

        # Formato 3: "APELLIDO, NOMBRE" después del CUIT
        if 'asegurado_nombre' not in datos:
            match = re.search(r'CUIT:\s*\d{2}-\d{8}-\d\s*\n\s*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ]+,\s*[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+?)\s*\n', texto)
            if match:
                datos['asegurado_nombre'] = match.group(1).strip()

        # CUIT del asegurado
        match = re.search(r'CUIT:\s*(\d{2}-\d{8}-\d)', texto)
        if match:
            datos['asegurado_documento'] = match.group(1).replace('-', '')

        # Fechas de vigencia Berkley - múltiples formatos:
        # Formato 1: "Desde las 12hs del DD/MM/YYYY hasta las 12hs del DD/MM/YYYY"
        match = re.search(r'Desde las \d+hs del (\d{2}/\d{2}/\d{4}) hasta las \d+hs del (\d{2}/\d{2}/\d{4})', texto)
        if match:
            datos['fecha_desde_texto'] = match.group(1)
            datos['fecha_hasta_texto'] = match.group(2)
        else:
            # Formato 2: Fecha inicio con (**) y "nunca antes del DD/MM/YYYY"
            # Buscar fecha hasta: "hasta las 12hs del DD/MM/YYYY"
            match_hasta = re.search(r'hasta las \d+hs del (\d{2}/\d{2}/\d{4})', texto)
            if match_hasta:
                datos['fecha_hasta_texto'] = match_hasta.group(1)

            # Buscar fecha desde: "nunca antes del DD/MM/YYYY"
            match_desde = re.search(r'nunca antes del (\d{2}/\d{2}/\d{4})', texto)
            if match_desde:
                datos['fecha_desde_texto'] = match_desde.group(1)

        # Vehiculo Berkley: MARCA : VOLKSWAGEN MODELO : SAVEIRO 1.9 SD LIMITED AÑO :       2008
        # Nota: puede haber espacios extra antes del año
        match = re.search(r'MARCA\s*:\s*([A-Z0-9]+)\s+MODELO\s*:\s*([A-Z0-9\s\.\-\/]+?)\s+A[ÑN]O\s*:\s+(\d{4})', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_marca'] = match.group(1).strip()
            modelo = match.group(2).strip()
            # Limpiar el modelo (quitar espacios extra, saltos de línea)
            modelo = ' '.join(modelo.split())
            datos['vehiculo_modelo'] = modelo
            datos['vehiculo_anio'] = int(match.group(3))
        else:
            # Formato alternativo: buscar línea completa con marca, modelo y año
            match = re.search(r'MARCA\s*:\s*([A-Z0-9]+)\s+MODELO\s*:\s*(.+?)\s+A[ÑN]O\s*:', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_marca'] = match.group(1).strip()
                modelo = match.group(2).strip()
                modelo = ' '.join(modelo.split())
                datos['vehiculo_modelo'] = modelo
            # Buscar año por separado
            match_anio = re.search(r'A[ÑN]O\s*:\s+(\d{4})', texto, re.IGNORECASE)
            if match_anio:
                datos['vehiculo_anio'] = int(match_anio.group(1))

        # Patente Berkley: PTTE.: HEM915
        match = re.search(r'PTTE\.?:\s*([A-Z0-9]+)', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_patente'] = match.group(1).strip()

        # Motor y Chasis: MOTOR : BGG034510 CHASIS : 9BWED05W68P120286
        match = re.search(r'MOTOR\s*:\s*([A-Z0-9]+)', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_motor'] = match.group(1)

        match = re.search(r'CHASIS\s*:\s*([A-Z0-9]+)', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_chasis'] = match.group(1)

        # Uso del vehiculo
        match = re.search(r'USO DE VEHICULO\s*:\s*([A-Z]+)', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_uso'] = match.group(1)

        # Suma asegurada - RC y daños
        match = re.search(r'RESPONSABILIDAD CIVIL[A-Z\s]*PESOS\s*([\d\.,]+)', texto)
        if match:
            datos['suma_asegurada_rc'] = match.group(1)

        match = re.search(r'ROBO.*?PESOS\s*([\d\.,]+)', texto)
        if match:
            datos['suma_asegurada_texto'] = match.group(1)

        # Premio
        match = re.search(r'PREMIO\s*\n\s*([\d\.,]+)', texto)
        if match:
            datos['prima_texto'] = match.group(1)
        elif re.search(r'PO\s*:\s*\$\s*([\d\.,]+)', texto):
            match = re.search(r'PO\s*:\s*\$\s*([\d\.,]+)', texto)
            datos['prima_texto'] = match.group(1)

        # Productor
        match = re.search(r'PROD\.?\s*:\s*\d+\s*-\s*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s,\.]+?)(?:\n|PLAN|$)', texto)
        if match:
            datos['productor_nombre'] = match.group(1).strip()

        # Direccion
        match = re.search(r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+\d+[A-Za-záéíóúñ\s]*)\s*\n\s*AUTOMOTORES', texto)
        if match:
            datos['asegurado_direccion'] = match.group(1).strip()

        return datos

    def _extraer_datos_mercantil_andina(self, texto):
        """Extraccion especifica para polizas de Mercantil Andina."""
        datos = {}

        # Numero de poliza Mercantil Andina: formato largo, ej: 501032094855 o 016533352
        # Formato 1: numero de 9-12 dígitos solo
        match = re.search(r'^(\d{9,12})$', texto, re.MULTILINE)
        if match:
            datos['numero_poliza'] = match.group(1)
        else:
            # Formato 2: Póliza: NUMERO
            match = re.search(r'[Pp][oó]liza\s*(?:N[°º]?|Nro\.?)?\s*:?\s*(\d{9,12})', texto)
            if match:
                datos['numero_poliza'] = match.group(1)
            else:
                # Formato 3: AUTOMOTORES seguido de número
                match = re.search(r'AUTOMOTORES\s*\n(\d{9,12})', texto)
                if match:
                    datos['numero_poliza'] = match.group(1)

        # CUIT del asegurado: formato XX-XXXXXXXX-X (excluir el de la compañía 30-50003691-1)
        # Formato 1: CUIT después de "IVA:" en línea separada (más confiable en Mercantil Andina)
        match_cuit_iva = re.search(r'IVA:\s*[A-Za-z\.]+\s*\n(\d{2})-?(\d{8})-?(\d)', texto)
        if match_cuit_iva:
            cuit_completo = f"{match_cuit_iva.group(1)}{match_cuit_iva.group(2)}{match_cuit_iva.group(3)}"
            if cuit_completo not in ['30500036911', '30500035788']:
                datos['asegurado_documento'] = cuit_completo

        # Formato 2: Buscar todos los CUIT con guiones
        if 'asegurado_documento' not in datos:
            matches_cuit = re.findall(r'(\d{2})-(\d{8})-(\d)', texto)
            for m in matches_cuit:
                cuit_completo = f"{m[0]}{m[1]}{m[2]}"
                # Excluir CUIT de Mercantil Andina
                if cuit_completo not in ['30500036911', '30500035788']:
                    datos['asegurado_documento'] = cuit_completo
                    break

        # Formato 3: CUIT sin guiones (11 dígitos que empiezan con 20, 23, 24, 27, 30, 33, 34)
        if 'asegurado_documento' not in datos:
            match = re.search(r'\b((?:20|23|24|27|30|33|34)\d{9})\b', texto)
            if match:
                cuit = match.group(1)
                if cuit not in ['30500036911', '30500035788']:
                    datos['asegurado_documento'] = cuit

        # Nombre del asegurado - varios formatos Mercantil Andina
        # Lista de textos a excluir (fragmentos de póliza, no nombres)
        excluir_mercantil = ['IVA', 'FACTURACION', 'DEBERA CONTAR', 'EL VEHICULO', 'GRABADO',
                             'CONFORME', 'RESPECTIVO', 'INDELEBLE', 'DOMINIO', 'COBERTURA']

        # Formato 1: Nombre en línea después de fechas de vigencia (DD.MM.YYYY\nDD.MM.YYYY\nNOMBRE)
        # Incluye apóstrofes para nombres como "D'ALESSANDRO" y puntos para "S.R.L."
        match = re.search(r'\d{2}\.\d{2}\.\d{4}\s*\n\d{2}\.\d{2}\.\d{4}\s*\n([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\'\.]+)\n', texto)
        if match:
            nombre = match.group(1).strip()
            nombre_upper = nombre.upper()
            # Verificar que no sea texto de la póliza
            es_excluido = any(excl in nombre_upper for excl in excluir_mercantil)
            if len(nombre) > 3 and not es_excluido:
                datos['asegurado_nombre'] = self._limpiar_nombre(nombre)

        # Formato 2: Asegurado: NUMERO\nNOMBRE (incluye apóstrofes y puntos para SRL, S.A., etc.)
        if 'asegurado_nombre' not in datos:
            match = re.search(r'Asegurado:\s*\d+\s*\n([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\'\.]+)\n', texto)
            if match:
                nombre = match.group(1).strip()
                if len(nombre) > 3:
                    datos['asegurado_nombre'] = self._limpiar_nombre(nombre)

        # Formato 3: Buscar después de "Asegurado" o "Tomador"
        if 'asegurado_nombre' not in datos:
            match = re.search(r'(?:Asegurado|Tomador|Cliente)\s*:?\s*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s,\.]+?)(?:\n|CUIT|DNI|C\.U\.I\.T|$)', texto)
            if match:
                nombre = match.group(1).strip()
                if len(nombre) > 3:
                    datos['asegurado_nombre'] = self._limpiar_nombre(nombre)

        # Fechas de vigencia: varios formatos
        # Formato 1: DD.MM.YYYY\nDD.MM.YYYY (con puntos)
        match = re.search(r'(\d{2}\.\d{2}\.\d{4})\s*\n(\d{2}\.\d{2}\.\d{4})', texto)
        if match:
            # Convertir de DD.MM.YYYY a DD/MM/YYYY
            datos['fecha_desde_texto'] = match.group(1).replace('.', '/')
            datos['fecha_hasta_texto'] = match.group(2).replace('.', '/')

        # Formato 2: Vigencia.: DD.MM.YYYY / DD.MM.YYYY
        if 'fecha_desde_texto' not in datos:
            match = re.search(r'Vigencia\.?:\s*(\d{2}\.\d{2}\.\d{4})\s*/\s*(\d{2}\.\d{2}\.\d{4})', texto)
            if match:
                datos['fecha_desde_texto'] = match.group(1).replace('.', '/')
                datos['fecha_hasta_texto'] = match.group(2).replace('.', '/')

        # Formato 3: "Vigencia: DD/MM/YYYY a DD/MM/YYYY"
        if 'fecha_desde_texto' not in datos:
            match = re.search(r'Vigencia\s*:?\s*(\d{2}/\d{2}/\d{4})\s*(?:a|al|hasta|-)\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
            if match:
                datos['fecha_desde_texto'] = match.group(1)
                datos['fecha_hasta_texto'] = match.group(2)
            else:
                # Intentar con formato separado
                match_desde = re.search(r'(?:Desde|Inicio|Vigencia\s+Desde)\s*:?\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
                match_hasta = re.search(r'(?:Hasta|Vencimiento|Fin|Vigencia\s+Hasta)\s*:?\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
                if match_desde:
                    datos['fecha_desde_texto'] = match_desde.group(1)
                if match_hasta:
                    datos['fecha_hasta_texto'] = match_hasta.group(1)

        # Vehiculo - Mercantil Andina formatos varios
        # Formato suplemento: PATENTE\nAA123BB  o  Patente: AA123BB
        # Buscar patente primero (más confiable)
        match = re.search(r'(?:PATENTE|Patente|Dominio)\s*:?\s*\n?\s*([A-Z]{2}\d{3}[A-Z]{2}|[A-Z]{3}\d{3})', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_patente'] = match.group(1).upper()
        else:
            # Buscar patente en formato suelto (sin etiqueta)
            match = re.search(r'\b([A-Z]{2}\d{3}[A-Z]{2})\b', texto)
            if match:
                datos['vehiculo_patente'] = match.group(1)
            else:
                match = re.search(r'\b([A-Z]{3}\d{3})\b', texto)
                if match:
                    datos['vehiculo_patente'] = match.group(1)

        # Formato suplemento Mercantil Andina con puntos suspensivos:
        # Marca...........: TOYOTA
        # HILUX L/21 2.8 DC 4X4 TDI SRV
        # Modelo 2021
        match = re.search(r'Marca\.+:\s*([A-Z]+)\s*\n([A-Z0-9\s\.\-\/]+?)\nModelo\s+(\d{4})', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_marca'] = match.group(1).strip()
            datos['vehiculo_modelo'] = match.group(2).strip()
            datos['vehiculo_anio'] = int(match.group(3))

        # Formato suplemento: VEHICULO\nCHEVROLET \nONIX 1.2 PLUS L/19 2021
        if 'vehiculo_marca' not in datos:
            match = re.search(r'VEH[IÍ]CULO\s*\n([A-Z]+)\s*\n([A-Z0-9\s\.\-\/]+?)(\d{4})', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_marca'] = match.group(1).strip()
                datos['vehiculo_modelo'] = match.group(2).strip()
                datos['vehiculo_anio'] = int(match.group(3))

        # Formato alternativo: Marca y Modelo en la misma línea
        if 'vehiculo_marca' not in datos:
            match = re.search(r'Marca\s*:?\s*([A-Z0-9]+)\s*[-/]?\s*Modelo\s*:?\s*([A-Z0-9\s\.\-\/]+?)(?:\n|Año|A[ñn]o|Patente|$)', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_marca'] = match.group(1).strip()
                modelo = match.group(2).strip()
                # Limpiar modelo
                modelo = ' '.join(modelo.split())
                datos['vehiculo_modelo'] = modelo

        # Formato: "VOLKSWAGEN GOL TREND" después de Vehículo
        if 'vehiculo_marca' not in datos:
            match = re.search(r'Veh[ií]culo\s*:?\s*([A-Z0-9]+)\s+([A-Z0-9\s\.\-\/]+?)(?:\n|Año|$)', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_marca'] = match.group(1).strip()
                datos['vehiculo_modelo'] = match.group(2).strip()

        # Año del vehiculo (si no se extrajo antes)
        if 'vehiculo_anio' not in datos:
            # Buscar año después de L/XX (ej: L/19 2021)
            match = re.search(r'L/\d{2}\s+(\d{4})', texto)
            if match:
                datos['vehiculo_anio'] = int(match.group(1))
            else:
                match = re.search(r'A[ñn]o\s*:?\s*((?:19|20)\d{2})', texto, re.IGNORECASE)
                if match:
                    datos['vehiculo_anio'] = int(match.group(1))

        # Motor y Chasis (requiere mínimo 5 caracteres para evitar falsos positivos)
        match = re.search(r'Motor\s*(?:N[°º]?)?\s*:?\s*([A-Z0-9\-]{5,})', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_motor'] = match.group(1)

        match = re.search(r'Chasis\s*(?:N[°º]?)?\s*:?\s*([A-Z0-9]+)', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_chasis'] = match.group(1)

        # Prima / Premio total
        match = re.search(r'(?:Prima|Premio)\s*(?:Total)?\s*:?\s*\$?\s*([\d\.,]+)', texto, re.IGNORECASE)
        if match:
            datos['prima_texto'] = match.group(1)

        # Suma asegurada
        match = re.search(r'(?:Suma\s+Asegurada|Capital)\s*:?\s*\$?\s*([\d\.,]+)', texto, re.IGNORECASE)
        if match:
            datos['suma_asegurada_texto'] = match.group(1)

        # Direccion del asegurado - Mercantil Andina tiene formato especial
        # Formato 1 Mercantil Andina: "Calle N° 123 , ( XXXX) LOCALIDAD PROV"
        # Aparece después del nombre del asegurado y antes de "Vigencia.:"
        match = re.search(r'\n([A-Za-záéíóúñÑ\s\.]+\s+N[°º]?\s*\d+\s*,\s*\(\s*\d{4}\s*\)\s*[A-Za-záéíóúñÑ\.\s]+[A-Z]{2,3})\s*\n', texto)
        if match:
            direccion = match.group(1).strip()
            # Limpiar espacios múltiples
            direccion = ' '.join(direccion.split())
            datos['asegurado_direccion'] = direccion

        # Formato 2: Domicilio o Dirección con etiqueta
        if 'asegurado_direccion' not in datos:
            match = re.search(r'(?:Domicilio|Direcci[oó]n)\s*:?\s*([A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s,\.]+?\d+[A-Za-záéíóúñÑ\s]*)', texto)
            if match:
                datos['asegurado_direccion'] = match.group(1).strip()

        # Formato 3: Buscar dirección entre nombre y vigencia (patrón más flexible)
        if 'asegurado_direccion' not in datos:
            # Buscar línea con número de calle después del nombre del asegurado
            match = re.search(r'Asegurado:\s*\d+\s*\n[A-ZÁÉÍÓÚÑ][^\n]+\n([A-Za-záéíóúñÑ\s\.]+\s+(?:N[°º]?\s*)?\d{1,5}[^\n]*)\n', texto)
            if match:
                direccion = match.group(1).strip()
                # Verificar que parece una dirección (tiene número)
                if re.search(r'\d{1,5}', direccion) and len(direccion) > 10:
                    datos['asegurado_direccion'] = ' '.join(direccion.split())

        # Productor
        match = re.search(r'(?:Productor|Asesor|Organizador)\s*:?\s*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\.\-]+?)(?:\n|Mat|Tel|$)', texto)
        if match:
            datos['productor_nombre'] = match.group(1).strip()

        # Tipo de cobertura/producto
        match = re.search(r'(?:Producto|Cobertura|Tipo)\s*:?\s*([A-Za-záéíóúñÑ\s]+?)(?:\n|$)', texto)
        if match:
            datos['tipo_cobertura'] = match.group(1).strip()

        return datos

    def _extraer_datos_rio_uruguay(self, texto):
        """Extraccion especifica para polizas/recibos de Rio Uruguay Seguros (RUS)."""
        datos = {}

        # ============================================================
        # NUMERO DE POLIZA RUS
        # ============================================================
        # Formato en recibos: POLIZA: 00:4:12294502 (con 1 dígito en medio)
        # Formato en pólizas: Póliza: 00:20:2576540 (con 2 dígitos en medio)
        match = re.search(r'P[OoÓó]LIZA:\s*(\d{2}:\d{1,2}:\d{7,8})', texto, re.IGNORECASE)
        if match:
            datos['numero_poliza'] = match.group(1)
        else:
            # Buscar el patron directamente (formato completo)
            match = re.search(r'\b(\d{2}:\d{1,2}:\d{7,8})\b', texto)
            if match:
                datos['numero_poliza'] = match.group(1)
            else:
                # Formato corto en cupón: 4:12294502
                match = re.search(r'\b(\d{1,2}:\d{7,8})\b', texto)
                if match:
                    datos['numero_poliza'] = '00:' + match.group(1)

        # Numero de recibo (formato largo)
        match = re.search(r'Recibo\s*(?:Nro\.?|N[°º])?\s*:?\s*(\d{11,17})', texto, re.IGNORECASE)
        if match:
            datos['numero_recibo'] = match.group(1)

        # ============================================================
        # ASEGURADO - múltiples formatos según tipo de documento
        # ============================================================
        # Formato RUS endoso/póliza: después del CUIT del asegurado hay una línea con el nombre
        # Buscar: XX-XXXXXXXX-X\nNOMBRE COMPLETO\nLocalidad
        matches_cuit = re.findall(r'(\d{2}-\d{8}-\d)\s*\n([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)\s*\n(?:Localidad|Desde|Cobrador|Productor)', texto)
        for m in matches_cuit:
            cuit = m[0].replace('-', '')
            # Excluir CUIT de RUS (30500061711)
            if cuit != '30500061711':
                nombre = m[1].strip()
                if len(nombre) > 3 and nombre not in ['ISOLA ANA MARIA', 'COBRADOR', 'PRODUCTOR']:
                    datos['asegurado_nombre'] = nombre
                    break

        # Formato alternativo: DNI/CUIL:\n...\nNOMBRE
        if 'asegurado_nombre' not in datos:
            match = re.search(r'DNI/CUIL:\s*\n[^\n]*\n([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)\s*\n', texto)
            if match:
                nombre = match.group(1).strip()
                if len(nombre) > 3:
                    datos['asegurado_nombre'] = nombre

        # Formato recibo: ASEGURADO\nNOMBRE EN MAYUSCULAS
        if 'asegurado_nombre' not in datos:
            match = re.search(r'ASEGURADO\n([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s,\.]+)', texto)
            if match:
                nombre = match.group(1).strip()
                # Limpiar caracteres finales
                nombre = re.sub(r'[\s,\.]+$', '', nombre)
                if len(nombre) > 3 and 'CUIL' not in nombre and 'CUIT' not in nombre:
                    datos['asegurado_nombre'] = nombre

        # Formato póliza: Localidad: ... \n NOMBRE COMPLETO \n Asegurado:
        # Incluye guión para nombres compuestos como "JUAREZ HERME OSCAR - MOLINA ALEJANDRO"
        if 'asegurado_nombre' not in datos:
            match = re.search(r'Localidad:[^\n]+\n([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\-]+)\nAsegurado:', texto)
            if match:
                nombre = match.group(1).strip()
                # Excluir si parece una dirección (contiene números)
                if len(nombre) > 3 and not re.search(r'\d', nombre):
                    datos['asegurado_nombre'] = nombre

        # Fallback: buscar "Asegurado:\n" seguido del nombre
        # IMPORTANTE: Excluir direcciones que contienen números (ej: "PARENTE 1025")
        if 'asegurado_nombre' not in datos:
            match = re.search(r'Asegurado:\s*\n([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s,\-]+)', texto)
            if match:
                nombre = match.group(1).strip()
                nombre = re.sub(r'[\s,\.]+$', '', nombre)
                # Solo aceptar si no tiene números (excluir direcciones como "PARENTE 1025")
                if len(nombre) > 3 and not re.search(r'\d', nombre):
                    datos['asegurado_nombre'] = nombre

        # ============================================================
        # CUIT DEL ASEGURADO
        # ============================================================
        # Buscar CUIT que NO sea el de RUS (30-50006171-1)
        # Formato: XX-XXXXXXXX-X
        matches_cuit = re.findall(r'\b(\d{2})-(\d{8})-(\d)\b', texto)
        for m in matches_cuit:
            cuit_completo = f"{m[0]}{m[1]}{m[2]}"
            # Excluir CUIT de RUS (30500061711)
            if cuit_completo != '30500061711':
                datos['asegurado_documento'] = cuit_completo
                break

        # Si no encontró con guiones, buscar sin guiones (solo en recibo)
        if 'asegurado_documento' not in datos:
            # En recibos aparece el CUIT solo después del CUIT de RUS
            match = re.search(r'CUIT:\s*30-50006171-1\n(\d{2}-\d{8}-\d)', texto)
            if match:
                cuit = match.group(1).replace('-', '')
                datos['asegurado_documento'] = cuit

        # ============================================================
        # PATENTE
        # ============================================================
        # Buscar "PATENTE: XXXXXXX" (formato recibo)
        match = re.search(r'PATENTE:\s*([A-Z0-9]+)', texto)
        if match:
            datos['vehiculo_patente'] = match.group(1).strip()
        else:
            # Buscar "Patente: XXXXXXX" (formato póliza)
            match = re.search(r'Patente:\s*([A-Z0-9]+)', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_patente'] = match.group(1).strip()
            else:
                # Formato nuevo: AA123BB
                match = re.search(r'\b([A-Z]{2}\d{3}[A-Z]{2})\b', texto)
                if match:
                    datos['vehiculo_patente'] = match.group(1)
                else:
                    # Formato viejo: AAA123
                    match = re.search(r'\b([A-Z]{3}\d{3})\b', texto)
                    if match:
                        datos['vehiculo_patente'] = match.group(1)

        # ============================================================
        # VIGENCIA
        # ============================================================
        # Formato póliza especial RUS: Desde:\nHasta:\nDD/MM/YYYY\nDD/MM/YYYY
        match = re.search(r'Desde:\s*\nHasta:\s*\n(\d{2}/\d{2}/\d{4})\n(\d{2}/\d{2}/\d{4})', texto)
        if match:
            datos['fecha_desde_texto'] = match.group(1)
            datos['fecha_hasta_texto'] = match.group(2)

        # Formato normal: Desde:\nDD/MM/YYYY
        if 'fecha_desde_texto' not in datos:
            match_desde = re.search(r'Desde:\s*\n?\s*(\d{2}/\d{2}/\d{4})', texto)
            if match_desde:
                datos['fecha_desde_texto'] = match_desde.group(1)

        if 'fecha_hasta_texto' not in datos:
            match_hasta = re.search(r'Hasta:\s*\n?\s*(\d{2}/\d{2}/\d{4})', texto)
            if match_hasta:
                datos['fecha_hasta_texto'] = match_hasta.group(1)

        # Formato recibo: VIGENCIA:\nFECHA DE EMISION:\nDD/MM/YYYY\n-\nDD/MM/YYYY
        if 'fecha_desde_texto' not in datos or 'fecha_hasta_texto' not in datos:
            match = re.search(r'VIGENCIA:.*?(\d{2}/\d{2}/\d{4})\s*\n\s*-\s*\n\s*(\d{2}/\d{2}/\d{4})', texto, re.DOTALL)
            if match:
                datos['fecha_desde_texto'] = match.group(1)
                datos['fecha_hasta_texto'] = match.group(2)

        # Formato recibo alternativo: buscar dos fechas consecutivas después de VIGENCIA
        if 'fecha_desde_texto' not in datos or 'fecha_hasta_texto' not in datos:
            match = re.search(r'VIGENCIA:.*?EMISION:.*?\n(\d{2}/\d{2}/\d{4})\n.*?\n(\d{2}/\d{2}/\d{4})', texto, re.DOTALL)
            if match:
                datos['fecha_desde_texto'] = match.group(1)
                datos['fecha_hasta_texto'] = match.group(2)

        # ============================================================
        # VEHICULO
        # ============================================================
        # Formato recibo: MARCA: TOYOTA ETIOS 1.5 4 PTAS XLS
        match = re.search(r'MARCA:\s*([A-Z0-9][A-Z0-9\s\.\-]+)', texto)
        if match:
            marca_modelo = match.group(1).strip()
            partes = marca_modelo.split(None, 1)
            if partes:
                datos['vehiculo_marca'] = partes[0]
                if len(partes) > 1:
                    datos['vehiculo_modelo'] = partes[1]

        # Formato póliza: Marca y modelo:\nKELLER 110 CRONO
        if 'vehiculo_marca' not in datos:
            match = re.search(r'Marca y modelo:\s*\n?\s*([A-Z0-9][A-Z0-9\s\-\.\/]+?)(?:\s*\n\s*A[ñn]o|\s*$)', texto, re.IGNORECASE)
            if match:
                marca_modelo = match.group(1).strip()
                # Limpiar el modelo (quitar caracteres sueltos al final)
                marca_modelo = re.sub(r'\s+[A-Z]$', '', marca_modelo)
                partes = marca_modelo.split(None, 1)
                if partes:
                    datos['vehiculo_marca'] = partes[0]
                    if len(partes) > 1:
                        datos['vehiculo_modelo'] = partes[1]

        # Año - formato recibo: AÑO: 2014
        match = re.search(r'A[ÑN]O:\s*(\d{4})', texto)
        if match:
            datos['vehiculo_anio'] = int(match.group(1))
        else:
            # Formato póliza: Año:\n2024
            match = re.search(r'A[ñn]o:\s*\n?\s*((?:19|20)\d{2})', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_anio'] = int(match.group(1))

        # Motor - formato recibo: MOTOR: 2NRV198335
        match = re.search(r'MOTOR:\s*([A-Z0-9]+)', texto)
        if match:
            datos['vehiculo_motor'] = match.group(1)
        else:
            match = re.search(r'Motor:\s*([A-Z0-9]+)', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_motor'] = match.group(1)

        # Chasis - formato recibo: CHASIS: 9BRB29BT8E2046047
        match = re.search(r'CHASIS:\s*([A-Z0-9]{17})', texto)
        if match:
            datos['vehiculo_chasis'] = match.group(1)
        else:
            match = re.search(r'Chasis:\s*\n?\s*([A-Z0-9]{17})', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_chasis'] = match.group(1)
            else:
                # Buscar VIN sin etiqueta (17 caracteres que empiezan con dígito o letra)
                match = re.search(r'\b([89][A-Z0-9]{16})\b', texto)
                if match:
                    datos['vehiculo_chasis'] = match.group(1)

        # Tipo de unidad - formato recibo: TIPO: AUTO
        match = re.search(r'TIPO:\s*([A-Z]+)', texto)
        if match:
            datos['vehiculo_tipo'] = match.group(1).strip()
        else:
            match = re.search(r'Tipo de Unidad:\s*([A-Z0-9\s]+)', texto, re.IGNORECASE)
            if match:
                datos['vehiculo_tipo'] = match.group(1).strip()

        # Uso
        match = re.search(r'Uso:\s*\n?\s*([A-Z]+)', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_uso'] = match.group(1)

        # Combustible
        match = re.search(r'Combustible:\s*\n?\s*([A-Z]+)', texto, re.IGNORECASE)
        if match:
            datos['vehiculo_combustible'] = match.group(1)

        # ============================================================
        # PRODUCTOR
        # ============================================================
        # Formato póliza: Productor:\nNOMBRE\nMatrícula:\nNUMERO
        match = re.search(r'Productor:\s*\n([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+)\nMatr[ií]cula:', texto)
        if match:
            datos['productor_nombre'] = match.group(1).strip()

        # Formato recibo: 4738 - ISOLA ANA MARIA  Mat. SSN Nro: 52922
        if 'productor_nombre' not in datos:
            match = re.search(r'(\d{4,5})\s*-\s*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+?)\s+Mat\.?\s*(?:SSN)?\s*(?:Nro)?:?\s*(\d+)', texto)
            if match:
                datos['productor_codigo'] = match.group(1)
                datos['productor_nombre'] = match.group(2).strip()
                datos['productor_matricula'] = match.group(3)

        # Matrícula sola
        if 'productor_matricula' not in datos:
            match = re.search(r'Matr[ií]cula:\s*\n?\s*(\d+)', texto, re.IGNORECASE)
            if match:
                datos['productor_matricula'] = match.group(1)

        # ============================================================
        # DOMICILIO
        # ============================================================
        # Formato recibo: Domicilio\nDIRECCION (CODIGO)LOCALIDADProvincia
        match = re.search(r'Domicilio\n([A-Z0-9ÁÉÍÓÚÑ][A-Za-z0-9áéíóúñ\s]+\d+)\s*\((\d+)\)([A-Za-záéíóúñ]+)([A-Za-záéíóúñ\s]+)', texto)
        if match:
            datos['asegurado_direccion'] = match.group(1).strip()
            datos['asegurado_cp'] = match.group(2)
            datos['asegurado_localidad'] = match.group(3).strip()
            datos['asegurado_provincia'] = match.group(4).strip()

        # Formato póliza: Domicilio Real:\nDIRECCION
        if 'asegurado_direccion' not in datos:
            match = re.search(r'Domicilio Real:\s*\n?\s*([A-Z0-9ÁÉÍÓÚÑ][A-Za-z0-9áéíóúñ\s]+?\d+)', texto, re.IGNORECASE)
            if match:
                datos['asegurado_direccion'] = match.group(1).strip()

        # Buscar dirección después del nombre del asegurado
        if 'asegurado_direccion' not in datos:
            match = re.search(r'Asegurado:\s*\n([A-Z0-9][A-Za-z0-9\s]+\d+)', texto)
            if match:
                datos['asegurado_direccion'] = match.group(1).strip()

        # Localidad formato póliza
        if 'asegurado_localidad' not in datos:
            match = re.search(r'Localidad:\s*\(?\d+\)?\s*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+?)\s*/\s*([A-Za-záéíóúñ\s]+)', texto)
            if match:
                datos['asegurado_localidad'] = match.group(1).strip()
                datos['asegurado_provincia'] = match.group(2).strip()

        # Fechas de vencimiento del recibo
        match = re.search(r'Fecha Vto\.?\s*Actual\s*\n.*?\n(\d{2}/\d{2}/\d{4})', texto, re.DOTALL)
        if match:
            datos['fecha_vto_actual'] = match.group(1)

        match = re.search(r'Fecha Pr[oó]x\.?\s*Vto\s*\n?(\d{2}/\d{2}/\d{4})', texto)
        if match:
            datos['fecha_vto_proximo'] = match.group(1)

        # ============================================================
        # MONTOS
        # ============================================================
        # Prima de la tabla de cuotas (formato: NUMERO  FECHA  IMPORTE)
        # Buscar valores de importe en la sección de cuotas
        cuotas_importes = re.findall(r'\d+\s+\d{2}/\d{2}/\d{4}\s+([\d\.]+,\d{2})', texto)
        if cuotas_importes:
            # Tomar el primer importe como referencia de la cuota
            primer_importe = cuotas_importes[0]
            datos['prima_cuota'] = primer_importe
            # Calcular prima total aproximada (suma de cuotas encontradas)
            try:
                total = sum(float(i.replace('.', '').replace(',', '.')) for i in cuotas_importes)
                datos['prima_texto'] = f"{total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
            except:
                datos['prima_texto'] = primer_importe

        # Prima (cerca de "Prima:")
        if 'prima_texto' not in datos:
            match = re.search(r'Prima:\s*\n?\s*([\d\.]+,\d{2})', texto)
            if match:
                datos['prima_texto'] = match.group(1)

        # Premio total en póliza
        match = re.search(r'Premio:\s*\n?\s*([\d\.]+,\d{2})', texto)
        if match:
            datos['premio_texto'] = match.group(1)

        # Importe en recibo: IMPORTE\n$75.626,00
        match = re.search(r'IMPORTE\s*\n?\$\s*([\d\.]+,\d{2})', texto)
        if match:
            datos['importe_recibo'] = match.group(1)
            datos['prima_total'] = match.group(1)

        # Suma asegurada
        match = re.search(r'SUMA ASEGURADA:\s*\$?\s*([\d\.,]+)', texto, re.IGNORECASE)
        if match:
            datos['suma_asegurada_texto'] = match.group(1)

        # Prima total con $ (formato póliza)
        if 'prima_total' not in datos:
            match = re.search(r'\$\s*([\d\.]+)\s*\n.*?Ctas\.?Soc', texto, re.DOTALL)
            if match:
                try:
                    valor_str = match.group(1).replace('.', '')
                    valor = int(valor_str)
                    if 10000 < valor < 10000000:
                        datos['prima_total'] = valor_str
                except:
                    pass

        # ============================================================
        # CUOTAS
        # ============================================================
        # Formato recibo: CUOTA 6/6
        match = re.search(r'CUOTA\s*(\d+)/(\d+)', texto)
        if match:
            datos['cuota_actual'] = int(match.group(1))
            datos['cantidad_cuotas'] = int(match.group(2))

        # Formato póliza: tabla de cuotas
        if 'cantidad_cuotas' not in datos:
            cuotas = re.findall(r'^\s*(\d+)\s+(\d{2}/\d{2}/\d{4})\s+([\d\.]+,\d{2})\s*$', texto, re.MULTILINE)
            if cuotas:
                datos['cantidad_cuotas'] = len(cuotas)
                datos['cuotas_detalle'] = [{'numero': c[0], 'vencimiento': c[1], 'importe': c[2]} for c in cuotas]

        # ============================================================
        # RENOVACION
        # ============================================================
        match = re.search(r'Renueva:\s*(\d{2}:\d{2}:\d{7})', texto)
        if match:
            datos['poliza_renovada'] = match.group(1)

        # ============================================================
        # TIPO DE DOCUMENTO
        # ============================================================
        if 'Nro. Recibo' in texto or 'CUOTA' in texto or 'Fecha Vto.' in texto:
            datos['tipo_documento'] = 'recibo'
        elif 'Ticket - Recibo' in texto or 'ReciboPoliza' in texto:
            datos['tipo_documento'] = 'recibo'
        elif 'polizaCompleta' in texto or 'CONDICIONES PARTICULARES' in texto or 'Emision de Poliza' in texto:
            datos['tipo_documento'] = 'poliza_completa'

        # Motivo del endoso
        match = re.search(r'MOTIVO DEL ENDOSO:\s*([A-Za-záéíóúñ\s]+)', texto)
        if match:
            datos['motivo'] = match.group(1).strip()
        else:
            match = re.search(r'Motivo del Endoso:\s*([A-Za-záéíóúñ\s]+)', texto)
            if match:
                datos['motivo'] = match.group(1).strip()

        # Sección/Ramo
        match = re.search(r'SECCION:\s*\((\d+)\)\s*([A-Za-záéíóúñ]+)', texto)
        if match:
            datos['seccion_codigo'] = match.group(1)
            datos['ramo'] = match.group(2)

        return datos

    def extraer_datos(self, ruta_pdf):
        """Extrae todos los datos disponibles del PDF."""
        texto = self.extraer_texto_pdf(ruta_pdf)
        if not texto:
            return {'error': 'No se pudo leer el PDF', 'confianza': 0}

        # Detectar compania primero
        compania = self.detectar_compania(texto)

        # Inicializar datos
        datos = {
            'compania_detectada': compania,
            'compania_nombre_formal': self.obtener_nombre_compania_formal(),
        }

        # Extraer todos los campos
        campos_a_extraer = [
            ('numero_poliza', None),
            ('fecha_desde', 'fecha_desde_texto'),
            ('fecha_hasta', 'fecha_hasta_texto'),
            ('prima', 'prima_texto'),
            ('suma_asegurada', 'suma_asegurada_texto'),
            ('deducible', 'deducible_texto'),
            ('asegurado_nombre', None),
            ('asegurado_documento', None),
            ('asegurado_direccion', None),
            ('asegurado_telefono', None),
            ('asegurado_email', None),
            ('vehiculo_marca', None),
            ('vehiculo_modelo', None),
            ('vehiculo_anio', None),
            ('vehiculo_patente', None),
            ('vehiculo_chasis', None),
            ('vehiculo_motor', None),
            ('vehiculo_color', None),
            ('vehiculo_uso', None),
            ('inmueble_direccion', None),
            ('inmueble_tipo', None),
            ('inmueble_superficie', None),
            ('productor_nombre', None),
            ('productor_matricula', None),
            ('forma_pago', None),
            ('cantidad_cuotas', None),
        ]

        for campo, campo_texto in campos_a_extraer:
            if campo in self.PATRONES:
                valor = self._buscar_patron(self.PATRONES[campo])
                if valor:
                    if campo_texto:
                        datos[campo_texto] = valor
                    else:
                        datos[campo] = valor
                    self.campos_encontrados.append(campo)
                else:
                    self.campos_no_encontrados.append(campo)

        # Si se detecto compania, intentar con patrones especificos
        if compania and compania in self.COMPANIAS:
            config = self.COMPANIAS[compania]

            # Usar extraccion especifica si esta disponible
            if config.get('extraccion_especifica'):
                if compania == 'liderar':
                    datos_especificos = self._extraer_datos_liderar(texto)
                elif compania == 'berkley':
                    datos_especificos = self._extraer_datos_berkley(texto)
                elif compania == 'mercantil_andina':
                    datos_especificos = self._extraer_datos_mercantil_andina(texto)
                elif compania == 'rio_uruguay':
                    datos_especificos = self._extraer_datos_rio_uruguay(texto)
                else:
                    datos_especificos = {}

                # Sobrescribir datos genericos con los especificos (solo si tienen valor)
                for campo, valor in datos_especificos.items():
                    if valor:
                        datos[campo] = valor
                        if campo not in self.campos_encontrados:
                            self.campos_encontrados.append(campo)

            elif 'patron_poliza' in config:
                poliza_especifica = self._buscar_patron([config['patron_poliza']])
                if poliza_especifica:
                    datos['numero_poliza'] = poliza_especifica

        # Post-procesamiento
        # Parsear fechas
        datos['fecha_vigencia_desde'] = self._parsear_fecha(datos.get('fecha_desde_texto'))
        datos['fecha_vigencia_hasta'] = self._parsear_fecha(datos.get('fecha_hasta_texto'))

        # Parsear montos
        datos['prima_anual'] = self._parsear_monto(datos.get('prima_texto'))
        datos['suma_asegurada'] = self._parsear_monto(datos.get('suma_asegurada_texto'))
        datos['deducible'] = self._parsear_monto(datos.get('deducible_texto'))

        # Limpiar nombre
        datos['asegurado_nombre'] = self._limpiar_nombre(datos.get('asegurado_nombre'))

        # Limpiar documento
        datos['asegurado_documento'] = self._limpiar_documento(datos.get('asegurado_documento'))

        # Limpiar patente
        datos['vehiculo_patente'] = self._limpiar_patente(datos.get('vehiculo_patente'))

        # Parsear año vehiculo
        if datos.get('vehiculo_anio'):
            try:
                datos['vehiculo_anio'] = int(datos['vehiculo_anio'])
            except:
                datos['vehiculo_anio'] = None

        # Parsear cuotas
        if datos.get('cantidad_cuotas'):
            try:
                datos['cantidad_cuotas'] = int(datos['cantidad_cuotas'])
            except:
                datos['cantidad_cuotas'] = None

        # Detectar tipo de seguro
        datos['tipo_seguro'] = self._detectar_tipo_seguro(texto)

        # Detectar tipo de bien asegurado
        datos['bien_asegurado_tipo'] = self._detectar_tipo_bien(datos)

        # Calcular confianza
        datos['confianza'] = self._calcular_confianza(datos)
        datos['campos_detectados'] = len(self.campos_encontrados)
        datos['campos_totales'] = len(campos_a_extraer)
        datos['requiere_revision'] = datos['confianza'] < 0.6

        # Guardar texto completo para referencia (primeros 5000 caracteres)
        datos['texto_muestra'] = texto[:5000] if len(texto) > 5000 else texto

        self.datos_extraidos = datos

        # Validar si es una póliza válida para guardar
        # (se puede llamar con nombre de archivo después)
        es_valida, motivo_rechazo = self.es_poliza_valida(datos)
        datos['es_poliza_valida'] = es_valida
        datos['motivo_rechazo'] = motivo_rechazo

        return datos

    def _detectar_tipo_seguro(self, texto):
        """Detecta el tipo de seguro basado en palabras clave."""
        texto_lower = texto.lower()

        # Contar coincidencias por tipo
        coincidencias = {}
        for tipo, palabras in self.TIPOS_SEGURO.items():
            count = 0
            for palabra in palabras:
                count += texto_lower.count(palabra.lower())
            if count > 0:
                coincidencias[tipo] = count

        # Retornar el tipo con mas coincidencias
        if coincidencias:
            return max(coincidencias, key=coincidencias.get)

        return 'otro'

    def _detectar_tipo_bien(self, datos):
        """Detecta el tipo de bien asegurado."""
        # Si hay datos de vehiculo, es vehiculo
        campos_vehiculo = ['vehiculo_marca', 'vehiculo_modelo', 'vehiculo_patente',
                          'vehiculo_chasis', 'vehiculo_motor']
        if any(datos.get(campo) for campo in campos_vehiculo):
            return 'vehiculo'

        # Si hay datos de inmueble
        campos_inmueble = ['inmueble_direccion', 'inmueble_tipo', 'inmueble_superficie']
        if any(datos.get(campo) for campo in campos_inmueble):
            return 'inmueble'

        # Deducir del tipo de seguro
        tipo_seguro = datos.get('tipo_seguro', '')
        if tipo_seguro in ['auto', 'moto']:
            return 'vehiculo'
        elif tipo_seguro in ['hogar', 'comercio', 'consorcio', 'incendio']:
            return 'inmueble'
        elif tipo_seguro in ['vida', 'salud', 'accidentes', 'art']:
            return 'persona'

        return None

    def _calcular_confianza(self, datos):
        """Calcula el nivel de confianza de la extraccion (0-1)."""
        # Campos con diferentes pesos
        campos_criticos = {
            'numero_poliza': 0.20,
            'fecha_vigencia_desde': 0.15,
            'fecha_vigencia_hasta': 0.15,
            'prima_anual': 0.15,
            'asegurado_nombre': 0.15,
        }

        campos_importantes = {
            'asegurado_documento': 0.05,
            'tipo_seguro': 0.05,
            'suma_asegurada': 0.05,
        }

        confianza = 0.0

        # Sumar pesos de campos criticos encontrados
        for campo, peso in campos_criticos.items():
            if datos.get(campo):
                confianza += peso

        # Sumar pesos de campos importantes
        for campo, peso in campos_importantes.items():
            if datos.get(campo):
                confianza += peso

        # Bonus por compania detectada
        if datos.get('compania_detectada'):
            confianza = min(1.0, confianza + 0.05)

        return round(confianza, 2)

    def es_poliza_valida(self, datos=None, nombre_archivo=None, dev_options=None):
        """
        Determina si el documento es una póliza/recibo válido para guardar.

        Criterios de RECHAZO (devuelve False):
        - Constancias de adhesión (tienen poca información útil)
        - Documentos de condiciones generales/anexos
        - Sin asegurado identificable
        - Sin número de póliza válido
        - Confianza muy baja (<45%)
        - Texto de disclaimer como "asegurado"

        Args:
            datos: Diccionario con datos extraídos
            nombre_archivo: Nombre original del archivo
            dev_options: Opciones de desarrollo para bypass de validaciones

        Returns:
            tuple: (es_valida: bool, motivo_rechazo: str or None)
        """
        if datos is None:
            datos = self.datos_extraidos

        # Opciones de desarrollo (permiten bypass de validaciones)
        dev_options = dev_options or {}
        permitir_facturas = dev_options.get('permitir_facturas', False)
        permitir_sin_asegurado = dev_options.get('permitir_sin_asegurado', False)
        permitir_sin_poliza = dev_options.get('permitir_sin_poliza', False)
        permitir_sin_fechas = dev_options.get('permitir_sin_fechas', False)
        permitir_baja_confianza = dev_options.get('permitir_baja_confianza', False)
        permitir_condiciones_grales = dev_options.get('permitir_condiciones_grales', False)
        permitir_servicios = dev_options.get('permitir_servicios', False)

        nombre_archivo = nombre_archivo or ""
        nombre_lower = nombre_archivo.lower()

        # ============================================================
        # RECHAZAR POR NOMBRE DE ARCHIVO
        # ============================================================
        # Constancias de adhesión tienen poca info útil
        if 'constanciapolizaadhesion' in nombre_lower.replace(' ', ''):
            return (False, "constancia_adhesion")

        # Rechazar por nombre de archivo que indica servicio no seguro
        # (a menos que permitir_servicios esté activo)
        if not permitir_servicios:
            servicios_en_nombre = ['starlink', 'netflix', 'spotify', 'amazon', 'mercadolibre',
                                   'telecom', 'telefonica', 'movistar', 'personal', 'claro',
                                   'edenor', 'edesur', 'metrogas', 'aysa', 'recibo', 'factura']
            for servicio in servicios_en_nombre:
                if servicio in nombre_lower:
                    return (False, f"nombre_archivo_{servicio}")

        # ============================================================
        # RECHAZAR FACTURAS Y COMPROBANTES FISCALES
        # ============================================================
        texto_muestra = datos.get('texto_muestra', '')
        texto_lower = texto_muestra.lower()

        # Detectar CAE (Código de Autorización Electrónica de AFIP)
        tiene_cae = bool(re.search(r'c\.?a\.?e\.?\s*n[º°]?\s*:?\s*\d{10,}', texto_lower))

        # Detectar palabras clave de facturas/comprobantes
        palabras_factura = [
            'factura',
            'comprobante autorizado',
            'administración federal',
            'afip',
            'iva contenido',
            'iva 21%',
            'iva 10.5%',
            'importe neto',
            'régimen de transparencia fiscal',
            'fecha vto cae',
            'cuit del emisor',
            'nota de crédito',
            'nota de débito',
            'recibo de pago',
            'comprobante de pago',
            'orden de compra',
        ]
        contador_factura = sum(1 for p in palabras_factura if p in texto_lower)

        # Si tiene CAE o señales de factura, rechazar
        # (a menos que permitir_facturas esté activo)
        if not permitir_facturas:
            if tiene_cae:
                return (False, "factura_cae")
            if contador_factura >= 2:  # Reducido de 3 a 2
                return (False, "factura_comprobante")

        # Detectar servicios NO aseguradores conocidos (en contenido)
        # (a menos que permitir_servicios esté activo)
        if not permitir_servicios:
            servicios_no_seguros = [
                'starlink',
                'enacom',
                'ente nacional de comunicaciones',
                'telecom argentina',
                'telefonica',
                'movistar',
                'personal.com',
                'claro argentina',
                'edenor',
                'edesur',
                'metrogas',
                'aysa',
                'netflix',
                'spotify',
                'amazon prime',
                'mercado pago',
                'mercadolibre',
                'rapipago',
                'pago fácil',
            ]
            for servicio in servicios_no_seguros:
                if servicio in texto_lower:
                    return (False, f"servicio_no_seguro_{servicio}")

        # ============================================================
        # VERIFICAR QUE SEA DOCUMENTO DE SEGURO (debe tener palabras clave)
        # ============================================================
        palabras_seguro = [
            'póliza', 'poliza', 'asegurado', 'aseguradora', 'compañía de seguros',
            'cobertura', 'siniestro', 'prima', 'vigencia', 'endoso',
            'suma asegurada', 'franquicia', 'beneficiario', 'tomador',
            'superintendencia de seguros', 'ssn', 'riesgo asegurado'
        ]
        contador_seguro = sum(1 for p in palabras_seguro if p in texto_lower)

        # Si no tiene ninguna palabra de seguro, probablemente no es póliza
        if contador_seguro == 0:
            return (False, "sin_palabras_seguro")

        # ============================================================
        # RECHAZAR POR CONFIANZA MUY BAJA
        # (a menos que permitir_baja_confianza esté activo)
        # ============================================================
        confianza = datos.get('confianza', 0)
        if confianza < 0.45 and not permitir_baja_confianza:
            return (False, f"confianza_baja_{int(confianza*100)}%")

        # ============================================================
        # RECHAZAR SI NO HAY ASEGURADO VÁLIDO
        # (a menos que permitir_sin_asegurado esté activo)
        # ============================================================
        if not permitir_sin_asegurado:
            asegurado = datos.get('asegurado_nombre')
            if not asegurado:
                return (False, "sin_asegurado")

            # Rechazar si el "asegurado" es texto de disclaimer/legal
            textos_invalidos = [
                'podrán solicitar información',
                'superintendencia de seguros',
                'asegurador no',
                'clausula',
                'condiciones generales',
                'si no reclama',
                'fecha vto',
                'general lopez',  # Dirección, no nombre
            ]
            asegurado_lower = asegurado.lower()
            for texto in textos_invalidos:
                if texto in asegurado_lower:
                    return (False, f"asegurado_invalido_{texto[:20]}")

            # Asegurado muy corto (menos de 4 caracteres reales)
            if len(asegurado.replace(' ', '').replace(',', '')) < 4:
                return (False, "asegurado_muy_corto")

        # ============================================================
        # RECHAZAR SI NO HAY NÚMERO DE PÓLIZA VÁLIDO
        # (a menos que permitir_sin_poliza esté activo)
        # ============================================================
        if not permitir_sin_poliza:
            numero_poliza = datos.get('numero_poliza')
            if not numero_poliza:
                return (False, "sin_numero_poliza")

            # Rechazar si el número de póliza es claramente inválido
            poliza_invalida = [
                'ha',  # Error común de extracción
                'seccion',
                'n/a',
            ]
            if numero_poliza.lower() in poliza_invalida:
                return (False, f"poliza_invalida_{numero_poliza}")

            # Número de póliza muy corto (menos de 5 caracteres)
            poliza_limpia = numero_poliza.replace(':', '').replace('-', '')
            if len(poliza_limpia) < 5:
                return (False, "poliza_muy_corta")

        # ============================================================
        # RECHAZAR SI NO HAY AL MENOS UNA FECHA DE VIGENCIA
        # (a menos que permitir_sin_fechas esté activo)
        # ============================================================
        if not permitir_sin_fechas:
            tiene_fecha_desde = datos.get('fecha_desde_texto') or datos.get('fecha_vigencia_desde')
            tiene_fecha_hasta = datos.get('fecha_hasta_texto') or datos.get('fecha_vigencia_hasta')

            if not tiene_fecha_desde and not tiene_fecha_hasta:
                return (False, "sin_fechas_vigencia")

        # ============================================================
        # RECHAZAR DOCUMENTOS DE CONDICIONES GENERALES
        # (a menos que permitir_condiciones_grales esté activo)
        # ============================================================
        if not permitir_condiciones_grales:
            # (texto_muestra ya fue definido arriba en la sección de facturas)

            # Señales de documento de condiciones generales (muchos disclaimers)
            señales_condiciones = [
                'CONDICIONES GENERALES',
                'CLAUSULAS GENERALES',
                'ANEXO DE COBERTURA',
                'el presente contrato se rige',
                'la aseguradora no responderá',
            ]

            contador_señales = 0
            for señal in señales_condiciones:
                if señal.lower() in texto_muestra.lower():
                    contador_señales += 1

            # Si tiene muchas señales de condiciones generales, rechazar
            if contador_señales >= 2:
                return (False, "documento_condiciones_generales")

        # ============================================================
        # DOCUMENTO VÁLIDO
        # ============================================================
        return (True, None)

    def datos_para_poliza(self, datos=None):
        """Devuelve solo los campos que van directo al modelo PolizaCliente."""
        if datos is None:
            datos = self.datos_extraidos

        return {
            'numero_poliza': datos.get('numero_poliza'),
            'tipo_seguro': datos.get('tipo_seguro'),
            'fecha_vigencia_desde': datos.get('fecha_vigencia_desde'),
            'fecha_vigencia_hasta': datos.get('fecha_vigencia_hasta'),
            'prima_anual': datos.get('prima_anual'),
            'suma_asegurada': datos.get('suma_asegurada'),
            'deducible': datos.get('deducible'),
            'asegurado_nombre': datos.get('asegurado_nombre'),
            'asegurado_documento': datos.get('asegurado_documento'),
            'asegurado_direccion': datos.get('asegurado_direccion'),
            'asegurado_telefono': datos.get('asegurado_telefono'),
            'asegurado_email': datos.get('asegurado_email'),
            'bien_asegurado_tipo': datos.get('bien_asegurado_tipo'),
            'vehiculo_marca': datos.get('vehiculo_marca'),
            'vehiculo_modelo': datos.get('vehiculo_modelo'),
            'vehiculo_anio': datos.get('vehiculo_anio'),
            'vehiculo_patente': datos.get('vehiculo_patente'),
            'vehiculo_chasis': datos.get('vehiculo_chasis'),
            'vehiculo_motor': datos.get('vehiculo_motor'),
            'vehiculo_color': datos.get('vehiculo_color'),
            'vehiculo_uso': datos.get('vehiculo_uso'),
            'inmueble_direccion': datos.get('inmueble_direccion'),
            'inmueble_tipo': datos.get('inmueble_tipo'),
            'inmueble_superficie': datos.get('inmueble_superficie'),
            'forma_pago': datos.get('forma_pago'),
            'cantidad_cuotas': datos.get('cantidad_cuotas'),
            'productor_nombre': datos.get('productor_nombre'),
            'confianza_extraccion': datos.get('confianza'),
            'datos_extraidos': json.dumps(datos, default=str),
            'requiere_revision': datos.get('requiere_revision', True),
        }

    def resumen_extraccion(self):
        """Genera un resumen de la extraccion para mostrar al usuario."""
        datos = self.datos_extraidos

        resumen = {
            'exito': datos.get('confianza', 0) > 0,
            'confianza': datos.get('confianza', 0),
            'confianza_porcentaje': int(datos.get('confianza', 0) * 100),
            'compania': datos.get('compania_nombre_formal') or 'No detectada',
            'tipo_seguro': datos.get('tipo_seguro', 'No detectado'),
            'campos_detectados': datos.get('campos_detectados', 0),
            'campos_totales': datos.get('campos_totales', 0),
            'requiere_revision': datos.get('requiere_revision', True),
            'nivel': self._nivel_confianza(datos.get('confianza', 0)),
        }

        return resumen

    def _nivel_confianza(self, confianza):
        """Retorna el nivel de confianza como texto."""
        if confianza >= 0.8:
            return 'alto'
        elif confianza >= 0.5:
            return 'medio'
        else:
            return 'bajo'

    def extraer_datos_estructurado(self, ruta_pdf, archivo_info=None):
        """
        Extrae datos del PDF en formato estructurado con metadata por campo.

        Este método es la base del sistema de extracción predictiva mejorable.
        Cada campo incluye:
        - valor: El valor procesado/limpio
        - texto_original: El texto tal como fue extraído del PDF
        - confianza: Nivel de confianza de la extracción (0-1)
        - fuente: Identificador del patrón que lo extrajo

        Args:
            ruta_pdf: Ruta al archivo PDF
            archivo_info: dict opcional con metadata del archivo (id, nombre, remitente, etc.)

        Returns:
            dict estructurado con secciones: meta, confianza, compania, cliente, poliza, vehiculo, inmueble, productor
        """
        from datetime import datetime as dt

        # Extraer datos base usando el método existente
        datos_raw = self.extraer_datos(ruta_pdf)

        if 'error' in datos_raw:
            return {
                'error': datos_raw['error'],
                'meta': {'timestamp_extraccion': dt.now().isoformat()}
            }

        # Intentar aplicar aprendizaje
        aprendizaje_aplicado = []
        try:
            from app.extractor.aprendizaje import obtener_motor
            motor = obtener_motor()
        except:
            motor = None

        def crear_campo(valor, texto_original=None, confianza=0.5, fuente='regex'):
            """Helper para crear estructura de campo con metadata."""
            if valor is None:
                return {'valor': None, 'confianza': 0, 'texto_original': None, 'fuente': None}

            valor_final = valor
            confianza_final = confianza

            # Intentar buscar corrección aprendida
            if motor and valor and isinstance(valor, str):
                try:
                    # El campo se pasa como contexto para buscar correcciones específicas
                    correccion = motor.buscar_correccion(fuente, valor)
                    if correccion:
                        valor_final = correccion.get('valor_corregido', valor)
                        confianza_final = correccion.get('confianza', confianza)
                        aprendizaje_aplicado.append({
                            'campo': fuente,
                            'tipo': correccion.get('metodo', 'correccion'),
                            'transformacion': correccion.get('transformacion'),
                            'original': valor,
                            'aplicado': valor_final
                        })
                except:
                    pass

            return {
                'valor': valor_final,
                'confianza': confianza_final,
                'texto_original': texto_original if texto_original else valor,
                'fuente': fuente
            }

        # Construir estructura de respuesta
        resultado = {
            'meta': {
                'archivo_id': archivo_info.get('id') if archivo_info else None,
                'archivo_nombre': archivo_info.get('nombre') if archivo_info else None,
                'archivo_fecha': archivo_info.get('fecha') if archivo_info else None,
                'remitente': archivo_info.get('remitente') if archivo_info else None,
                'asunto': archivo_info.get('asunto') if archivo_info else None,
                'timestamp_extraccion': dt.now().isoformat(),
                'version_extractor': '2.0'
            },
            'confianza': {
                'global': datos_raw.get('confianza', 0),
                'porcentaje': int(datos_raw.get('confianza', 0) * 100),
                'nivel': self._nivel_confianza(datos_raw.get('confianza', 0)),
                'campos_detectados': datos_raw.get('campos_detectados', 0),
                'campos_totales': datos_raw.get('campos_totales', 0)
            },
            'compania': {
                'detectada': datos_raw.get('compania_detectada'),
                'nombre_formal': datos_raw.get('compania_nombre_formal'),
                'id_sugerida': None  # Se llena en el servicio
            },
            'cliente': {
                'nombre': crear_campo(
                    datos_raw.get('asegurado_nombre'),
                    confianza=0.85 if datos_raw.get('asegurado_nombre') else 0,
                    fuente='asegurado_nombre'
                ),
                'documento': crear_campo(
                    datos_raw.get('asegurado_documento'),
                    confianza=0.95 if datos_raw.get('asegurado_documento') else 0,
                    fuente='asegurado_documento'
                ),
                'telefono': crear_campo(
                    datos_raw.get('asegurado_telefono'),
                    confianza=0.70 if datos_raw.get('asegurado_telefono') else 0,
                    fuente='asegurado_telefono'
                ),
                'email': crear_campo(
                    datos_raw.get('asegurado_email'),
                    confianza=0.90 if datos_raw.get('asegurado_email') else 0,
                    fuente='asegurado_email'
                ),
                'direccion': crear_campo(
                    datos_raw.get('asegurado_direccion'),
                    confianza=0.75 if datos_raw.get('asegurado_direccion') else 0,
                    fuente='asegurado_direccion'
                )
            },
            'poliza': {
                'numero_poliza': crear_campo(
                    datos_raw.get('numero_poliza'),
                    confianza=0.95 if datos_raw.get('numero_poliza') else 0,
                    fuente='numero_poliza'
                ),
                'tipo_seguro': crear_campo(
                    datos_raw.get('tipo_seguro'),
                    confianza=0.80 if datos_raw.get('tipo_seguro') else 0,
                    fuente='tipo_seguro'
                ),
                'fecha_vigencia_desde': crear_campo(
                    datos_raw.get('fecha_vigencia_desde').isoformat() if datos_raw.get('fecha_vigencia_desde') else None,
                    texto_original=datos_raw.get('fecha_desde_texto'),
                    confianza=0.90 if datos_raw.get('fecha_vigencia_desde') else 0,
                    fuente='fecha_desde'
                ),
                'fecha_vigencia_hasta': crear_campo(
                    datos_raw.get('fecha_vigencia_hasta').isoformat() if datos_raw.get('fecha_vigencia_hasta') else None,
                    texto_original=datos_raw.get('fecha_hasta_texto'),
                    confianza=0.90 if datos_raw.get('fecha_vigencia_hasta') else 0,
                    fuente='fecha_hasta'
                ),
                'prima_anual': crear_campo(
                    float(datos_raw.get('prima_anual')) if datos_raw.get('prima_anual') else None,
                    texto_original=datos_raw.get('prima_texto'),
                    confianza=0.85 if datos_raw.get('prima_anual') else 0,
                    fuente='prima'
                ),
                'suma_asegurada': crear_campo(
                    float(datos_raw.get('suma_asegurada')) if datos_raw.get('suma_asegurada') else None,
                    texto_original=datos_raw.get('suma_asegurada_texto'),
                    confianza=0.80 if datos_raw.get('suma_asegurada') else 0,
                    fuente='suma_asegurada'
                ),
                'deducible': crear_campo(
                    float(datos_raw.get('deducible')) if datos_raw.get('deducible') else None,
                    texto_original=datos_raw.get('deducible_texto'),
                    confianza=0.75 if datos_raw.get('deducible') else 0,
                    fuente='deducible'
                ),
                'forma_pago': crear_campo(
                    datos_raw.get('forma_pago'),
                    confianza=0.70 if datos_raw.get('forma_pago') else 0,
                    fuente='forma_pago'
                ),
                'cantidad_cuotas': crear_campo(
                    datos_raw.get('cantidad_cuotas'),
                    confianza=0.70 if datos_raw.get('cantidad_cuotas') else 0,
                    fuente='cantidad_cuotas'
                ),
                'bien_asegurado_tipo': crear_campo(
                    datos_raw.get('bien_asegurado_tipo'),
                    confianza=0.85 if datos_raw.get('bien_asegurado_tipo') else 0,
                    fuente='bien_asegurado_tipo'
                )
            },
            'vehiculo': None,
            'inmueble': None,
            'productor': {
                'nombre': crear_campo(
                    datos_raw.get('productor_nombre'),
                    confianza=0.70 if datos_raw.get('productor_nombre') else 0,
                    fuente='productor_nombre'
                ),
                'matricula': crear_campo(
                    datos_raw.get('productor_matricula'),
                    confianza=0.65 if datos_raw.get('productor_matricula') else 0,
                    fuente='productor_matricula'
                ),
                'telefono': {'valor': None, 'confianza': 0, 'texto_original': None, 'fuente': None},
                'email': {'valor': None, 'confianza': 0, 'texto_original': None, 'fuente': None}
            },
            'aprendizaje_aplicado': aprendizaje_aplicado,
            'es_poliza_valida': datos_raw.get('es_poliza_valida', False),
            'motivo_rechazo': datos_raw.get('motivo_rechazo'),
            'requiere_revision': datos_raw.get('requiere_revision', True)
        }

        # Agregar datos de vehículo si hay
        if datos_raw.get('bien_asegurado_tipo') == 'vehiculo' or datos_raw.get('tipo_seguro') in ['auto', 'moto']:
            resultado['vehiculo'] = {
                'marca': crear_campo(
                    datos_raw.get('vehiculo_marca'),
                    confianza=0.90 if datos_raw.get('vehiculo_marca') else 0,
                    fuente='vehiculo_marca'
                ),
                'modelo': crear_campo(
                    datos_raw.get('vehiculo_modelo'),
                    confianza=0.85 if datos_raw.get('vehiculo_modelo') else 0,
                    fuente='vehiculo_modelo'
                ),
                'anio': crear_campo(
                    datos_raw.get('vehiculo_anio'),
                    confianza=0.95 if datos_raw.get('vehiculo_anio') else 0,
                    fuente='vehiculo_anio'
                ),
                'patente': crear_campo(
                    datos_raw.get('vehiculo_patente'),
                    confianza=0.95 if datos_raw.get('vehiculo_patente') else 0,
                    fuente='vehiculo_patente'
                ),
                'chasis': crear_campo(
                    datos_raw.get('vehiculo_chasis'),
                    confianza=0.90 if datos_raw.get('vehiculo_chasis') else 0,
                    fuente='vehiculo_chasis'
                ),
                'motor': crear_campo(
                    datos_raw.get('vehiculo_motor'),
                    confianza=0.85 if datos_raw.get('vehiculo_motor') else 0,
                    fuente='vehiculo_motor'
                ),
                'color': crear_campo(
                    datos_raw.get('vehiculo_color'),
                    confianza=0.75 if datos_raw.get('vehiculo_color') else 0,
                    fuente='vehiculo_color'
                ),
                'uso': crear_campo(
                    datos_raw.get('vehiculo_uso'),
                    confianza=0.70 if datos_raw.get('vehiculo_uso') else 0,
                    fuente='vehiculo_uso'
                )
            }

        # Agregar datos de inmueble si hay
        if datos_raw.get('bien_asegurado_tipo') == 'inmueble' or datos_raw.get('tipo_seguro') in ['hogar', 'incendio', 'comercio']:
            resultado['inmueble'] = {
                'direccion': crear_campo(
                    datos_raw.get('inmueble_direccion'),
                    confianza=0.80 if datos_raw.get('inmueble_direccion') else 0,
                    fuente='inmueble_direccion'
                ),
                'tipo': crear_campo(
                    datos_raw.get('inmueble_tipo'),
                    confianza=0.75 if datos_raw.get('inmueble_tipo') else 0,
                    fuente='inmueble_tipo'
                ),
                'superficie': crear_campo(
                    datos_raw.get('inmueble_superficie'),
                    confianza=0.70 if datos_raw.get('inmueble_superficie') else 0,
                    fuente='inmueble_superficie'
                )
            }

        return resultado


def extraer_datos_poliza(ruta_pdf, aplicar_aprendizaje=True):
    """
    Funcion de conveniencia para extraer datos de un PDF.

    Args:
        ruta_pdf: Ruta al archivo PDF
        aplicar_aprendizaje: Si True, aplica correcciones aprendidas

    Returns:
        dict con datos extraídos para el modelo PolizaCliente
    """
    extractor = ExtractorDatosPoliza()
    datos = extractor.extraer_datos(ruta_pdf)
    datos_poliza = extractor.datos_para_poliza(datos)

    # Aplicar correcciones aprendidas si está habilitado
    if aplicar_aprendizaje:
        try:
            from app.extractor.aprendizaje import buscar_correccion

            for campo, valor in datos_poliza.items():
                if valor and isinstance(valor, str):
                    correccion = buscar_correccion(campo, valor)
                    if correccion:
                        datos_poliza[campo] = correccion['valor_corregido']
        except ImportError:
            pass  # Módulo de aprendizaje no disponible
        except Exception as e:
            logger.warning(f"Error aplicando aprendizaje: {e}")

    return datos_poliza


def extraer_y_validar_poliza(ruta_pdf, nombre_archivo=None, dev_options=None):
    """
    Extrae datos de un PDF y valida si es una póliza válida para guardar.

    Args:
        ruta_pdf: Ruta al archivo PDF
        nombre_archivo: Nombre original del archivo (para detectar constancias, etc.)
        dev_options: Opciones de desarrollo para bypass de validaciones

    Returns:
        dict con:
            - es_valida: bool
            - motivo_rechazo: str or None
            - datos: dict con todos los datos extraídos
            - datos_poliza: dict con campos para el modelo PolizaCliente
            - texto: str con el texto completo del PDF (para detección de compañía)
    """
    extractor = ExtractorDatosPoliza()

    # Extraer texto primero (para retornarlo junto con los datos)
    texto_pdf = extractor.extraer_texto_pdf(ruta_pdf)

    # Extraer datos
    datos = extractor.extraer_datos(ruta_pdf)

    # Re-validar con nombre de archivo si se proporciona
    if nombre_archivo:
        es_valida, motivo = extractor.es_poliza_valida(datos, nombre_archivo, dev_options)
        datos['es_poliza_valida'] = es_valida
        datos['motivo_rechazo'] = motivo

    return {
        'es_valida': datos.get('es_poliza_valida', False),
        'motivo_rechazo': datos.get('motivo_rechazo'),
        'datos': datos,
        'datos_poliza': extractor.datos_para_poliza(datos) if datos.get('es_poliza_valida') else None,
        'resumen': extractor.resumen_extraccion(),
        'texto': texto_pdf or '',  # Texto completo para detección de compañía
    }
