"""
Detector de Compania desde Contenido del PDF

Este modulo analiza el texto extraido de un PDF para determinar
la compania aseguradora usando multiples estrategias.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger('app.extractor.detector_compania')


@dataclass
class ResultadoDeteccion:
    """Resultado de la deteccion de compania."""
    compania_id: Optional[str]  # ID interno (ej: 'liderar')
    nombre_formal: Optional[str]  # Nombre para mostrar (ej: 'Liderar')
    confianza: float  # 0.0 a 1.0
    metodo: str  # Metodo que detecto (cuit, url, nombre, etc.)
    coincidencia: Optional[str]  # Texto que coincidio


class DetectorCompaniaPDF:
    """
    Detecta la compania aseguradora analizando el contenido del PDF.

    Estrategias de deteccion (en orden de prioridad):
    1. CUIT - Buscar CUIT conocido de la aseguradora
    2. URLs - Buscar dominios web en el contenido
    3. Nombre Formal - Buscar nombre completo de la compania
    4. Encabezados - Buscar encabezados tipicos
    5. Fallback - Usar dominio del remitente del email
    """

    # Pesos de confianza por metodo
    PESOS = {
        'cuit': 0.95,
        'url': 0.90,
        'encabezado': 0.85,
        'nombre_texto': 0.80,
        'palabra_unica': 0.70,
        'dominio_email': 0.60,
        'no_detectado': 0.0
    }

    def __init__(self):
        self.patrones = self._cargar_patrones()

    def _cargar_patrones(self) -> Dict[str, Any]:
        """Carga los patrones desde el archivo JSON."""
        ruta_json = os.path.join(
            os.path.dirname(__file__),
            'config',
            'patrones_companias.json'
        )

        try:
            with open(ruta_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('companias', {})
        except Exception as e:
            logger.warning(f"Error cargando patrones: {e}")
            return {}

    def detectar(self, texto_pdf: str, remitente: str = None) -> ResultadoDeteccion:
        """
        Detecta la compania analizando el texto del PDF.

        Args:
            texto_pdf: Texto extraido del PDF
            remitente: Email del remitente (opcional, para fallback)

        Returns:
            ResultadoDeteccion con la compania detectada
        """
        if not texto_pdf:
            return ResultadoDeteccion(
                compania_id=None,
                nombre_formal=None,
                confianza=0.0,
                metodo='sin_texto',
                coincidencia=None
            )

        # Normalizar texto para busqueda
        texto_upper = texto_pdf.upper()
        texto_lower = texto_pdf.lower()

        # Lista de resultados de cada estrategia
        resultados = []

        # 1. Buscar por CUIT (mas confiable)
        resultado_cuit = self._detectar_por_cuit(texto_pdf)
        if resultado_cuit:
            resultados.append(resultado_cuit)

        # 2. Buscar por URL
        resultado_url = self._detectar_por_url(texto_lower)
        if resultado_url:
            resultados.append(resultado_url)

        # 3. Buscar por encabezado
        resultado_encabezado = self._detectar_por_encabezado(texto_upper)
        if resultado_encabezado:
            resultados.append(resultado_encabezado)

        # 4. Buscar por nombre en texto
        resultado_nombre = self._detectar_por_nombre(texto_upper)
        if resultado_nombre:
            resultados.append(resultado_nombre)

        # 5. Fallback: dominio del remitente
        if remitente:
            resultado_dominio = self._detectar_por_dominio(remitente)
            if resultado_dominio:
                resultados.append(resultado_dominio)

        # Retornar el de mayor confianza
        if resultados:
            mejor = max(resultados, key=lambda r: r.confianza)
            return mejor

        return ResultadoDeteccion(
            compania_id=None,
            nombre_formal=None,
            confianza=0.0,
            metodo='no_detectado',
            coincidencia=None
        )

    def _detectar_por_cuit(self, texto: str) -> Optional[ResultadoDeteccion]:
        """Busca CUITs conocidos en el texto."""
        for comp_id, config in self.patrones.items():
            patrones = config.get('patrones', {})
            cuits = patrones.get('cuits', [])

            for cuit in cuits:
                # Buscar CUIT con guiones o sin ellos
                if cuit in texto:
                    return ResultadoDeteccion(
                        compania_id=comp_id,
                        nombre_formal=config.get('nombre_formal'),
                        confianza=self.PESOS['cuit'],
                        metodo='cuit',
                        coincidencia=cuit
                    )

        return None

    def _detectar_por_url(self, texto_lower: str) -> Optional[ResultadoDeteccion]:
        """Busca URLs/dominios conocidos en el texto."""
        for comp_id, config in self.patrones.items():
            patrones = config.get('patrones', {})
            urls = patrones.get('urls', [])

            for url in urls:
                # Buscar el dominio en cualquier contexto
                if url.lower() in texto_lower:
                    return ResultadoDeteccion(
                        compania_id=comp_id,
                        nombre_formal=config.get('nombre_formal'),
                        confianza=self.PESOS['url'],
                        metodo='url',
                        coincidencia=url
                    )

        return None

    def _detectar_por_encabezado(self, texto_upper: str) -> Optional[ResultadoDeteccion]:
        """Busca encabezados formales de companias."""
        for comp_id, config in self.patrones.items():
            patrones = config.get('patrones', {})
            encabezados = patrones.get('encabezados', [])

            for encabezado in encabezados:
                if encabezado.upper() in texto_upper:
                    return ResultadoDeteccion(
                        compania_id=comp_id,
                        nombre_formal=config.get('nombre_formal'),
                        confianza=self.PESOS['encabezado'],
                        metodo='encabezado',
                        coincidencia=encabezado
                    )

        return None

    def _detectar_por_nombre(self, texto_upper: str) -> Optional[ResultadoDeteccion]:
        """Busca nombres de companias en el texto."""
        mejores_coincidencias = []

        for comp_id, config in self.patrones.items():
            patrones = config.get('patrones', {})
            nombres = patrones.get('nombres_texto', [])

            for nombre in nombres:
                nombre_upper = nombre.upper()
                # Usar word boundary para evitar falsos positivos
                patron = r'\b' + re.escape(nombre_upper) + r'\b'
                match = re.search(patron, texto_upper)

                if match:
                    # Dar mas peso a nombres mas largos (mas especificos)
                    peso_ajustado = self.PESOS['nombre_texto'] + (len(nombre) * 0.001)
                    mejores_coincidencias.append(ResultadoDeteccion(
                        compania_id=comp_id,
                        nombre_formal=config.get('nombre_formal'),
                        confianza=min(peso_ajustado, 0.89),  # No superar URL
                        metodo='nombre_texto',
                        coincidencia=nombre
                    ))

        if mejores_coincidencias:
            return max(mejores_coincidencias, key=lambda r: r.confianza)

        return None

    def _detectar_por_dominio(self, remitente: str) -> Optional[ResultadoDeteccion]:
        """Fallback: detecta por dominio del email remitente."""
        if not remitente:
            return None

        # Extraer dominio
        match = re.search(r'@([a-zA-Z0-9.-]+)', remitente.lower())
        if not match:
            return None

        dominio = match.group(1)

        # Buscar en patrones
        for comp_id, config in self.patrones.items():
            patrones = config.get('patrones', {})
            urls = patrones.get('urls', [])

            for url in urls:
                if url.lower() in dominio or dominio in url.lower():
                    return ResultadoDeteccion(
                        compania_id=comp_id,
                        nombre_formal=config.get('nombre_formal'),
                        confianza=self.PESOS['dominio_email'],
                        metodo='dominio_email',
                        coincidencia=dominio
                    )

        return None

    def detectar_todas(self, texto_pdf: str, remitente: str = None) -> List[ResultadoDeteccion]:
        """
        Retorna todas las companias detectadas, ordenadas por confianza.
        Util para debugging o para mostrar alternativas al usuario.
        """
        if not texto_pdf:
            return []

        texto_upper = texto_pdf.upper()
        texto_lower = texto_pdf.lower()

        resultados = []
        companias_vistas = set()

        # Ejecutar todas las estrategias
        for comp_id, config in self.patrones.items():
            patrones = config.get('patrones', {})

            # CUIT
            for cuit in patrones.get('cuits', []):
                if cuit in texto_pdf and comp_id not in companias_vistas:
                    resultados.append(ResultadoDeteccion(
                        compania_id=comp_id,
                        nombre_formal=config.get('nombre_formal'),
                        confianza=self.PESOS['cuit'],
                        metodo='cuit',
                        coincidencia=cuit
                    ))
                    companias_vistas.add(comp_id)

            # URL
            for url in patrones.get('urls', []):
                if url.lower() in texto_lower and comp_id not in companias_vistas:
                    resultados.append(ResultadoDeteccion(
                        compania_id=comp_id,
                        nombre_formal=config.get('nombre_formal'),
                        confianza=self.PESOS['url'],
                        metodo='url',
                        coincidencia=url
                    ))
                    companias_vistas.add(comp_id)

            # Nombre
            for nombre in patrones.get('nombres_texto', []):
                if nombre.upper() in texto_upper and comp_id not in companias_vistas:
                    resultados.append(ResultadoDeteccion(
                        compania_id=comp_id,
                        nombre_formal=config.get('nombre_formal'),
                        confianza=self.PESOS['nombre_texto'],
                        metodo='nombre_texto',
                        coincidencia=nombre
                    ))
                    companias_vistas.add(comp_id)

        # Ordenar por confianza descendente
        resultados.sort(key=lambda r: r.confianza, reverse=True)

        return resultados

    def obtener_nombre_formal(self, compania_id: str) -> Optional[str]:
        """Obtiene el nombre formal de una compania por su ID."""
        config = self.patrones.get(compania_id)
        if config:
            return config.get('nombre_formal')
        return None


# Instancia global para reusar
_detector_instance = None

def obtener_detector() -> DetectorCompaniaPDF:
    """Obtiene la instancia singleton del detector."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = DetectorCompaniaPDF()
    return _detector_instance


def detectar_compania_en_pdf(texto_pdf: str, remitente: str = None) -> ResultadoDeteccion:
    """
    Funcion de conveniencia para detectar compania.

    Args:
        texto_pdf: Texto extraido del PDF
        remitente: Email del remitente (opcional)

    Returns:
        ResultadoDeteccion
    """
    detector = obtener_detector()
    return detector.detectar(texto_pdf, remitente)
