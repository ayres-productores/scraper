"""
Patrón State para gestión del ciclo de vida de escaneos.

Permite pausar/detener escaneos y reanudarlos posteriormente,
guardando el progreso de forma persistente.

Estados:
    IDLE -> RUNNING -> PAUSED -> RUNNING -> COMPLETED
                    -> STOPPED
                    -> ERROR

Uso:
    context = ScanStateContext(escaneo_id=123, usuario_id=1)
    context.start(config)

    # Durante el escaneo:
    context.update_progress(cuenta='email@gmail.com', carpeta='INBOX', mensaje_idx=50)

    # Pausar (guarda estado):
    context.pause()

    # Reanudar desde donde quedó:
    context.resume()

    # O detener definitivamente:
    context.stop()
"""

import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, List, Any
from threading import Lock

logger = logging.getLogger('app.extractor.scan_state')

# Detectar directorio base
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATE_DIR = os.path.join(BASE_DIR, 'logs', 'scan_states')
os.makedirs(STATE_DIR, exist_ok=True)

_state_lock = Lock()


# =============================================================================
# DATA CLASSES PARA PROGRESO
# =============================================================================

@dataclass
class CuentaProgress:
    """Progreso de una cuenta específica."""
    correo: str
    carpetas_completadas: List[str] = field(default_factory=list)
    carpeta_actual: Optional[str] = None
    mensaje_idx: int = 0  # Índice del mensaje actual en la carpeta
    total_mensajes: int = 0
    pdfs_descargados: int = 0
    correos_procesados: int = 0
    completada: bool = False


@dataclass
class ScanProgress:
    """Progreso completo del escaneo."""
    escaneo_id: int
    usuario_id: int
    estado: str = 'idle'

    # Configuración del escaneo
    config: Dict[str, Any] = field(default_factory=dict)
    directorio_salida: str = ''

    # Progreso por cuenta
    cuentas: Dict[str, CuentaProgress] = field(default_factory=dict)
    cuenta_actual_idx: int = 0
    orden_cuentas: List[str] = field(default_factory=list)

    # Totales
    total_pdfs: int = 0
    total_correos: int = 0
    total_errores: int = 0

    # Timestamps
    fecha_inicio: Optional[str] = None
    fecha_pausa: Optional[str] = None
    fecha_reanudacion: Optional[str] = None
    fecha_fin: Optional[str] = None

    # Hashes ya procesados (para evitar duplicados)
    hashes_procesados: List[str] = field(default_factory=list)

    # Message IDs procesados por cuenta/carpeta
    mensajes_procesados: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convierte a diccionario para JSON."""
        data = {
            'escaneo_id': self.escaneo_id,
            'usuario_id': self.usuario_id,
            'estado': self.estado,
            'config': self.config,
            'directorio_salida': self.directorio_salida,
            'cuenta_actual_idx': self.cuenta_actual_idx,
            'orden_cuentas': self.orden_cuentas,
            'total_pdfs': self.total_pdfs,
            'total_correos': self.total_correos,
            'total_errores': self.total_errores,
            'fecha_inicio': self.fecha_inicio,
            'fecha_pausa': self.fecha_pausa,
            'fecha_reanudacion': self.fecha_reanudacion,
            'fecha_fin': self.fecha_fin,
            'hashes_procesados': self.hashes_procesados,
            'mensajes_procesados': self.mensajes_procesados,
            'cuentas': {}
        }
        for correo, cuenta_prog in self.cuentas.items():
            data['cuentas'][correo] = asdict(cuenta_prog)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'ScanProgress':
        """Crea instancia desde diccionario."""
        progress = cls(
            escaneo_id=data['escaneo_id'],
            usuario_id=data['usuario_id'],
            estado=data.get('estado', 'idle'),
            config=data.get('config', {}),
            directorio_salida=data.get('directorio_salida', ''),
            cuenta_actual_idx=data.get('cuenta_actual_idx', 0),
            orden_cuentas=data.get('orden_cuentas', []),
            total_pdfs=data.get('total_pdfs', 0),
            total_correos=data.get('total_correos', 0),
            total_errores=data.get('total_errores', 0),
            fecha_inicio=data.get('fecha_inicio'),
            fecha_pausa=data.get('fecha_pausa'),
            fecha_reanudacion=data.get('fecha_reanudacion'),
            fecha_fin=data.get('fecha_fin'),
            hashes_procesados=data.get('hashes_procesados', []),
            mensajes_procesados=data.get('mensajes_procesados', {})
        )
        for correo, cuenta_data in data.get('cuentas', {}).items():
            progress.cuentas[correo] = CuentaProgress(**cuenta_data)
        return progress


# =============================================================================
# ESTADOS (PATRÓN STATE)
# =============================================================================

class ScanState(ABC):
    """Clase base abstracta para estados del escaneo."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre del estado."""
        pass

    def enter(self, context: 'ScanStateContext') -> None:
        """Llamado al entrar al estado."""
        context.progress.estado = self.name
        logger.debug(f"Entrando a estado: {self.name}")

    def exit(self, context: 'ScanStateContext') -> None:
        """Llamado al salir del estado."""
        pass

    @abstractmethod
    def pause(self, context: 'ScanStateContext') -> bool:
        """Intenta pausar. Retorna True si fue exitoso."""
        pass

    @abstractmethod
    def resume(self, context: 'ScanStateContext') -> bool:
        """Intenta reanudar. Retorna True si fue exitoso."""
        pass

    @abstractmethod
    def stop(self, context: 'ScanStateContext') -> bool:
        """Intenta detener. Retorna True si fue exitoso."""
        pass

    def complete(self, context: 'ScanStateContext') -> bool:
        """Marca como completado."""
        return False

    def error(self, context: 'ScanStateContext', error_msg: str) -> bool:
        """Maneja un error."""
        return False


class IdleState(ScanState):
    """Estado inicial - sin escaneo activo."""

    @property
    def name(self) -> str:
        return 'idle'

    def pause(self, context: 'ScanStateContext') -> bool:
        return False  # No se puede pausar si no está corriendo

    def resume(self, context: 'ScanStateContext') -> bool:
        return False  # No hay nada que reanudar

    def stop(self, context: 'ScanStateContext') -> bool:
        return False  # No hay nada que detener

    def start(self, context: 'ScanStateContext') -> bool:
        """Inicia el escaneo."""
        context.progress.fecha_inicio = datetime.utcnow().isoformat()
        context._transition_to(RunningState())
        return True


class RunningState(ScanState):
    """Estado de escaneo en ejecución."""

    @property
    def name(self) -> str:
        return 'running'

    def pause(self, context: 'ScanStateContext') -> bool:
        """Pausa y guarda el estado."""
        context.progress.fecha_pausa = datetime.utcnow().isoformat()
        context.save_state()  # Guardar estado antes de pausar
        context._transition_to(PausedState())
        return True

    def resume(self, context: 'ScanStateContext') -> bool:
        return False  # Ya está corriendo

    def stop(self, context: 'ScanStateContext') -> bool:
        """Detiene y guarda el estado."""
        context.save_state()  # Guardar estado antes de detener
        context._transition_to(StoppedState())
        return True

    def complete(self, context: 'ScanStateContext') -> bool:
        """Marca como completado."""
        context.progress.fecha_fin = datetime.utcnow().isoformat()
        context._transition_to(CompletedState())
        context.delete_state_file()  # Limpiar archivo de estado
        return True

    def error(self, context: 'ScanStateContext', error_msg: str) -> bool:
        """Maneja error."""
        context.progress.total_errores += 1
        context.save_state()
        context._transition_to(ErrorState(error_msg))
        return True


class PausedState(ScanState):
    """Estado pausado - escaneo interrumpido temporalmente."""

    @property
    def name(self) -> str:
        return 'paused'

    def enter(self, context: 'ScanStateContext') -> None:
        super().enter(context)
        context.save_state()  # Asegurar que el estado está guardado

    def pause(self, context: 'ScanStateContext') -> bool:
        return False  # Ya está pausado

    def resume(self, context: 'ScanStateContext') -> bool:
        """Reanuda desde donde quedó."""
        context.progress.fecha_reanudacion = datetime.utcnow().isoformat()
        context._transition_to(RunningState())
        return True

    def stop(self, context: 'ScanStateContext') -> bool:
        """Detiene definitivamente."""
        context._transition_to(StoppedState())
        return True


class StoppedState(ScanState):
    """Estado detenido - puede reanudarse más tarde."""

    @property
    def name(self) -> str:
        return 'stopped'

    def enter(self, context: 'ScanStateContext') -> None:
        super().enter(context)
        context.save_state()  # Guardar para posible reanudación

    def pause(self, context: 'ScanStateContext') -> bool:
        return False

    def resume(self, context: 'ScanStateContext') -> bool:
        """Reanuda el escaneo detenido."""
        context.progress.fecha_reanudacion = datetime.utcnow().isoformat()
        context._transition_to(RunningState())
        return True

    def stop(self, context: 'ScanStateContext') -> bool:
        return False  # Ya está detenido


class CompletedState(ScanState):
    """Estado completado - escaneo finalizado exitosamente."""

    @property
    def name(self) -> str:
        return 'completed'

    def pause(self, context: 'ScanStateContext') -> bool:
        return False

    def resume(self, context: 'ScanStateContext') -> bool:
        return False

    def stop(self, context: 'ScanStateContext') -> bool:
        return False


class ErrorState(ScanState):
    """Estado de error - puede reintentar o detener."""

    def __init__(self, error_msg: str = ''):
        self.error_msg = error_msg

    @property
    def name(self) -> str:
        return 'error'

    def enter(self, context: 'ScanStateContext') -> None:
        super().enter(context)
        context.save_state()
        logger.error(f"Estado error: {self.error_msg}")

    def pause(self, context: 'ScanStateContext') -> bool:
        return False

    def resume(self, context: 'ScanStateContext') -> bool:
        """Reintentar desde donde quedó."""
        context._transition_to(RunningState())
        return True

    def stop(self, context: 'ScanStateContext') -> bool:
        context._transition_to(StoppedState())
        return True


# =============================================================================
# CONTEXTO DEL ESTADO
# =============================================================================

class ScanStateContext:
    """
    Contexto que mantiene el estado actual del escaneo.

    Maneja transiciones de estado y persistencia.
    """

    def __init__(self, escaneo_id: int, usuario_id: int):
        self.escaneo_id = escaneo_id
        self.usuario_id = usuario_id
        self.state_file = os.path.join(STATE_DIR, f'scan_state_{escaneo_id}.json')

        # Intentar cargar estado existente
        loaded = self.load_state()
        if loaded:
            self.progress = loaded
            # Restaurar el estado correcto
            self._state = self._state_from_name(self.progress.estado)
        else:
            self.progress = ScanProgress(escaneo_id=escaneo_id, usuario_id=usuario_id)
            self._state = IdleState()

    def _state_from_name(self, name: str) -> ScanState:
        """Obtiene instancia de estado desde nombre."""
        states = {
            'idle': IdleState(),
            'running': RunningState(),
            'paused': PausedState(),
            'stopped': StoppedState(),
            'completed': CompletedState(),
            'error': ErrorState()
        }
        return states.get(name, IdleState())

    def _transition_to(self, new_state: ScanState) -> None:
        """Realiza transición a nuevo estado."""
        self._state.exit(self)
        self._state = new_state
        self._state.enter(self)

    @property
    def current_state(self) -> str:
        """Nombre del estado actual."""
        return self._state.name

    @property
    def is_running(self) -> bool:
        return isinstance(self._state, RunningState)

    @property
    def is_paused(self) -> bool:
        return isinstance(self._state, PausedState)

    @property
    def is_stopped(self) -> bool:
        return isinstance(self._state, StoppedState)

    @property
    def can_resume(self) -> bool:
        """Indica si se puede reanudar."""
        return isinstance(self._state, (PausedState, StoppedState, ErrorState))

    # =========================================================================
    # DELEGACIÓN AL ESTADO ACTUAL
    # =========================================================================

    def start(self, config: dict, cuentas: List[str], directorio_salida: str) -> bool:
        """Inicia el escaneo."""
        if isinstance(self._state, IdleState):
            self.progress.config = config
            self.progress.directorio_salida = directorio_salida
            self.progress.orden_cuentas = cuentas
            for correo in cuentas:
                self.progress.cuentas[correo] = CuentaProgress(correo=correo)
            return self._state.start(self)
        return False

    def pause(self) -> bool:
        """Pausa el escaneo."""
        return self._state.pause(self)

    def resume(self) -> bool:
        """Reanuda el escaneo."""
        return self._state.resume(self)

    def stop(self) -> bool:
        """Detiene el escaneo."""
        return self._state.stop(self)

    def complete(self) -> bool:
        """Marca como completado."""
        return self._state.complete(self)

    def error(self, error_msg: str) -> bool:
        """Registra un error."""
        return self._state.error(self, error_msg)

    # =========================================================================
    # ACTUALIZACIÓN DE PROGRESO
    # =========================================================================

    def set_cuenta_actual(self, correo: str, idx: int) -> None:
        """Establece la cuenta actual."""
        self.progress.cuenta_actual_idx = idx
        if correo not in self.progress.cuentas:
            self.progress.cuentas[correo] = CuentaProgress(correo=correo)

    def set_carpeta_actual(self, correo: str, carpeta: str, total_mensajes: int) -> None:
        """Establece la carpeta actual para una cuenta."""
        if correo in self.progress.cuentas:
            self.progress.cuentas[correo].carpeta_actual = carpeta
            self.progress.cuentas[correo].total_mensajes = total_mensajes
            self.progress.cuentas[correo].mensaje_idx = 0

    def update_mensaje_idx(self, correo: str, idx: int) -> None:
        """Actualiza el índice del mensaje actual."""
        if correo in self.progress.cuentas:
            self.progress.cuentas[correo].mensaje_idx = idx

    def marcar_mensaje_procesado(self, correo: str, carpeta: str, message_id: str) -> None:
        """Marca un mensaje como procesado."""
        key = f"{correo}:{carpeta}"
        if key not in self.progress.mensajes_procesados:
            self.progress.mensajes_procesados[key] = []
        if message_id not in self.progress.mensajes_procesados[key]:
            self.progress.mensajes_procesados[key].append(message_id)

        if correo in self.progress.cuentas:
            self.progress.cuentas[correo].correos_procesados += 1
            self.progress.total_correos += 1

    def es_mensaje_procesado(self, correo: str, carpeta: str, message_id: str) -> bool:
        """Verifica si un mensaje ya fue procesado."""
        key = f"{correo}:{carpeta}"
        return message_id in self.progress.mensajes_procesados.get(key, [])

    def marcar_carpeta_completada(self, correo: str, carpeta: str) -> None:
        """Marca una carpeta como completada."""
        if correo in self.progress.cuentas:
            if carpeta not in self.progress.cuentas[correo].carpetas_completadas:
                self.progress.cuentas[correo].carpetas_completadas.append(carpeta)
            self.progress.cuentas[correo].carpeta_actual = None

    def es_carpeta_completada(self, correo: str, carpeta: str) -> bool:
        """Verifica si una carpeta ya fue completada."""
        if correo in self.progress.cuentas:
            return carpeta in self.progress.cuentas[correo].carpetas_completadas
        return False

    def marcar_cuenta_completada(self, correo: str) -> None:
        """Marca una cuenta como completada."""
        if correo in self.progress.cuentas:
            self.progress.cuentas[correo].completada = True

    def es_cuenta_completada(self, correo: str) -> bool:
        """Verifica si una cuenta ya fue completada."""
        if correo in self.progress.cuentas:
            return self.progress.cuentas[correo].completada
        return False

    def registrar_pdf(self, hash_archivo: str) -> None:
        """Registra un PDF descargado."""
        if hash_archivo not in self.progress.hashes_procesados:
            self.progress.hashes_procesados.append(hash_archivo)
        self.progress.total_pdfs += 1

    def es_hash_procesado(self, hash_archivo: str) -> bool:
        """Verifica si un hash ya fue procesado."""
        return hash_archivo in self.progress.hashes_procesados

    def registrar_error(self) -> None:
        """Incrementa contador de errores."""
        self.progress.total_errores += 1

    def get_punto_reanudacion(self) -> dict:
        """Obtiene el punto desde donde reanudar."""
        return {
            'cuenta_idx': self.progress.cuenta_actual_idx,
            'cuenta_correo': self.progress.orden_cuentas[self.progress.cuenta_actual_idx]
                            if self.progress.orden_cuentas else None,
            'carpeta': None,
            'mensaje_idx': 0
        }

    # =========================================================================
    # PERSISTENCIA
    # =========================================================================

    def save_state(self) -> bool:
        """Guarda el estado actual a JSON."""
        with _state_lock:
            try:
                data = self.progress.to_dict()
                data['_saved_at'] = datetime.utcnow().isoformat()

                temp_file = self.state_file + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                if os.path.exists(self.state_file):
                    os.remove(self.state_file)
                os.rename(temp_file, self.state_file)

                logger.debug(f"Estado guardado: {self.state_file}")
                return True
            except Exception as e:
                logger.error(f"Error guardando estado: {e}")
                return False

    def load_state(self) -> Optional[ScanProgress]:
        """Carga estado desde JSON."""
        if not os.path.exists(self.state_file):
            return None

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            progress = ScanProgress.from_dict(data)
            logger.debug(f"Estado cargado: {self.state_file} - Estado: {progress.estado}, PDFs: {progress.total_pdfs}, Correos: {progress.total_correos}")
            return progress
        except Exception as e:
            logger.error(f"Error cargando estado: {e}")
            return None

    def delete_state_file(self) -> bool:
        """Elimina el archivo de estado."""
        try:
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
                logger.debug(f"Archivo de estado eliminado: {self.state_file}")
            return True
        except Exception as e:
            logger.error(f"Error eliminando estado: {e}")
            return False

    def get_resumen(self) -> dict:
        """Obtiene resumen del estado actual."""
        return {
            'escaneo_id': self.escaneo_id,
            'estado': self.current_state,
            'puede_reanudar': self.can_resume,
            'total_pdfs': self.progress.total_pdfs,
            'total_correos': self.progress.total_correos,
            'total_errores': self.progress.total_errores,
            'cuentas_procesadas': sum(1 for c in self.progress.cuentas.values() if c.completada),
            'total_cuentas': len(self.progress.cuentas),
            'fecha_inicio': self.progress.fecha_inicio,
            'fecha_pausa': self.progress.fecha_pausa
        }


# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def obtener_escaneos_pausados() -> List[dict]:
    """Retorna lista de escaneos pausados/detenidos que pueden reanudarse."""
    pausados = []
    if os.path.exists(STATE_DIR):
        for archivo in os.listdir(STATE_DIR):
            if archivo.startswith('scan_state_') and archivo.endswith('.json'):
                try:
                    ruta = os.path.join(STATE_DIR, archivo)
                    with open(ruta, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    if data.get('estado') in ('paused', 'stopped', 'error'):
                        pausados.append({
                            'escaneo_id': data['escaneo_id'],
                            'usuario_id': data['usuario_id'],
                            'estado': data['estado'],
                            'total_pdfs': data.get('total_pdfs', 0),
                            'total_correos': data.get('total_correos', 0),
                            'fecha_pausa': data.get('fecha_pausa'),
                            'archivo': ruta
                        })
                except Exception:
                    pass
    return pausados


def limpiar_estados_antiguos(dias: int = 7) -> int:
    """Elimina estados más antiguos que X días."""
    eliminados = 0
    ahora = datetime.utcnow()

    if os.path.exists(STATE_DIR):
        for archivo in os.listdir(STATE_DIR):
            if archivo.startswith('scan_state_') and archivo.endswith('.json'):
                try:
                    ruta = os.path.join(STATE_DIR, archivo)
                    with open(ruta, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    saved_at = data.get('_saved_at')
                    if saved_at:
                        fecha = datetime.fromisoformat(saved_at)
                        if (ahora - fecha).days > dias:
                            os.remove(ruta)
                            eliminados += 1
                except Exception:
                    pass

    return eliminados
