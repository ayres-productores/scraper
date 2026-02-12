"""
Gestor de Reglas - Manipula los archivos JSON de configuración.
- reglas_entrenadas.json: Palabras clave globales
- companias.json: Reglas específicas por compañía
"""

import json
import logging
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('app.extractor.gestor_reglas')

# Rutas a los archivos de configuración
CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'config')
REGLAS_FILE = os.path.join(CONFIG_DIR, 'reglas_entrenadas.json')
COMPANIAS_FILE = os.path.join(CONFIG_DIR, 'companias.json')


def _crear_backup(filepath: str) -> str:
    """Crea backup del archivo antes de modificar."""
    if os.path.exists(filepath):
        backup_path = f"{filepath}.backup"
        shutil.copy2(filepath, backup_path)
        return backup_path
    return ""


def _cargar_json(filepath: str) -> dict:
    """Carga un archivo JSON."""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def _guardar_json(filepath: str, data: dict, crear_backup: bool = True) -> bool:
    """Guarda datos en archivo JSON."""
    try:
        if crear_backup:
            _crear_backup(filepath)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error guardando {filepath}: {e}")
        return False


# ============================================
# PALABRAS CLAVE GLOBALES (reglas_entrenadas.json)
# ============================================

def cargar_palabras_globales() -> Dict:
    """
    Carga las palabras clave globales.

    Returns:
        dict con keys: palabras_poliza, palabras_excluir, servicios_excluidos
    """
    data = _cargar_json(REGLAS_FILE)
    validacion = data.get('validacion_global', {})
    return {
        'palabras_poliza': validacion.get('palabras_poliza', []),
        'palabras_excluir': validacion.get('palabras_excluir', []),
        'servicios_excluidos': validacion.get('servicios_excluidos', [])
    }


def guardar_palabras_globales(palabras_poliza: List[str],
                               palabras_excluir: List[str],
                               servicios_excluidos: List[str]) -> Tuple[bool, str]:
    """
    Guarda las palabras clave globales.

    Returns:
        (exito: bool, mensaje: str)
    """
    try:
        data = _cargar_json(REGLAS_FILE)

        # Actualizar validacion_global
        if 'validacion_global' not in data:
            data['validacion_global'] = {}

        data['validacion_global']['palabras_poliza'] = [p.upper() for p in palabras_poliza if p.strip()]
        data['validacion_global']['palabras_excluir'] = [p.upper() for p in palabras_excluir if p.strip()]
        data['validacion_global']['servicios_excluidos'] = [s.upper() for s in servicios_excluidos if s.strip()]

        # Actualizar metadata
        data['fecha_modificacion'] = datetime.now().isoformat()

        if _guardar_json(REGLAS_FILE, data):
            return True, "Palabras clave guardadas correctamente"
        return False, "Error al guardar archivo"
    except Exception as e:
        return False, f"Error: {str(e)}"


def agregar_palabra_global(tipo: str, palabra: str) -> Tuple[bool, str]:
    """
    Agrega una palabra a una categoría global.

    Args:
        tipo: 'poliza', 'excluir' o 'servicios'
        palabra: palabra a agregar
    """
    palabras = cargar_palabras_globales()

    key_map = {
        'poliza': 'palabras_poliza',
        'excluir': 'palabras_excluir',
        'servicios': 'servicios_excluidos'
    }

    if tipo not in key_map:
        return False, f"Tipo inválido: {tipo}"

    key = key_map[tipo]
    palabra_upper = palabra.upper().strip()

    if palabra_upper in palabras[key]:
        return False, f"'{palabra_upper}' ya existe"

    palabras[key].append(palabra_upper)

    return guardar_palabras_globales(
        palabras['palabras_poliza'],
        palabras['palabras_excluir'],
        palabras['servicios_excluidos']
    )


def eliminar_palabra_global(tipo: str, palabra: str) -> Tuple[bool, str]:
    """
    Elimina una palabra de una categoría global.
    """
    palabras = cargar_palabras_globales()

    key_map = {
        'poliza': 'palabras_poliza',
        'excluir': 'palabras_excluir',
        'servicios': 'servicios_excluidos'
    }

    if tipo not in key_map:
        return False, f"Tipo inválido: {tipo}"

    key = key_map[tipo]
    palabra_upper = palabra.upper().strip()

    if palabra_upper not in palabras[key]:
        return False, f"'{palabra_upper}' no existe"

    palabras[key].remove(palabra_upper)

    return guardar_palabras_globales(
        palabras['palabras_poliza'],
        palabras['palabras_excluir'],
        palabras['servicios_excluidos']
    )


# ============================================
# REGLAS POR COMPAÑÍA (companias.json)
# ============================================

def cargar_companias() -> Dict:
    """
    Carga todas las compañías configuradas.

    Returns:
        dict con todas las compañías (id -> config)
    """
    data = _cargar_json(COMPANIAS_FILE)
    return data.get('companias', {})


def cargar_lista_companias() -> List[Dict]:
    """
    Carga lista simplificada de compañías para select.

    Returns:
        Lista de dicts con id, nombre, dominios
    """
    companias = cargar_companias()
    resultado = []
    for comp_id, config in companias.items():
        resultado.append({
            'id': comp_id,
            'nombre': config.get('nombre', comp_id),
            'dominios': config.get('dominios', []),
            'activa': config.get('activa', True),
            'es_default': config.get('es_default', False)
        })
    # Ordenar por nombre, pero 'generica' al final
    resultado.sort(key=lambda x: (x.get('es_default', False), x['nombre']))
    return resultado


def cargar_reglas_compania(compania_id: str) -> Optional[Dict]:
    """
    Carga las reglas de una compañía específica.

    Returns:
        dict con la configuración completa o None si no existe
    """
    companias = cargar_companias()
    return companias.get(compania_id)


def guardar_reglas_compania(compania_id: str, reglas: Dict) -> Tuple[bool, str]:
    """
    Guarda las reglas de una compañía.

    Args:
        compania_id: ID de la compañía
        reglas: dict con las reglas a guardar
    """
    try:
        data = _cargar_json(COMPANIAS_FILE)

        if 'companias' not in data:
            data['companias'] = {}

        # Mantener campos que no se modifican
        if compania_id in data['companias']:
            existing = data['companias'][compania_id]
            # Actualizar solo los campos proporcionados
            for key, value in reglas.items():
                existing[key] = value
            data['companias'][compania_id] = existing
        else:
            data['companias'][compania_id] = reglas

        if _guardar_json(COMPANIAS_FILE, data):
            return True, f"Reglas de '{compania_id}' guardadas"
        return False, "Error al guardar archivo"
    except Exception as e:
        return False, f"Error: {str(e)}"


def agregar_compania_json(compania_id: str, nombre: str, dominios: List[str],
                          tipo_extraccion: str = 'adjunto') -> Tuple[bool, str]:
    """
    Agrega una nueva compañía al archivo JSON.

    Args:
        compania_id: ID único (ej: 'allianz')
        nombre: Nombre display (ej: 'Allianz Seguros')
        dominios: Lista de dominios de email
        tipo_extraccion: 'adjunto' o 'enlace_html'
    """
    try:
        data = _cargar_json(COMPANIAS_FILE)

        if 'companias' not in data:
            data['companias'] = {}

        # Verificar que no existe
        if compania_id in data['companias']:
            return False, f"Ya existe compañía con ID '{compania_id}'"

        # Verificar dominios no duplicados
        for comp_id, config in data['companias'].items():
            for dominio in dominios:
                if dominio in config.get('dominios', []):
                    return False, f"Dominio '{dominio}' ya está asignado a '{comp_id}'"

        # Crear configuración por defecto
        nueva_compania = {
            "nombre": nombre,
            "activa": True,
            "dominios": dominios,
            "tipo_extraccion": tipo_extraccion,
            "filtros_imap": {
                "filtrar_por_from": True
            },
            "config_adjuntos": {
                "extensiones_permitidas": [".pdf"]
            },
            "limites": {
                "dias_max_antiguedad": 365,
                "tamano_max_pdf_mb": 25
            },
            "validacion_pdf": {
                "palabras_cualquiera": ["PÓLIZA", "ASEGURADO", nombre.upper()]
            },
            "renombrado": {
                "formato": "{asegurado}_{patente}_{fecha}.pdf"
            }
        }

        data['companias'][compania_id] = nueva_compania

        if _guardar_json(COMPANIAS_FILE, data):
            return True, f"Compañía '{nombre}' agregada correctamente"
        return False, "Error al guardar archivo"
    except Exception as e:
        return False, f"Error: {str(e)}"


def actualizar_dominios_compania(compania_id: str, dominios: List[str]) -> Tuple[bool, str]:
    """
    Actualiza los dominios de una compañía.
    """
    reglas = cargar_reglas_compania(compania_id)
    if not reglas:
        return False, f"Compañía '{compania_id}' no encontrada"

    reglas['dominios'] = [d.lower().strip() for d in dominios if d.strip()]
    return guardar_reglas_compania(compania_id, reglas)


def actualizar_validacion_compania(compania_id: str,
                                    palabras_requeridas: List[str] = None,
                                    palabras_cualquiera: List[str] = None,
                                    palabras_excluir: List[str] = None) -> Tuple[bool, str]:
    """
    Actualiza las reglas de validación PDF de una compañía.
    """
    reglas = cargar_reglas_compania(compania_id)
    if not reglas:
        return False, f"Compañía '{compania_id}' no encontrada"

    if 'validacion_pdf' not in reglas:
        reglas['validacion_pdf'] = {}

    if palabras_requeridas is not None:
        reglas['validacion_pdf']['palabras_requeridas'] = [p.upper() for p in palabras_requeridas]

    if palabras_cualquiera is not None:
        reglas['validacion_pdf']['palabras_cualquiera'] = [p.upper() for p in palabras_cualquiera]

    if palabras_excluir is not None:
        reglas['validacion_pdf']['palabras_excluir'] = [p.upper() for p in palabras_excluir]

    return guardar_reglas_compania(compania_id, reglas)
