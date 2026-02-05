"""
Motor de Aprendizaje Incremental - Aprende de las correcciones del usuario.

Arquitectura híbrida:
1. REGLAS BASE: Regex existentes en pdf_parser.py
2. EJEMPLOS CORREGIDOS: correcciones.json - mapeo texto_original → valor_corregido
3. PATRONES APRENDIDOS: patrones_aprendidos.json - regex generados automáticamente
"""

import json
import os
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

# Rutas a los archivos de configuración
CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'config')
CORRECCIONES_FILE = os.path.join(CONFIG_DIR, 'correcciones.json')
PATRONES_FILE = os.path.join(CONFIG_DIR, 'patrones_aprendidos.json')
LOG_ERRORES_FILE = os.path.join(CONFIG_DIR, 'errores_seleccion.json')

# Umbral para generar patrón automático
FRECUENCIA_MINIMA_PATRON = 5
# Umbral de similitud para coincidencia fuzzy
UMBRAL_SIMILITUD = 0.85


def _cargar_json(filepath: str) -> dict:
    """Carga un archivo JSON."""
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _guardar_json(filepath: str, data: dict) -> bool:
    """Guarda datos en archivo JSON."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error guardando {filepath}: {e}")
        return False


def _similitud(texto1: str, texto2: str) -> float:
    """Calcula similitud entre dos textos (0-1)."""
    if not texto1 or not texto2:
        return 0.0
    return SequenceMatcher(None, texto1.upper(), texto2.upper()).ratio()


def _detectar_transformacion(original: str, corregido: str) -> Optional[str]:
    """Detecta qué tipo de transformación se aplicó."""
    if not original or not corregido:
        return None

    # Normalizar para comparar
    orig_clean = original.strip()
    corr_clean = corregido.strip()

    # Sin espacios: "AD 759 UL" → "AD759UL"
    if orig_clean.replace(' ', '') == corr_clean.replace(' ', '') and ' ' in orig_clean:
        return 'sin_espacios'

    # Título: "JUAN PEREZ" → "Juan Perez"
    if orig_clean.upper() == corr_clean.upper() and corr_clean == corr_clean.title():
        return 'titulo'

    # Mayúsculas: "juan perez" → "JUAN PEREZ"
    if orig_clean.upper() == corr_clean:
        return 'mayusculas'

    # Minúsculas: "JUAN PEREZ" → "juan perez"
    if orig_clean.lower() == corr_clean:
        return 'minusculas'

    # Formato DNI: "20345678" → "20.345.678"
    if orig_clean.replace('.', '') == corr_clean.replace('.', ''):
        if '.' in corr_clean and '.' not in orig_clean:
            return 'formato_dni'

    # Formato fecha: detectar cambios de formato de fecha
    if _es_fecha(orig_clean) and _es_fecha(corr_clean):
        return 'formato_fecha'

    return 'otro'


def _es_fecha(texto: str) -> bool:
    """Verifica si el texto parece una fecha."""
    patrones_fecha = [
        r'\d{2}/\d{2}/\d{4}',
        r'\d{4}-\d{2}-\d{2}',
        r'\d{2}-\d{2}-\d{4}',
        r'\d{1,2}\s+de\s+\w+\s+de\s+\d{4}',
    ]
    for patron in patrones_fecha:
        if re.search(patron, texto):
            return True
    return False


def _aplicar_transformacion(texto: str, tipo: str) -> str:
    """Aplica una transformación conocida al texto."""
    if not texto:
        return texto

    if tipo == 'sin_espacios':
        return texto.replace(' ', '')
    elif tipo == 'titulo':
        return texto.title()
    elif tipo == 'mayusculas':
        return texto.upper()
    elif tipo == 'minusculas':
        return texto.lower()
    elif tipo == 'formato_dni':
        # Formatear como DNI argentino: XX.XXX.XXX
        numeros = re.sub(r'\D', '', texto)
        if len(numeros) >= 7:
            if len(numeros) == 7:
                return f"{numeros[0]}.{numeros[1:4]}.{numeros[4:7]}"
            elif len(numeros) == 8:
                return f"{numeros[0:2]}.{numeros[2:5]}.{numeros[5:8]}"
            elif len(numeros) >= 10:  # CUIT
                return f"{numeros[0:2]}-{numeros[2:10]}-{numeros[10:]}"
        return texto

    return texto


class MotorAprendizaje:
    """Motor de aprendizaje incremental basado en correcciones del usuario."""

    def __init__(self):
        self.correcciones = _cargar_json(CORRECCIONES_FILE)
        self.patrones = _cargar_json(PATRONES_FILE)

        # Inicializar estructura si está vacía
        if not self.correcciones:
            self.correcciones = {
                'version': '1.0',
                'total_correcciones': 0,
                'campos': {}
            }

        if not self.patrones:
            self.patrones = {
                'version': '1.0',
                'total_patrones': 0,
                'campos': {}
            }

    def buscar_correccion(self, campo: str, texto_original: str,
                          contexto: str = None) -> Optional[Dict]:
        """
        Busca si hay una corrección aprendida para este texto.

        Args:
            campo: Nombre del campo (ej: 'asegurado_nombre')
            texto_original: Valor extraído del PDF
            contexto: Texto circundante para mejor matching

        Returns:
            Dict con 'valor_corregido' y 'confianza', o None
        """
        if not texto_original or not texto_original.strip():
            return None

        texto_norm = texto_original.strip().upper()
        campo_data = self.correcciones.get('campos', {}).get(campo, {})
        ejemplos = campo_data.get('ejemplos', [])

        # 1. Coincidencia exacta
        for ejemplo in ejemplos:
            if ejemplo.get('texto_original', '').upper() == texto_norm:
                return {
                    'valor_corregido': ejemplo['valor_corregido'],
                    'confianza': 0.98,
                    'metodo': 'exacto',
                    'frecuencia': ejemplo.get('frecuencia', 1)
                }

        # 2. Coincidencia fuzzy (>85% similar)
        mejor_match = None
        mejor_similitud = 0
        for ejemplo in ejemplos:
            sim = _similitud(texto_original, ejemplo.get('texto_original', ''))
            if sim > UMBRAL_SIMILITUD and sim > mejor_similitud:
                mejor_similitud = sim
                mejor_match = ejemplo

        if mejor_match:
            return {
                'valor_corregido': mejor_match['valor_corregido'],
                'confianza': mejor_similitud * 0.9,  # Reducir un poco por ser fuzzy
                'metodo': 'fuzzy',
                'similitud': mejor_similitud
            }

        # 3. Patrón aprendido con misma transformación
        patrones_campo = self.patrones.get('campos', {}).get(campo, {})
        for patron in patrones_campo.get('patrones', []):
            transformacion = patron.get('transformacion')
            if transformacion and transformacion != 'otro':
                # Aplicar la transformación aprendida
                valor_transformado = _aplicar_transformacion(texto_original, transformacion)
                if valor_transformado != texto_original:
                    return {
                        'valor_corregido': valor_transformado,
                        'confianza': patron.get('confianza', 0.7),
                        'metodo': 'patron',
                        'transformacion': transformacion
                    }

        return None

    def registrar_correccion(self, campo: str, texto_original: str,
                             valor_corregido: str, contexto: str = None,
                             compania: str = None) -> Tuple[bool, str]:
        """
        Registra una nueva corrección del usuario.

        Args:
            campo: Nombre del campo corregido
            texto_original: Valor extraído originalmente
            valor_corregido: Valor correcto indicado por el usuario
            contexto: Texto circundante (opcional)
            compania: ID de la compañía (opcional)

        Returns:
            (exito, mensaje)
        """
        if not texto_original or not valor_corregido:
            return False, "Texto original y corregido son requeridos"

        texto_norm = texto_original.strip()
        valor_norm = valor_corregido.strip()

        if texto_norm.upper() == valor_norm.upper():
            return False, "El valor corregido es igual al original"

        # Detectar transformación
        transformacion = _detectar_transformacion(texto_norm, valor_norm)

        # Inicializar campo si no existe
        if 'campos' not in self.correcciones:
            self.correcciones['campos'] = {}
        if campo not in self.correcciones['campos']:
            self.correcciones['campos'][campo] = {'ejemplos': []}

        # Buscar si ya existe este ejemplo
        ejemplos = self.correcciones['campos'][campo]['ejemplos']
        ejemplo_existente = None
        for i, ej in enumerate(ejemplos):
            if ej.get('texto_original', '').upper() == texto_norm.upper():
                ejemplo_existente = i
                break

        if ejemplo_existente is not None:
            # Actualizar frecuencia
            ejemplos[ejemplo_existente]['frecuencia'] = ejemplos[ejemplo_existente].get('frecuencia', 1) + 1
            ejemplos[ejemplo_existente]['valor_corregido'] = valor_norm
            ejemplos[ejemplo_existente]['fecha_ultima'] = datetime.now().isoformat()
        else:
            # Agregar nuevo ejemplo
            nuevo_ejemplo = {
                'texto_original': texto_norm,
                'valor_corregido': valor_norm,
                'transformacion': transformacion,
                'contexto': contexto,
                'compania': compania,
                'frecuencia': 1,
                'fecha': datetime.now().isoformat()
            }
            ejemplos.append(nuevo_ejemplo)
            self.correcciones['total_correcciones'] = self.correcciones.get('total_correcciones', 0) + 1

        # Guardar correcciones
        if not _guardar_json(CORRECCIONES_FILE, self.correcciones):
            return False, "Error al guardar correcciones"

        # Verificar si debemos generar un patrón
        mensaje = "Corrección registrada"
        if transformacion and transformacion != 'otro':
            patron_generado = self._intentar_generar_patron(campo, transformacion)
            if patron_generado:
                mensaje += f". Nuevo patrón '{transformacion}' generado automáticamente"

        return True, mensaje

    def _intentar_generar_patron(self, campo: str, transformacion: str) -> bool:
        """
        Intenta generar un patrón si hay suficientes ejemplos.

        Returns:
            True si se generó un nuevo patrón
        """
        ejemplos = self.correcciones.get('campos', {}).get(campo, {}).get('ejemplos', [])

        # Contar ejemplos con esta transformación
        ejemplos_trans = [e for e in ejemplos if e.get('transformacion') == transformacion]
        total_frecuencia = sum(e.get('frecuencia', 1) for e in ejemplos_trans)

        if total_frecuencia < FRECUENCIA_MINIMA_PATRON:
            return False

        # Verificar si ya existe este patrón
        if 'campos' not in self.patrones:
            self.patrones['campos'] = {}
        if campo not in self.patrones['campos']:
            self.patrones['campos'][campo] = {'patrones': []}

        patrones_existentes = self.patrones['campos'][campo]['patrones']
        for p in patrones_existentes:
            if p.get('transformacion') == transformacion:
                # Actualizar confianza
                p['confianza'] = min(0.95, p.get('confianza', 0.7) + 0.05)
                p['basado_en'] = total_frecuencia
                _guardar_json(PATRONES_FILE, self.patrones)
                return False  # Ya existía, solo actualizamos

        # Crear nuevo patrón
        nuevo_patron = {
            'transformacion': transformacion,
            'confianza': 0.75,
            'basado_en': total_frecuencia,
            'fecha_creacion': datetime.now().isoformat()
        }
        patrones_existentes.append(nuevo_patron)
        self.patrones['total_patrones'] = self.patrones.get('total_patrones', 0) + 1

        _guardar_json(PATRONES_FILE, self.patrones)
        return True

    def confirmar_datos(self, campo: str, valor: str) -> Tuple[bool, str]:
        """
        Confirma que un dato extraído es correcto (sin corrección).
        Esto incrementa la confianza de los patrones usados.
        """
        # Por ahora solo registramos la confirmación
        # En el futuro podemos usar esto para ajustar confianza
        return True, "Dato confirmado"

    def obtener_estadisticas(self) -> Dict:
        """Retorna estadísticas del aprendizaje."""
        total_ejemplos = 0
        campos_con_ejemplos = 0

        for campo, data in self.correcciones.get('campos', {}).items():
            ejemplos = data.get('ejemplos', [])
            if ejemplos:
                campos_con_ejemplos += 1
                total_ejemplos += len(ejemplos)

        total_patrones = 0
        for campo, data in self.patrones.get('campos', {}).items():
            total_patrones += len(data.get('patrones', []))

        return {
            'total_correcciones': self.correcciones.get('total_correcciones', 0),
            'total_ejemplos': total_ejemplos,
            'campos_con_ejemplos': campos_con_ejemplos,
            'total_patrones': total_patrones
        }

    def obtener_correcciones_campo(self, campo: str) -> List[Dict]:
        """Retorna todas las correcciones de un campo."""
        return self.correcciones.get('campos', {}).get(campo, {}).get('ejemplos', [])

    def registrar_lote_correcciones(self, correcciones: List[Dict],
                                     contexto: Dict) -> Tuple[int, str]:
        """
        Registra múltiples correcciones de una sesión de edición.

        Este método es llamado cuando el usuario guarda una póliza después
        de editar campos pre-rellenados. Registra las correcciones tanto
        en el archivo de aprendizaje como en el log de errores para análisis.

        Args:
            correcciones: Lista de correcciones del frontend, cada una con:
                - campo_sugerido: str - Campo donde el algoritmo lo puso
                - campo_correcto: str - Campo donde debía ir (por ahora igual)
                - texto_original: str - Texto crudo del PDF
                - valor_extraido: str - Valor que el algoritmo sugirió
                - valor_corregido: str - Valor que el usuario guardó
                - tipo_cambio: str - edicion, agregado_manual, eliminacion
                - confianza_original: float - Confianza del algoritmo (0-1)

            contexto: Diccionario con información de la sesión:
                - archivo_id: int
                - usuario_id: int
                - compania: str
                - tipo_seguro: str
                - tiempo_edicion: int (segundos)
                - poliza_id: int (opcional, después de crear)
                - cliente_id: int (opcional, después de crear)

        Returns:
            (cantidad_registradas, mensaje)
        """
        registradas = 0
        sesion_id = str(uuid.uuid4())

        for corr in correcciones:
            tipo_cambio = corr.get('tipo_cambio', 'edicion')
            valor_extraido = corr.get('valor_extraido')
            valor_corregido = corr.get('valor_corregido')
            campo = corr.get('campo_correcto') or corr.get('campo_sugerido')

            # Solo registrar si realmente hubo un cambio
            if tipo_cambio == 'edicion' and valor_extraido and valor_corregido:
                # Verificar que son diferentes
                if str(valor_extraido).strip() != str(valor_corregido).strip():
                    exito, _ = self.registrar_correccion(
                        campo=campo,
                        texto_original=corr.get('texto_original') or valor_extraido,
                        valor_corregido=valor_corregido,
                        contexto=contexto.get('tipo_seguro'),
                        compania=contexto.get('compania')
                    )
                    if exito:
                        registradas += 1

        # Guardar en log de errores para análisis y entrenamiento ML
        self._guardar_log_errores(correcciones, contexto, sesion_id)

        # Guardar también en BD si hay usuario_id
        self._guardar_log_bd(correcciones, contexto, sesion_id)

        mensaje = f"{registradas} correcciones registradas en el motor de aprendizaje"
        return registradas, mensaje

    def _guardar_log_errores(self, correcciones: List[Dict],
                             contexto: Dict, sesion_id: str) -> bool:
        """
        Guarda el log detallado de errores para análisis y entrenamiento ML.

        Este archivo JSON es exportable para entrenar modelos externos.
        """
        log = _cargar_json(LOG_ERRORES_FILE)

        if not log:
            log = {
                'version': '1.0',
                'total_registros': 0,
                'registros': [],
                'estadisticas': {
                    'por_campo': {},
                    'por_tipo_cambio': {},
                    'por_compania': {}
                }
            }

        # Crear registro de la sesión
        registro = {
            'id': sesion_id,
            'timestamp': datetime.now().isoformat(),
            'usuario_id': contexto.get('usuario_id'),
            'archivo_id': contexto.get('archivo_id'),
            'poliza_id': contexto.get('poliza_id'),
            'cliente_id': contexto.get('cliente_id'),
            'compania_detectada': contexto.get('compania'),
            'tipo_seguro': contexto.get('tipo_seguro'),
            'correcciones': correcciones,
            'contexto': {
                'campos_totales_modificados': len(correcciones),
                'tiempo_edicion_segundos': contexto.get('tiempo_edicion', 0)
            }
        }

        log['registros'].append(registro)
        log['total_registros'] += 1

        # Actualizar estadísticas
        self._actualizar_estadisticas_log(log, correcciones, contexto)

        return _guardar_json(LOG_ERRORES_FILE, log)

    def _actualizar_estadisticas_log(self, log: Dict, correcciones: List[Dict],
                                      contexto: Dict) -> None:
        """Actualiza las estadísticas del log de errores."""
        stats = log.get('estadisticas', {})

        # Por campo
        por_campo = stats.setdefault('por_campo', {})
        for corr in correcciones:
            campo = corr.get('campo_correcto') or corr.get('campo_sugerido', 'desconocido')
            if campo not in por_campo:
                por_campo[campo] = {'total': 0, 'ediciones': 0, 'agregados': 0, 'eliminaciones': 0}
            por_campo[campo]['total'] += 1
            tipo = corr.get('tipo_cambio', 'edicion')
            if tipo == 'edicion':
                por_campo[campo]['ediciones'] += 1
            elif tipo == 'agregado_manual':
                por_campo[campo]['agregados'] += 1
            elif tipo == 'eliminacion':
                por_campo[campo]['eliminaciones'] += 1

        # Por tipo de cambio
        por_tipo = stats.setdefault('por_tipo_cambio', {})
        for corr in correcciones:
            tipo = corr.get('tipo_cambio', 'edicion')
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1

        # Por compañía
        compania = contexto.get('compania', 'desconocida')
        por_compania = stats.setdefault('por_compania', {})
        por_compania[compania] = por_compania.get(compania, 0) + len(correcciones)

    def _guardar_log_bd(self, correcciones: List[Dict],
                        contexto: Dict, sesion_id: str) -> bool:
        """
        Guarda las correcciones en la base de datos.

        Utiliza el modelo LogCorreccionExtraccion para persistencia.
        """
        if not contexto.get('usuario_id'):
            return False

        try:
            from app.models import LogCorreccionExtraccion, db

            for corr in correcciones:
                LogCorreccionExtraccion.registrar(
                    usuario_id=contexto.get('usuario_id'),
                    archivo_id=contexto.get('archivo_id'),
                    poliza_id=contexto.get('poliza_id'),
                    cliente_id=contexto.get('cliente_id'),
                    campo=corr.get('campo_correcto') or corr.get('campo_sugerido'),
                    texto_original=corr.get('texto_original'),
                    valor_extraido=corr.get('valor_extraido'),
                    valor_corregido=corr.get('valor_corregido'),
                    tipo_cambio=corr.get('tipo_cambio', 'edicion'),
                    confianza_original=corr.get('confianza_original'),
                    compania=contexto.get('compania'),
                    tipo_seguro=contexto.get('tipo_seguro'),
                    sesion_id=sesion_id
                )

            # No hacemos commit aquí - se hace en el servicio que llama
            return True

        except ImportError:
            # Módulo de modelos no disponible (ej: tests)
            return False
        except Exception as e:
            print(f"Error guardando correcciones en BD: {e}")
            return False

    def obtener_estadisticas_log(self) -> Dict:
        """Retorna las estadísticas del log de errores."""
        log = _cargar_json(LOG_ERRORES_FILE)
        return {
            'total_registros': log.get('total_registros', 0),
            'estadisticas': log.get('estadisticas', {})
        }

    def obtener_campos_problematicos(self, limite: int = 10) -> List[Dict]:
        """
        Retorna los campos que más correcciones requieren.

        Útil para identificar dónde el algoritmo falla más frecuentemente.
        """
        log = _cargar_json(LOG_ERRORES_FILE)
        por_campo = log.get('estadisticas', {}).get('por_campo', {})

        # Ordenar por total de correcciones
        ordenados = sorted(
            [{'campo': k, **v} for k, v in por_campo.items()],
            key=lambda x: x.get('total', 0),
            reverse=True
        )

        return ordenados[:limite]

    def exportar_para_entrenamiento(self, filepath: str = None) -> Dict:
        """
        Exporta los datos de correcciones en formato adecuado para entrenamiento ML.

        Returns:
            Dict con estructura optimizada para entrenamiento
        """
        log = _cargar_json(LOG_ERRORES_FILE)

        # Aplanar los datos para facilitar el entrenamiento
        datos_entrenamiento = []

        for registro in log.get('registros', []):
            for corr in registro.get('correcciones', []):
                if corr.get('tipo_cambio') == 'edicion' and corr.get('texto_original'):
                    datos_entrenamiento.append({
                        'campo': corr.get('campo_correcto') or corr.get('campo_sugerido'),
                        'texto_original': corr.get('texto_original'),
                        'valor_extraido': corr.get('valor_extraido'),
                        'valor_corregido': corr.get('valor_corregido'),
                        'compania': registro.get('compania_detectada'),
                        'tipo_seguro': registro.get('tipo_seguro'),
                        'timestamp': registro.get('timestamp')
                    })

        resultado = {
            'version': '1.0',
            'fecha_exportacion': datetime.now().isoformat(),
            'total_ejemplos': len(datos_entrenamiento),
            'datos': datos_entrenamiento
        }

        if filepath:
            _guardar_json(filepath, resultado)

        return resultado


# Instancia global del motor
_motor = None

def obtener_motor() -> MotorAprendizaje:
    """Obtiene la instancia global del motor de aprendizaje."""
    global _motor
    if _motor is None:
        _motor = MotorAprendizaje()
    return _motor


def buscar_correccion(campo: str, texto_original: str, contexto: str = None) -> Optional[Dict]:
    """Función helper para buscar corrección."""
    return obtener_motor().buscar_correccion(campo, texto_original, contexto)


def registrar_correccion(campo: str, texto_original: str, valor_corregido: str,
                         contexto: str = None, compania: str = None) -> Tuple[bool, str]:
    """Función helper para registrar corrección."""
    return obtener_motor().registrar_correccion(campo, texto_original, valor_corregido, contexto, compania)


def registrar_lote_correcciones(correcciones: List[Dict], contexto: Dict) -> Tuple[int, str]:
    """Función helper para registrar múltiples correcciones de una sesión."""
    return obtener_motor().registrar_lote_correcciones(correcciones, contexto)


def obtener_estadisticas_aprendizaje() -> Dict:
    """Función helper para obtener estadísticas completas del aprendizaje."""
    motor = obtener_motor()
    return {
        'motor': motor.obtener_estadisticas(),
        'log_errores': motor.obtener_estadisticas_log(),
        'campos_problematicos': motor.obtener_campos_problematicos(5)
    }
