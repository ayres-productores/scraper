"""
Cargador de reglas entrenadas.
Lee las reglas exportadas desde el Entrenador de Descarga y las hace
disponibles para el sistema de estrategias.
"""

import json
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ReglasEntrenadas:
    """
    Singleton que carga y gestiona las reglas exportadas desde el entrenador.
    Las reglas se recargan automáticamente si el archivo cambia.
    """

    _instancia = None
    _ultima_carga = None
    _mtime_archivo = None

    def __new__(cls):
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._inicializado = False
        return cls._instancia

    def __init__(self):
        if self._inicializado:
            # Verificar si el archivo cambió para recargar
            self._verificar_recarga()
            return
        self._inicializado = True
        self._palabras_poliza: List[str] = []
        self._palabras_excluir: List[str] = []
        self._servicios_excluidos: List[str] = []
        self._estadisticas: Dict = {}
        self._fecha_exportacion: Optional[str] = None
        self._cargar_reglas()

    def _obtener_ruta_reglas(self) -> str:
        """Obtiene la ruta del archivo de reglas entrenadas."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, 'config', 'reglas_entrenadas.json')

    def _verificar_recarga(self):
        """Verifica si el archivo cambió y recarga si es necesario."""
        ruta = self._obtener_ruta_reglas()
        if os.path.exists(ruta):
            mtime = os.path.getmtime(ruta)
            if self._mtime_archivo is None or mtime > self._mtime_archivo:
                logger.info("[ReglasEntrenadas] Archivo modificado, recargando...")
                self._cargar_reglas()

    def _cargar_reglas(self):
        """Carga las reglas desde el archivo JSON."""
        ruta = self._obtener_ruta_reglas()

        if not os.path.exists(ruta):
            logger.info("[ReglasEntrenadas] No hay archivo de reglas entrenadas")
            return

        try:
            self._mtime_archivo = os.path.getmtime(ruta)

            with open(ruta, 'r', encoding='utf-8') as f:
                data = json.load(f)

            validacion = data.get('validacion_global', {})

            self._palabras_poliza = validacion.get('palabras_poliza', [])
            self._palabras_excluir = validacion.get('palabras_excluir', [])
            self._servicios_excluidos = validacion.get('servicios_excluidos', [])
            self._estadisticas = data.get('estadisticas', {})
            self._fecha_exportacion = data.get('fecha_exportacion')
            self._ultima_carga = datetime.now()

            logger.info(f"[ReglasEntrenadas] Cargadas: "
                        f"{len(self._palabras_poliza)} palabras póliza, "
                        f"{len(self._palabras_excluir)} exclusiones, "
                        f"{len(self._servicios_excluidos)} servicios excluidos")

        except json.JSONDecodeError as e:
            logger.error(f"[ReglasEntrenadas] Error parseando JSON: {e}")
        except Exception as e:
            logger.error(f"[ReglasEntrenadas] Error cargando reglas: {e}")

    @property
    def palabras_poliza(self) -> List[str]:
        """Palabras que indican que el PDF es una póliza."""
        self._verificar_recarga()
        return self._palabras_poliza

    @property
    def palabras_excluir(self) -> List[str]:
        """Palabras que indican que el PDF NO es una póliza."""
        self._verificar_recarga()
        return self._palabras_excluir

    @property
    def servicios_excluidos(self) -> List[str]:
        """Servicios no aseguradores (Netflix, Telecom, etc.)."""
        self._verificar_recarga()
        return self._servicios_excluidos

    @property
    def tiene_reglas(self) -> bool:
        """Indica si hay reglas cargadas."""
        return bool(self._palabras_poliza or self._palabras_excluir)

    @property
    def estadisticas(self) -> Dict:
        """Estadísticas del entrenamiento."""
        return self._estadisticas

    @property
    def fecha_exportacion(self) -> Optional[str]:
        """Fecha de la última exportación."""
        return self._fecha_exportacion

    def validar_con_reglas(self, texto: str) -> tuple[bool, str, Dict]:
        """
        Valida un texto usando las reglas entrenadas.

        Args:
            texto: Texto extraído del PDF

        Returns:
            Tuple (es_valido, motivo, detalles)
        """
        if not self.tiene_reglas:
            # Sin reglas, no podemos validar
            return True, "sin_reglas_entrenadas", {}

        texto_lower = texto.lower()
        detalles = {
            'palabras_poliza_encontradas': [],
            'palabras_excluir_encontradas': [],
            'servicios_encontrados': []
        }

        # Buscar palabras de exclusión primero (prioridad alta)
        for palabra in self._palabras_excluir:
            if palabra.lower() in texto_lower:
                detalles['palabras_excluir_encontradas'].append(palabra)

        # Buscar servicios excluidos
        for servicio in self._servicios_excluidos:
            if servicio.lower() in texto_lower:
                detalles['servicios_encontrados'].append(servicio)

        # Si hay exclusiones fuertes, rechazar
        if detalles['servicios_encontrados']:
            return False, f"servicio_no_asegurador: {detalles['servicios_encontrados'][0]}", detalles

        # Buscar palabras de póliza
        for palabra in self._palabras_poliza:
            if palabra.lower() in texto_lower:
                detalles['palabras_poliza_encontradas'].append(palabra)

        # Evaluar resultado
        tiene_exclusiones = len(detalles['palabras_excluir_encontradas']) > 0
        tiene_indicadores_poliza = len(detalles['palabras_poliza_encontradas']) > 0

        # Si tiene muchas exclusiones y pocas palabras de póliza, rechazar
        if tiene_exclusiones and not tiene_indicadores_poliza:
            return False, f"documento_excluido: {detalles['palabras_excluir_encontradas'][0]}", detalles

        # Si tiene palabras de póliza, aceptar
        if tiene_indicadores_poliza:
            return True, "contiene_palabras_poliza", detalles

        # Sin indicadores claros, dejar pasar (para no ser muy restrictivo)
        return True, "sin_indicadores_claros", detalles

    def recargar(self):
        """Fuerza recarga de las reglas."""
        self._mtime_archivo = None
        self._cargar_reglas()

    @classmethod
    def reset(cls):
        """Resetea el singleton (útil para tests)."""
        cls._instancia = None


# ============================================================================
# Funciones de conveniencia (API pública)
# ============================================================================

def obtener_reglas() -> ReglasEntrenadas:
    """Obtiene la instancia de reglas entrenadas."""
    return ReglasEntrenadas()


def validar_pdf_con_reglas_entrenadas(texto: str) -> tuple[bool, str, Dict]:
    """
    Valida un texto de PDF usando las reglas del entrenador.

    Args:
        texto: Texto extraído del PDF

    Returns:
        Tuple (es_valido, motivo, detalles)
    """
    return ReglasEntrenadas().validar_con_reglas(texto)


def hay_reglas_entrenadas() -> bool:
    """Indica si hay reglas entrenadas disponibles."""
    return ReglasEntrenadas().tiene_reglas
