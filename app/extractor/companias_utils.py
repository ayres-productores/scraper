"""
Utilidades para gestión de nombres oficiales de compañías aseguradoras.

Este módulo proporciona funciones para:
1. Buscar el nombre oficial de una aseguradora en internet
2. Actualizar nombres en la base de datos
3. Mapear nombres detectados a nombres formales
"""

import logging
import re
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger('app.extractor.companias_utils')


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


# Cache de búsquedas web para evitar consultas repetidas
_cache_busquedas_web = {}


def obtener_nombre_oficial(nombre_detectado, buscar_en_web=True):
    """
    Obtiene el nombre oficial de una compañía aseguradora.

    Flujo:
    1. Busca en el diccionario local (NOMBRES_OFICIALES)
    2. Busca coincidencias parciales en el diccionario
    3. Si buscar_en_web=True y no encuentra, consulta internet
    4. Si encuentra en web, lo guarda en cache y diccionario
    5. Si no encuentra, retorna el nombre original formateado

    Args:
        nombre_detectado: nombre de la compañía como fue detectado
        buscar_en_web: si debe buscar en internet cuando no encuentra localmente

    Returns:
        str: nombre oficial de la compañía
    """
    if not nombre_detectado:
        return nombre_detectado

    # Normalizar el nombre para búsqueda
    clave = normalizar_nombre(nombre_detectado)

    # 1. Buscar en el diccionario local
    if clave in NOMBRES_OFICIALES:
        return NOMBRES_OFICIALES[clave]

    # 2. Buscar coincidencias parciales
    for key, valor in NOMBRES_OFICIALES.items():
        if key in clave or clave in key:
            return valor

    # 3. Buscar en cache de búsquedas web
    if clave in _cache_busquedas_web:
        return _cache_busquedas_web[clave]

    # 4. Buscar en internet si está habilitado
    if buscar_en_web:
        logger.debug(f"Buscando en web: {nombre_detectado}")
        nombre_web = buscar_nombre_web(nombre_detectado)

        if nombre_web:
            logger.debug(f"Encontrado en web: {nombre_web}")
            # Guardar en cache y diccionario para futuras consultas
            _cache_busquedas_web[clave] = nombre_web
            NOMBRES_OFICIALES[clave] = nombre_web
            return nombre_web
        else:
            # Guardar en cache que no se encontró (evita búsquedas repetidas)
            nombre_formateado = nombre_detectado.title()
            _cache_busquedas_web[clave] = nombre_formateado

    # 5. Si no se encuentra, retornar el nombre original con formato título
    return nombre_detectado.title()


def buscar_nombre_web(nombre_compania, timeout=10):
    """
    Busca el nombre oficial de una compañía aseguradora en internet.

    Consulta DuckDuckGo para encontrar el nombre oficial/coloquial
    de la aseguradora en Argentina.

    IMPORTANTE: Esta función es conservadora - solo retorna un nombre
    si encuentra una coincidencia clara y confiable. Prefiere retornar
    None a retornar información incorrecta.

    Args:
        nombre_compania: nombre de la compañía a buscar
        timeout: tiempo máximo de espera en segundos

    Returns:
        str or None: nombre oficial encontrado o None si no se encuentra
    """
    if not nombre_compania or len(nombre_compania) < 3:
        return None

    try:
        # Limpiar nombre para búsqueda
        nombre_limpio = re.sub(r'[_-]', ' ', nombre_compania).strip()
        nombre_lower = nombre_limpio.lower()

        # Construir query de búsqueda específica
        query = f'"{nombre_limpio}" compañía seguros argentina sitio oficial'

        # Usar DuckDuckGo HTML (no requiere API key)
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        resultados = soup.select('.result')

        # Patrón estricto: Nombre + Tipo societario claramente definido
        # Ejemplo: "Sancor Cooperativa de Seguros Ltda." o "Mapfre Argentina S.A."
        patron_estricto = re.compile(
            r'\b(' + re.escape(nombre_limpio) + r'[^.]*?'
            r'(?:Compa[ñn][ií]a|Cooperativa|Sociedad)?[^.]*?'
            r'(?:de\s+)?(?:Seguros?|Aseguradora?)[^.]*?'
            r'(?:S\.?A\.?|Ltda\.?|S\.?R\.?L\.?|Limited)?'
            r')\b',
            re.IGNORECASE
        )

        for resultado in resultados[:5]:
            titulo_elem = resultado.select_one('.result__title')
            if not titulo_elem:
                continue

            titulo = titulo_elem.get_text().strip()

            # Verificar que el título es del sitio oficial o Wikipedia
            url_elem = resultado.select_one('.result__url')
            es_fuente_confiable = False
            if url_elem:
                url_texto = url_elem.get_text().lower()
                # Dominios confiables
                if any(d in url_texto for d in ['wikipedia', '.gob.ar', 'ssn.gob', nombre_lower.replace(' ', '')]):
                    es_fuente_confiable = True

            # Buscar con patrón estricto
            match = patron_estricto.search(titulo)
            if match:
                nombre_encontrado = match.group(1).strip()
                # Validaciones adicionales
                if len(nombre_encontrado) >= 10 and len(nombre_encontrado) <= 80:
                    if nombre_lower in nombre_encontrado.lower():
                        return _formatear_nombre_compania(nombre_encontrado)

            # Si es fuente confiable, intentar extraer del título directamente
            if es_fuente_confiable and nombre_lower in titulo.lower():
                # Limpiar título
                partes = re.split(r'[|\-–—]', titulo)
                for parte in partes:
                    parte = parte.strip()
                    if nombre_lower in parte.lower() and 'seguro' in parte.lower():
                        if 10 <= len(parte) <= 60:
                            return _formatear_nombre_compania(parte)

        return None

    except requests.Timeout:
        logger.debug(f"Timeout buscando: {nombre_compania}")
        return None
    except requests.RequestException as e:
        logger.debug(f"Error de red buscando {nombre_compania}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error buscando nombre web: {e}")
        return None


def _formatear_nombre_compania(nombre):
    """Formatea correctamente el nombre de una compañía."""
    if not nombre:
        return nombre

    # Normalizar espacios
    nombre = re.sub(r'\s+', ' ', nombre).strip()

    # Cortar en puntos que no sean de siglas (S.A., Ltda., etc.)
    # Si hay un punto seguido de espacio y mayúscula, probablemente es fin de oración
    nombre = re.split(r'\.(?=\s+[A-Z][a-z])', nombre)[0]

    # Cortar si empieza con palabras introductorias
    patrones_cortar = [
        r'^.*?(?:somos|nacimos|fundada|creada|desde)\s+.*?\s+([\w\s]+(?:S\.?A\.?|Ltda\.?|Seguros))',
        r'^.*?(?:como|es)\s+([\w\s]+(?:S\.?A\.?|Ltda\.?|Seguros)[\w\s]*)',
    ]
    for patron in patrones_cortar:
        match = re.search(patron, nombre, re.IGNORECASE)
        if match:
            nombre = match.group(1).strip()
            break

    # Remover texto después de ciertos delimitadores
    nombre = re.split(r'[,;]|\s+en\s+|\s+con\s+|\s+para\s+|\s+desde\s+', nombre)[0].strip()

    # Si termina con S.A, Ltda, etc., cortar ahí
    match_tipo = re.search(r'^(.+?(?:S\.?A\.?|Ltda\.?|S\.?R\.?L\.?))\b', nombre, re.IGNORECASE)
    if match_tipo:
        nombre = match_tipo.group(1)

    # Capitalizar correctamente (pero mantener siglas en mayúsculas)
    palabras = nombre.split()
    resultado = []

    for palabra in palabras:
        palabra_limpia = palabra.strip('.,;')
        # Mantener siglas y abreviaturas
        if palabra_limpia.upper() in ['S.A.', 'SA', 'S.R.L.', 'SRL', 'LTDA', 'LTDA.', 'DE', 'LA', 'EL', 'Y']:
            if palabra_limpia.upper() in ['LTDA', 'LTDA.']:
                resultado.append('Ltda.')
            elif palabra_limpia.upper() in ['S.A.', 'SA']:
                resultado.append('S.A.')
            elif palabra_limpia.upper() in ['DE', 'LA', 'EL', 'Y']:
                resultado.append(palabra_limpia.lower())
            else:
                resultado.append(palabra_limpia.upper())
        elif len(palabra_limpia) <= 3 and palabra_limpia.isupper():
            resultado.append(palabra_limpia)  # Mantener siglas cortas
        else:
            resultado.append(palabra_limpia.capitalize())

    nombre_final = ' '.join(resultado)

    # Limpiar puntuación final extra
    nombre_final = re.sub(r'[,;.]+$', '', nombre_final).strip()

    # Asegurar que termine con el tipo societario si lo tenía
    if not re.search(r'(?:S\.?A\.?|Ltda\.?|S\.?R\.?L\.?)$', nombre_final, re.IGNORECASE):
        # Si el original tenía tipo societario, agregarlo
        match_original = re.search(r'(S\.?A\.?|Ltda\.?|S\.?R\.?L\.?)\s*$', nombre, re.IGNORECASE)
        if match_original:
            nombre_final += ' ' + match_original.group(1)

    return nombre_final


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
