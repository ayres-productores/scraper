"""
Registro central de estrategias. Carga la configuración y selecciona
la estrategia apropiada según el remitente del correo.
"""

import json
import os
import logging
from typing import Dict, Optional, List

from app.extractor.companias.estrategia_base import EstrategiaExtraccion, ConfigCompania
from app.extractor.companias.estrategia_adjunto import EstrategiaAdjunto
from app.extractor.companias.estrategia_enlace_html import EstrategiaEnlaceHTML

logger = logging.getLogger(__name__)


class RegistroEstrategias:
    """
    Singleton que gestiona las estrategias de extracción.
    Carga la configuración de companias.json y proporciona
    la estrategia correcta según el remitente.
    """

    _instancia = None
    _config_path_override = None

    def __new__(cls):
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._inicializado = False
        return cls._instancia

    def __init__(self):
        if self._inicializado:
            return
        self._inicializado = True
        self._companias: Dict[str, ConfigCompania] = {}
        self._estrategias: Dict[str, EstrategiaExtraccion] = {}
        self._dominios_map: Dict[str, str] = {}  # dominio -> id_compania
        self._default_id: str = 'generica'
        self._cargar_configuracion()

    def _obtener_ruta_config(self) -> str:
        """Determina la ruta del archivo de configuración."""
        if self._config_path_override:
            return self._config_path_override

        # Ruta por defecto: app/extractor/config/companias.json
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, 'config', 'companias.json')

    def _cargar_configuracion(self):
        """Carga companias.json y construye las estructuras internas."""
        config_path = self._obtener_ruta_config()

        if not os.path.exists(config_path):
            logger.warning(f"[Estrategias] No se encontró {config_path}, usando configuración por defecto")
            self._crear_config_default()
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"[Estrategias] Error parseando JSON: {e}")
            self._crear_config_default()
            return
        except Exception as e:
            logger.error(f"[Estrategias] Error leyendo configuración: {e}")
            self._crear_config_default()
            return

        self._default_id = config.get('default_compania', 'generica')

        # Procesar cada compañía
        for id_comp, datos in config.get('companias', {}).items():
            if not datos.get('activa', True):
                logger.info(f"[Estrategias] Compañía '{id_comp}' desactivada, omitiendo")
                continue

            try:
                self._registrar_compania(id_comp, datos)
            except Exception as e:
                logger.error(f"[Estrategias] Error registrando '{id_comp}': {e}")

        logger.info(f"[Estrategias] Cargadas {len(self._companias)} compañías, "
                    f"{len(self._dominios_map)} dominios mapeados")

    def _registrar_compania(self, id_comp: str, datos: Dict):
        """Registra una compañía individual."""
        tipo = datos.get('tipo_extraccion', 'adjunto')

        # Determinar configuración específica según tipo
        if tipo == 'enlace_html':
            config_esp = datos.get('config_enlaces', {})
        else:
            config_esp = datos.get('config_adjuntos', {})

        compania = ConfigCompania(
            id=id_comp,
            nombre=datos.get('nombre', id_comp),
            dominios=datos.get('dominios', []),
            tipo_extraccion=tipo,
            filtros_imap=datos.get('filtros_imap', {}),
            limites=datos.get('limites', {}),
            validacion_pdf=datos.get('validacion_pdf', {}),
            extraccion_datos=datos.get('extraccion_datos', {}),
            renombrado=datos.get('renombrado', {}),
            config_especifica=config_esp
        )

        self._companias[id_comp] = compania

        # Crear estrategia según tipo
        if tipo == 'enlace_html':
            self._estrategias[id_comp] = EstrategiaEnlaceHTML(compania)
        else:
            self._estrategias[id_comp] = EstrategiaAdjunto(compania)

        # Mapear dominios a esta compañía
        for dominio in compania.dominios:
            self._dominios_map[dominio.lower()] = id_comp

        logger.debug(f"[Estrategias] Registrada: {compania.nombre} ({tipo}), "
                     f"dominios: {compania.dominios}")

    def _crear_config_default(self):
        """Crea configuración mínima por defecto."""
        compania = ConfigCompania(
            id='generica',
            nombre='Compañía Genérica',
            dominios=[],
            tipo_extraccion='adjunto',
            filtros_imap={},
            limites={'dias_max_antiguedad': 365},
            validacion_pdf={'palabras_cualquiera': ['PÓLIZA', 'POLIZA', 'ASEGURADO']},
            extraccion_datos={},
            renombrado={'formato': '{compania}_{fecha}.pdf'},
            config_especifica={}
        )
        self._companias['generica'] = compania
        self._estrategias['generica'] = EstrategiaAdjunto(compania)
        logger.info("[Estrategias] Usando configuración por defecto (genérica)")

    def obtener_estrategia(self, remitente: str) -> EstrategiaExtraccion:
        """
        Obtiene la estrategia apropiada según el remitente.

        Args:
            remitente: Dirección de email del remitente

        Returns:
            Estrategia correspondiente (o la default si no hay match)
        """
        if not remitente:
            return self._estrategias.get(self._default_id)

        remitente_lower = remitente.lower()

        # Buscar dominio que coincida
        for dominio, id_comp in self._dominios_map.items():
            if dominio in remitente_lower:
                estrategia = self._estrategias.get(id_comp)
                if estrategia:
                    return estrategia

        # Retornar estrategia default
        return self._estrategias.get(self._default_id)

    def obtener_compania(self, remitente: str) -> Optional[ConfigCompania]:
        """Obtiene la configuración de compañía según el remitente."""
        if not remitente:
            return self._companias.get(self._default_id)

        remitente_lower = remitente.lower()

        for dominio, id_comp in self._dominios_map.items():
            if dominio in remitente_lower:
                return self._companias.get(id_comp)

        return self._companias.get(self._default_id)

    def obtener_compania_por_id(self, id_compania: str) -> Optional[ConfigCompania]:
        """Obtiene una compañía por su ID."""
        return self._companias.get(id_compania)

    def listar_companias(self) -> Dict[str, str]:
        """Retorna diccionario {id: nombre} de compañías activas."""
        return {id_c: c.nombre for id_c, c in self._companias.items()}

    def listar_dominios(self) -> List[str]:
        """Retorna lista de todos los dominios configurados."""
        return list(self._dominios_map.keys())

    def recargar_configuracion(self):
        """Recarga la configuración desde el archivo JSON."""
        logger.info("[Estrategias] Recargando configuración...")
        self._companias.clear()
        self._estrategias.clear()
        self._dominios_map.clear()
        self._cargar_configuracion()

    @classmethod
    def set_config_path(cls, path: str):
        """Permite especificar una ruta alternativa para el JSON."""
        cls._config_path_override = path
        # Si ya hay instancia, forzar recarga
        if cls._instancia:
            cls._instancia._inicializado = False
            cls._instancia.__init__()

    @classmethod
    def reset(cls):
        """Resetea el singleton (útil para tests)."""
        cls._instancia = None
        cls._config_path_override = None


# ============================================================================
# Funciones de conveniencia (API pública del módulo)
# ============================================================================

def obtener_estrategia(remitente: str) -> EstrategiaExtraccion:
    """
    Obtiene la estrategia de extracción apropiada para un remitente.

    Args:
        remitente: Email del remitente

    Returns:
        Instancia de EstrategiaExtraccion (Adjunto o EnlaceHTML)
    """
    return RegistroEstrategias().obtener_estrategia(remitente)


def obtener_compania(remitente: str) -> Optional[ConfigCompania]:
    """
    Obtiene la configuración de compañía para un remitente.

    Args:
        remitente: Email del remitente

    Returns:
        ConfigCompania o None
    """
    return RegistroEstrategias().obtener_compania(remitente)


def listar_companias() -> Dict[str, str]:
    """Lista todas las compañías configuradas."""
    return RegistroEstrategias().listar_companias()


def recargar_configuracion():
    """Recarga la configuración desde el archivo JSON."""
    RegistroEstrategias().recargar_configuracion()
