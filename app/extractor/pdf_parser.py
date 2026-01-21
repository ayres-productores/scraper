"""
Extractor de datos de polizas desde archivos PDF.
Utiliza PyMuPDF para extraer texto y patrones regex para identificar datos.
"""

import re
import fitz  # PyMuPDF
from decimal import Decimal
from datetime import datetime
import json


class ExtractorDatosPoliza:
    """Extrae datos estructurados de PDFs de polizas de seguros."""

    # Patrones genericos para datos comunes
    PATRONES = {
        # Numeros de poliza (varios formatos)
        'numero_poliza': [
            r'[Pp][oó]liza\s*(?:[Nn][oº°]?\.?\s*)?:?\s*([A-Z0-9\-\/]+)',
            r'[Nn][oº°]?\s*[Pp][oó]liza:?\s*([A-Z0-9\-\/]+)',
            r'[Cc]ontrato\s*[Nn][oº°]?\.?:?\s*([A-Z0-9\-\/]+)',
            r'[Cc]ertificado\s*[Nn][oº°]?\.?:?\s*([A-Z0-9\-\/]+)',
        ],

        # Fechas de vigencia
        'fecha_desde': [
            r'[Vv]igencia\s*[Dd]esde:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ii]nicio\s*[Vv]igencia:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ff]echa\s*[Ii]nicio:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Dd]esde\s*el:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        ],
        'fecha_hasta': [
            r'[Vv]igencia\s*[Hh]asta:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ff]in\s*[Vv]igencia:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Ff]echa\s*[Ff]in:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Hh]asta\s*el:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'[Vv]encimiento:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        ],

        # Prima
        'prima': [
            r'[Pp]rima\s*[Tt]otal:?\s*\$?\s*([\d\.,]+)',
            r'[Pp]rima\s*[Aa]nual:?\s*\$?\s*([\d\.,]+)',
            r'[Pp]remio:?\s*\$?\s*([\d\.,]+)',
            r'[Tt]otal\s*a\s*[Pp]agar:?\s*\$?\s*([\d\.,]+)',
        ],

        # Suma asegurada
        'suma_asegurada': [
            r'[Ss]uma\s*[Aa]segurada:?\s*\$?\s*([\d\.,]+)',
            r'[Cc]apital\s*[Aa]segurado:?\s*\$?\s*([\d\.,]+)',
            r'[Mm]onto\s*[Aa]segurado:?\s*\$?\s*([\d\.,]+)',
        ],

        # Datos del asegurado
        'asegurado_nombre': [
            r'[Aa]segurado:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)',
            r'[Tt]omador:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)',
            r'[Cc]ontratante:?\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)',
        ],
        'asegurado_documento': [
            r'[Dd][Nn][Ii]:?\s*(\d{7,8})',
            r'[Cc][Uu][Ii][Tt]:?\s*(\d{2}\-?\d{8}\-?\d{1})',
            r'[Cc][Uu][Ii][Ll]:?\s*(\d{2}\-?\d{8}\-?\d{1})',
            r'[Dd]ocumento:?\s*(\d{7,11})',
        ],

        # Vehiculo
        'vehiculo_marca': [
            r'[Mm]arca:?\s*([A-Za-z0-9]+)',
        ],
        'vehiculo_modelo': [
            r'[Mm]odelo:?\s*([A-Za-z0-9\s\-]+)',
        ],
        'vehiculo_anio': [
            r'[Aa][ñn]o:?\s*((?:19|20)\d{2})',
            r'[Aa][ñn]o\s*[Ff]ab(?:ricaci[oó]n)?:?\s*((?:19|20)\d{2})',
        ],
        'vehiculo_patente': [
            r'[Pp]atente:?\s*([A-Z]{2,3}\s?\d{3}\s?[A-Z]{0,2})',
            r'[Dd]ominio:?\s*([A-Z]{2,3}\s?\d{3}\s?[A-Z]{0,2})',
            r'[Pp]laca:?\s*([A-Z]{2,3}\s?\d{3}\s?[A-Z]{0,2})',
        ],
        'vehiculo_chasis': [
            r'[Cc]hasis:?\s*([A-Z0-9]{17})',
            r'[Vv][Ii][Nn]:?\s*([A-Z0-9]{17})',
        ],
        'vehiculo_motor': [
            r'[Mm]otor:?\s*([A-Z0-9\-]+)',
        ],
    }

    # Companias conocidas y sus patrones especificos
    COMPANIAS = {
        'mapfre': {
            'patrones_nombre': ['mapfre', 'MAPFRE'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{4}[\-\/]\d+)',
        },
        'la_caja': {
            'patrones_nombre': ['la caja', 'LA CAJA', 'caja seguros'],
            'patron_poliza': r'[Pp][oó]liza\s*[Nn][oº°]?\s*(\d+)',
        },
        'federacion_patronal': {
            'patrones_nombre': ['federacion patronal', 'FEDERACION PATRONAL', 'fed. patronal'],
            'patron_poliza': r'[Pp][oó]liza:?\s*([A-Z]?\d{6,})',
        },
        'sancor': {
            'patrones_nombre': ['sancor', 'SANCOR'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{7,})',
        },
        'allianz': {
            'patrones_nombre': ['allianz', 'ALLIANZ'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{10,})',
        },
        'zurich': {
            'patrones_nombre': ['zurich', 'ZURICH'],
            'patron_poliza': r'[Pp][oó]liza:?\s*([A-Z0-9]{8,})',
        },
        'sura': {
            'patrones_nombre': ['sura', 'SURA', 'royal & sun'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{8,})',
        },
        'la_segunda': {
            'patrones_nombre': ['la segunda', 'LA SEGUNDA'],
            'patron_poliza': r'[Pp][oó]liza:?\s*(\d{6,})',
        },
    }

    def __init__(self):
        self.texto_completo = ""
        self.datos_extraidos = {}
        self.confianza = 0.0
        self.compania_detectada = None

    def extraer_texto_pdf(self, ruta_pdf):
        """Extrae todo el texto de un archivo PDF."""
        try:
            doc = fitz.open(ruta_pdf)
            texto = ""
            for pagina in doc:
                texto += pagina.get_text()
            doc.close()
            self.texto_completo = texto
            return texto
        except Exception as e:
            print(f"Error al leer PDF {ruta_pdf}: {e}")
            return ""

    def detectar_compania(self, texto=None):
        """Detecta la compania aseguradora del texto."""
        if texto is None:
            texto = self.texto_completo

        texto_lower = texto.lower()

        for nombre_clave, config in self.COMPANIAS.items():
            for patron in config['patrones_nombre']:
                if patron.lower() in texto_lower:
                    self.compania_detectada = nombre_clave
                    return nombre_clave

        return None

    def _buscar_patron(self, patrones, texto=None):
        """Busca el primer match de una lista de patrones."""
        if texto is None:
            texto = self.texto_completo

        for patron in patrones:
            match = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()
        return None

    def _parsear_fecha(self, texto_fecha):
        """Convierte texto de fecha a objeto date."""
        if not texto_fecha:
            return None

        formatos = ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y']
        for fmt in formatos:
            try:
                return datetime.strptime(texto_fecha, fmt).date()
            except:
                continue
        return None

    def _parsear_monto(self, texto_monto):
        """Convierte texto de monto a Decimal."""
        if not texto_monto:
            return None

        try:
            # Limpiar: quitar puntos de miles, cambiar coma por punto
            limpio = texto_monto.replace('.', '').replace(',', '.')
            return Decimal(limpio)
        except:
            return None

    def extraer_datos(self, ruta_pdf):
        """Extrae todos los datos disponibles del PDF."""
        texto = self.extraer_texto_pdf(ruta_pdf)
        if not texto:
            return {}

        # Detectar compania
        compania = self.detectar_compania(texto)

        # Extraer con patrones genericos
        datos = {
            'numero_poliza': self._buscar_patron(self.PATRONES['numero_poliza']),
            'fecha_desde_texto': self._buscar_patron(self.PATRONES['fecha_desde']),
            'fecha_hasta_texto': self._buscar_patron(self.PATRONES['fecha_hasta']),
            'prima_texto': self._buscar_patron(self.PATRONES['prima']),
            'suma_asegurada_texto': self._buscar_patron(self.PATRONES['suma_asegurada']),
            'asegurado_nombre': self._buscar_patron(self.PATRONES['asegurado_nombre']),
            'asegurado_documento': self._buscar_patron(self.PATRONES['asegurado_documento']),
            'vehiculo_marca': self._buscar_patron(self.PATRONES['vehiculo_marca']),
            'vehiculo_modelo': self._buscar_patron(self.PATRONES['vehiculo_modelo']),
            'vehiculo_anio': self._buscar_patron(self.PATRONES['vehiculo_anio']),
            'vehiculo_patente': self._buscar_patron(self.PATRONES['vehiculo_patente']),
            'vehiculo_chasis': self._buscar_patron(self.PATRONES['vehiculo_chasis']),
            'vehiculo_motor': self._buscar_patron(self.PATRONES['vehiculo_motor']),
            'compania_detectada': compania,
        }

        # Si se detecto compania, intentar con patrones especificos
        if compania and compania in self.COMPANIAS:
            config = self.COMPANIAS[compania]
            if 'patron_poliza' in config:
                poliza_especifica = self._buscar_patron([config['patron_poliza']])
                if poliza_especifica:
                    datos['numero_poliza'] = poliza_especifica

        # Parsear fechas y montos
        datos['fecha_vigencia_desde'] = self._parsear_fecha(datos.get('fecha_desde_texto'))
        datos['fecha_vigencia_hasta'] = self._parsear_fecha(datos.get('fecha_hasta_texto'))
        datos['prima_anual'] = self._parsear_monto(datos.get('prima_texto'))
        datos['suma_asegurada'] = self._parsear_monto(datos.get('suma_asegurada_texto'))

        # Parsear año vehiculo
        if datos.get('vehiculo_anio'):
            try:
                datos['vehiculo_anio'] = int(datos['vehiculo_anio'])
            except:
                datos['vehiculo_anio'] = None

        # Detectar tipo de seguro
        datos['tipo_seguro'] = self._detectar_tipo_seguro(texto)

        # Detectar tipo de bien asegurado
        datos['bien_asegurado_tipo'] = self._detectar_tipo_bien(datos)

        # Calcular confianza
        datos['confianza'] = self._calcular_confianza(datos)

        self.datos_extraidos = datos
        return datos

    def _detectar_tipo_seguro(self, texto):
        """Detecta el tipo de seguro basado en palabras clave."""
        texto_lower = texto.lower()

        tipos = {
            'auto': ['automotor', 'automovil', 'vehiculo', 'auto ', 'carro'],
            'moto': ['motocicleta', 'moto ', 'ciclomotor'],
            'hogar': ['hogar', 'vivienda', 'casa ', 'departamento', 'domicilio'],
            'vida': ['vida', 'fallecimiento', 'muerte', 'sepelio'],
            'salud': ['salud', 'medico', 'hospitalario', 'cobertura medica'],
            'accidentes': ['accidentes personales', 'ap ', 'accidente personal'],
            'responsabilidad': ['responsabilidad civil', 'rc ', 'terceros'],
            'comercio': ['comercio', 'negocio', 'local comercial', 'pyme'],
            'transporte': ['transporte', 'carga', 'mercaderia', 'flete'],
            'caucion': ['caucion', 'fianza', 'garantia'],
        }

        for tipo, palabras in tipos.items():
            for palabra in palabras:
                if palabra in texto_lower:
                    return tipo

        return 'otro'

    def _detectar_tipo_bien(self, datos):
        """Detecta el tipo de bien asegurado."""
        # Si hay datos de vehiculo, es vehiculo
        if any([datos.get('vehiculo_marca'), datos.get('vehiculo_modelo'),
                datos.get('vehiculo_patente'), datos.get('vehiculo_chasis')]):
            return 'vehiculo'

        tipo_seguro = datos.get('tipo_seguro', '')
        if tipo_seguro in ['auto', 'moto']:
            return 'vehiculo'
        elif tipo_seguro in ['hogar', 'comercio']:
            return 'inmueble'
        elif tipo_seguro in ['vida', 'salud', 'accidentes']:
            return 'persona'

        return None

    def _calcular_confianza(self, datos):
        """Calcula el nivel de confianza de la extraccion (0-1)."""
        campos_importantes = [
            'numero_poliza',
            'fecha_vigencia_desde',
            'fecha_vigencia_hasta',
            'prima_anual',
            'asegurado_nombre',
        ]

        encontrados = sum(1 for campo in campos_importantes if datos.get(campo))
        confianza = encontrados / len(campos_importantes)

        # Bonus por compania detectada
        if datos.get('compania_detectada'):
            confianza = min(1.0, confianza + 0.1)

        return round(confianza, 2)

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
            'asegurado_nombre': datos.get('asegurado_nombre'),
            'asegurado_documento': datos.get('asegurado_documento'),
            'bien_asegurado_tipo': datos.get('bien_asegurado_tipo'),
            'vehiculo_marca': datos.get('vehiculo_marca'),
            'vehiculo_modelo': datos.get('vehiculo_modelo'),
            'vehiculo_anio': datos.get('vehiculo_anio'),
            'vehiculo_patente': datos.get('vehiculo_patente'),
            'vehiculo_chasis': datos.get('vehiculo_chasis'),
            'vehiculo_motor': datos.get('vehiculo_motor'),
            'confianza_extraccion': datos.get('confianza'),
            'datos_extraidos': json.dumps(datos, default=str),
            'requiere_revision': datos.get('confianza', 0) < 0.6,
        }


def extraer_datos_poliza(ruta_pdf):
    """Funcion de conveniencia para extraer datos de un PDF."""
    extractor = ExtractorDatosPoliza()
    datos = extractor.extraer_datos(ruta_pdf)
    return extractor.datos_para_poliza(datos)
