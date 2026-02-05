"""
Clase base abstracta para estrategias de extracción de PDFs.
Define la interfaz común que todas las estrategias deben implementar.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime


@dataclass
class ResultadoExtraccion:
    """Resultado de una extracción de PDF."""
    exito: bool
    contenido: Optional[bytes] = None
    nombre_sugerido: Optional[str] = None
    datos_extraidos: Optional[Dict] = None
    error: Optional[str] = None
    metadata: Optional[Dict] = field(default_factory=dict)


@dataclass
class ConfigCompania:
    """Configuración cargada de una compañía."""
    id: str
    nombre: str
    dominios: List[str]
    tipo_extraccion: str  # 'adjunto' o 'enlace_html'
    filtros_imap: Dict
    limites: Dict
    validacion_pdf: Dict
    extraccion_datos: Dict
    renombrado: Dict
    config_especifica: Dict  # config_adjuntos o config_enlaces


class EstrategiaExtraccion(ABC):
    """
    Clase base abstracta para estrategias de extracción.

    Cada compañía puede tener una estrategia diferente para:
    - Filtrar correos relevantes
    - Extraer PDFs (adjuntos o enlaces)
    - Validar que el PDF sea una póliza
    - Extraer datos del PDF
    - Renombrar el archivo final
    """

    def __init__(self, config: ConfigCompania):
        self.config = config
        self.nombre_compania = config.nombre
        self.id_compania = config.id

    @abstractmethod
    def extraer_pdfs(self, mensaje_email, html_content: Optional[str] = None) -> List[ResultadoExtraccion]:
        """
        Extrae PDFs de un mensaje de correo.

        Args:
            mensaje_email: Objeto email.message.Message
            html_content: Contenido HTML del correo (para estrategias de enlace)

        Returns:
            Lista de ResultadoExtraccion con los PDFs encontrados
        """
        pass

    def filtrar_correo(self, remitente: str, asunto: str, fecha_correo: datetime) -> Tuple[bool, str]:
        """
        Determina si un correo debe ser procesado.

        Returns:
            Tuple (procesar: bool, motivo: str)
        """
        # Verificar antigüedad
        dias_antiguedad = (datetime.now() - fecha_correo).days
        max_dias = self.config.limites.get('dias_max_antiguedad', 365)
        if dias_antiguedad > max_dias:
            return False, f"Correo muy antiguo ({dias_antiguedad} días > {max_dias})"

        # Verificar dominio del remitente (si la compañía tiene dominios específicos)
        if self.config.dominios:
            remitente_lower = remitente.lower()
            if not any(dom.lower() in remitente_lower for dom in self.config.dominios):
                return False, "Dominio no coincide"

        # Verificar palabras clave en asunto
        filtros = self.config.filtros_imap
        if filtros.get('subject_keywords'):
            asunto_lower = asunto.lower()
            if not any(kw.lower() in asunto_lower for kw in filtros['subject_keywords']):
                return False, "Asunto no contiene palabras clave"

        # Verificar exclusiones en asunto
        if filtros.get('subject_excluir'):
            asunto_lower = asunto.lower()
            if any(excl.lower() in asunto_lower for excl in filtros['subject_excluir']):
                return False, "Asunto contiene palabra excluida"

        return True, "OK"

    def validar_pdf(self, contenido: bytes, nombre_archivo: str) -> Tuple[bool, str, Dict]:
        """
        Valida si el contenido es una póliza válida.

        La validación usa dos capas:
        1. Reglas entrenadas (si están disponibles) - del Entrenador de Descarga
        2. Reglas específicas de la compañía - de companias.json

        Returns:
            Tuple (es_valido: bool, motivo: str, datos_extraidos: dict)
        """
        import tempfile
        import os

        validacion = self.config.validacion_pdf

        # Verificar que sea PDF válido (magic bytes)
        if contenido[:4] != b'%PDF':
            return False, "No es un archivo PDF válido", {}

        # Guardar temporalmente para analizar
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(contenido)
            tmp_path = tmp.name

        try:
            # Intentar extraer texto del PDF
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(tmp_path)
                texto = ""
                for pagina in doc:
                    texto += pagina.get_text()
                doc.close()
            except Exception as e:
                return False, f"Error leyendo PDF: {str(e)}", {}

            texto_upper = texto.upper()

            # ================================================================
            # CAPA 1: Validación con reglas entrenadas (del Entrenador)
            # ================================================================
            try:
                from app.extractor.companias.reglas_entrenadas import (
                    hay_reglas_entrenadas,
                    validar_pdf_con_reglas_entrenadas
                )

                if hay_reglas_entrenadas():
                    es_valido, motivo_reglas, detalles_reglas = validar_pdf_con_reglas_entrenadas(texto)

                    if not es_valido:
                        # Las reglas entrenadas rechazan este PDF
                        return False, f"[Reglas entrenadas] {motivo_reglas}", detalles_reglas
            except ImportError:
                # Sin módulo de reglas entrenadas, continuar con validación normal
                pass

            # ================================================================
            # CAPA 2: Validación con reglas específicas de la compañía
            # ================================================================

            # Verificar longitud mínima
            min_caracteres = validacion.get('min_caracteres', 100)
            if len(texto) < min_caracteres:
                return False, f"PDF muy corto ({len(texto)} < {min_caracteres} caracteres)", {}

            # Palabras requeridas (todas deben estar)
            palabras_req = validacion.get('palabras_requeridas', [])
            for palabra in palabras_req:
                if palabra.upper() not in texto_upper:
                    return False, f"Falta palabra requerida: {palabra}", {}

            # Palabras cualquiera (al menos una debe estar)
            palabras_cualquiera = validacion.get('palabras_cualquiera', [])
            if palabras_cualquiera:
                if not any(p.upper() in texto_upper for p in palabras_cualquiera):
                    return False, "No contiene ninguna palabra clave esperada", {}

            # Palabras excluidas (ninguna debe estar)
            palabras_excl = validacion.get('palabras_excluir', [])
            for palabra in palabras_excl:
                if palabra.upper() in texto_upper:
                    return False, f"Contiene palabra excluida: {palabra}", {}

            # PDF válido - extraer datos básicos
            datos = {
                'texto_extraido': texto[:5000],  # Primeros 5000 chars
                'paginas': doc.page_count if 'doc' in dir() else 1,
                'compania_detectada': self.nombre_compania
            }

            return True, "Póliza válida", datos

        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass

    def generar_nombre_archivo(self, datos: Dict, fecha_correo: datetime,
                               remitente: str = '', asunto: str = '') -> str:
        """
        Genera el nombre final del archivo según la configuración.
        """
        config_ren = self.config.renombrado
        formato = config_ren.get('formato', '{compania}_{fecha}.pdf')
        max_len = config_ren.get('max_longitud_nombre', 100)

        # Preparar campos disponibles
        campos = {
            'asegurado': self._sanitizar(str(datos.get('asegurado_nombre', ''))[:40]),
            'patente': str(datos.get('vehiculo_patente', '')).replace(' ', ''),
            'bien': datos.get('vehiculo_patente') or datos.get('tipo_seguro', ''),
            'numero_poliza': str(datos.get('numero_poliza', '')),
            'fecha': fecha_correo.strftime('%Y%m%d'),
            'remitente': self._sanitizar(remitente.split('<')[0].strip()[:30]),
            'asunto': self._sanitizar(asunto[:40]),
            'compania': self._sanitizar(self.nombre_compania[:20])
        }

        # Aplicar formato
        nombre = formato
        for campo, valor in campos.items():
            nombre = nombre.replace(f'{{{campo}}}', valor or '')

        # Limpiar caracteres repetidos y espacios
        nombre = nombre.replace('__', '_').replace('  ', ' ').strip('_ ')
        if not nombre.endswith('.pdf'):
            nombre += '.pdf'

        # Si el nombre quedó muy corto o vacío, usar fallback
        if len(nombre) < 10:
            nombre = f"{self._sanitizar(self.nombre_compania)}_{fecha_correo.strftime('%Y%m%d_%H%M%S')}.pdf"

        return nombre[:max_len]

    def _sanitizar(self, texto: str) -> str:
        """Elimina caracteres inválidos para nombres de archivo."""
        if not texto:
            return ''
        invalidos = '<>:"/\\|?*\n\r\t'
        for c in invalidos:
            texto = texto.replace(c, '_')
        return texto.strip()

    def obtener_criterios_imap(self) -> List[str]:
        """
        Retorna criterios IMAP adicionales para esta compañía.
        Se usan para filtrar en el servidor antes de descargar.
        """
        criterios = []
        filtros = self.config.filtros_imap

        # Filtro FROM por dominios
        if filtros.get('filtrar_por_from', True) and self.config.dominios:
            if len(self.config.dominios) == 1:
                criterios.append(f'FROM "{self.config.dominios[0]}"')
            elif len(self.config.dominios) > 1:
                # IMAP OR anidado para múltiples dominios
                from_parts = [f'FROM "{dom}"' for dom in self.config.dominios]
                or_clause = from_parts[-1]
                for part in reversed(from_parts[:-1]):
                    or_clause = f'OR {part} ({or_clause})'
                criterios.append(f'({or_clause})')

        return criterios

    def __repr__(self):
        return f"<{self.__class__.__name__} '{self.nombre_compania}'>"
