"""
Módulo de estrategias de extracción por compañía.

Este módulo implementa el patrón Strategy para manejar diferentes
formas de extraer PDFs según la compañía de seguros.

Uso:
    from app.extractor.companias import obtener_estrategia, obtener_compania

    estrategia = obtener_estrategia(remitente_email)
    resultados = estrategia.extraer_pdfs(mensaje)
"""

from app.extractor.companias.estrategia_base import (
    EstrategiaExtraccion,
    ConfigCompania,
    ResultadoExtraccion
)
from app.extractor.companias.estrategia_adjunto import EstrategiaAdjunto
from app.extractor.companias.estrategia_enlace_html import EstrategiaEnlaceHTML
from app.extractor.companias.registro_estrategias import (
    RegistroEstrategias,
    obtener_estrategia,
    obtener_compania
)
from app.extractor.companias.reglas_entrenadas import (
    ReglasEntrenadas,
    obtener_reglas,
    validar_pdf_con_reglas_entrenadas,
    hay_reglas_entrenadas
)

__all__ = [
    'EstrategiaExtraccion',
    'ConfigCompania',
    'ResultadoExtraccion',
    'EstrategiaAdjunto',
    'EstrategiaEnlaceHTML',
    'RegistroEstrategias',
    'obtener_estrategia',
    'obtener_compania',
    # Reglas entrenadas
    'ReglasEntrenadas',
    'obtener_reglas',
    'validar_pdf_con_reglas_entrenadas',
    'hay_reglas_entrenadas',
]
