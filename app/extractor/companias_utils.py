"""
Utilidades para gestión de nombres oficiales de compañías aseguradoras.

Este módulo proporciona funciones para:
1. Buscar el nombre oficial de una aseguradora en internet
2. Actualizar nombres en la base de datos
3. Mapear nombres detectados a nombres formales
"""

import re
import requests
from bs4 import BeautifulSoup


# Diccionario de nombres oficiales conocidos (cache local)
# Esto evita hacer búsquedas web repetidas para compañías conocidas
NOMBRES_OFICIALES = {
    # Clave: nombre detectado por el extractor (lowercase, sin espacios extra)
    'mercantil_andina': 'Compañía de Seguros La Mercantil Andina S.A.',
    'lamercantil': 'Compañía de Seguros La Mercantil Andina S.A.',
    'liderar': 'Liderar Compañía General de Seguros S.A.',
    'rio_uruguay': 'Río Uruguay Cooperativa de Seguros Ltda.',
    'berkley': 'Berkley International Seguros S.A.',
    'mapfre': 'MAPFRE Argentina Seguros S.A.',
    'la_caja': 'La Caja Compañía de Seguros S.A.',
    'sancor': 'Sancor Cooperativa de Seguros Ltda.',
    'allianz': 'Allianz Argentina Compañía de Seguros S.A.',
    'zurich': 'Zurich Argentina Compañía de Seguros S.A.',
    'sura': 'Seguros SURA S.A.',
    'la_segunda': 'La Segunda Compañía de Seguros S.A.',
    'provincia': 'Provincia Seguros S.A.',
    'san_cristobal': 'San Cristóbal Sociedad Mutual de Seguros Generales',
    'federacion_patronal': 'Federación Patronal Seguros S.A.',
    'triunfo': 'Triunfo Cooperativa de Seguros Ltda.',
    'integrity': 'Integrity Seguros Argentina S.A.',
    'orbis': 'Orbis Compañía Argentina de Seguros S.A.',
    'rivadavia': 'Rivadavia Seguros S.A.',
    'experta': 'Experta ART S.A.',
}


def normalizar_nombre(nombre):
    """
    Normaliza un nombre de compañía para búsqueda en el diccionario.

    Args:
        nombre: nombre de la compañía (puede venir de diferentes fuentes)

    Returns:
        str: nombre normalizado (lowercase, sin caracteres especiales)
    """
    if not nombre:
        return ''

    # Convertir a minúsculas y quitar espacios extra
    nombre = nombre.lower().strip()

    # Quitar caracteres especiales pero mantener letras y espacios
    nombre = re.sub(r'[^a-záéíóúñ\s]', '', nombre)

    # Reemplazar espacios múltiples por uno solo
    nombre = re.sub(r'\s+', ' ', nombre)

    # Reemplazar espacios por guiones bajos para la clave
    nombre_clave = nombre.replace(' ', '_')

    return nombre_clave


def obtener_nombre_oficial(nombre_detectado):
    """
    Obtiene el nombre oficial de una compañía aseguradora.

    Primero busca en el diccionario local. Si no lo encuentra,
    retorna el nombre original.

    Args:
        nombre_detectado: nombre de la compañía como fue detectado

    Returns:
        str: nombre oficial de la compañía
    """
    if not nombre_detectado:
        return nombre_detectado

    # Normalizar el nombre para búsqueda
    clave = normalizar_nombre(nombre_detectado)

    # Buscar en el diccionario
    if clave in NOMBRES_OFICIALES:
        return NOMBRES_OFICIALES[clave]

    # Buscar coincidencias parciales
    for key, valor in NOMBRES_OFICIALES.items():
        if key in clave or clave in key:
            return valor

    # Si no se encuentra, retornar el nombre original con formato título
    return nombre_detectado.title()


def buscar_nombre_web(nombre_compania):
    """
    Busca el nombre oficial de una compañía aseguradora en internet.

    NOTA: Esta función requiere conexión a internet y puede ser lenta.
    Se recomienda usar solo para compañías nuevas no conocidas.

    Args:
        nombre_compania: nombre de la compañía a buscar

    Returns:
        str or None: nombre oficial encontrado o None si no se encuentra
    """
    try:
        # Buscar en la web de la SSN (Superintendencia de Seguros de la Nación)
        # Esta es la fuente oficial de nombres de aseguradoras en Argentina
        url_busqueda = f"https://www.argentina.gob.ar/superintendencia-de-seguros/listado-de-aseguradoras"

        # Por ahora retornamos None - la búsqueda web real requeriría
        # configuración adicional de APIs o scraping
        return None

    except Exception as e:
        print(f"Error buscando nombre web: {e}")
        return None


def actualizar_nombres_bd(app=None):
    """
    Actualiza los nombres de compañías en la base de datos
    usando el diccionario de nombres oficiales.

    Args:
        app: instancia de la aplicación Flask (opcional)

    Returns:
        dict: resumen de actualizaciones realizadas
    """
    if app is None:
        from flask import current_app
        app = current_app

    from app import db
    from app.models import Compania

    actualizaciones = []

    with app.app_context():
        companias = Compania.query.all()

        for compania in companias:
            nombre_actual = compania.nombre
            nombre_oficial = obtener_nombre_oficial(nombre_actual)

            if nombre_oficial and nombre_oficial != nombre_actual:
                actualizaciones.append({
                    'id': compania.id,
                    'anterior': nombre_actual,
                    'nuevo': nombre_oficial
                })
                compania.nombre = nombre_oficial

        if actualizaciones:
            db.session.commit()

    return {
        'total': len(actualizaciones),
        'actualizaciones': actualizaciones
    }


def agregar_nombre_conocido(clave, nombre_oficial):
    """
    Agrega un nuevo nombre al diccionario de nombres oficiales.

    Args:
        clave: clave para el diccionario (nombre normalizado)
        nombre_oficial: nombre oficial completo de la compañía
    """
    global NOMBRES_OFICIALES
    NOMBRES_OFICIALES[normalizar_nombre(clave)] = nombre_oficial


def listar_nombres_conocidos():
    """
    Lista todos los nombres oficiales conocidos.

    Returns:
        dict: diccionario de nombres conocidos
    """
    return NOMBRES_OFICIALES.copy()
