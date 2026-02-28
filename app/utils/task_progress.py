"""
Almacenamiento thread-safe para progreso de tareas en memoria.

Este módulo proporciona una clase singleton para almacenar el progreso
de tareas de larga duración (como análisis de PDFs en lote) de manera
segura para acceso concurrente.

Características:
- Thread-safe con locks
- TTL automático (limpieza de tareas antiguas)
- Límite de tamaño para evitar memory leaks
- Acceso simplificado con métodos de conveniencia

Uso:
    from app.utils.task_progress import task_store

    # Crear tarea
    task_store.create('mi-tarea-123', {'status': 'iniciando'})

    # Actualizar progreso
    task_store.update('mi-tarea-123', procesados=5, total=10)

    # Obtener progreso
    progreso = task_store.get('mi-tarea-123')

    # Eliminar tarea
    task_store.delete('mi-tarea-123')
"""

import threading
import time
from typing import Dict, Any, Optional
from datetime import datetime


class TaskProgressStore:
    """
    Almacenamiento thread-safe para progreso de tareas.

    Esta clase implementa un singleton que gestiona el estado de tareas
    de larga duración con protección contra acceso concurrente.
    """

    _instance = None
    _instance_lock = threading.Lock()

    # Configuración
    DEFAULT_TTL_SECONDS = 3600  # 1 hora
    MAX_TASKS = 100  # Máximo de tareas en memoria
    CLEANUP_INTERVAL = 300  # 5 minutos

    def __new__(cls):
        """Implementación de singleton thread-safe."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Inicializa el store (solo la primera vez)."""
        if self._initialized:
            return

        self._lock = threading.RLock()  # RLock permite re-entrada
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._last_cleanup = time.time()
        self._initialized = True

    def _cleanup_expired(self):
        """
        Limpia tareas expiradas (TTL excedido).
        Se ejecuta automáticamente cada CLEANUP_INTERVAL.
        """
        now = time.time()

        # Solo limpiar si pasó el intervalo
        if now - self._last_cleanup < self.CLEANUP_INTERVAL:
            return

        self._last_cleanup = now
        expired_keys = []

        for task_id, task in self._tasks.items():
            created_at = task.get('_created_at', 0)
            ttl = task.get('_ttl', self.DEFAULT_TTL_SECONDS)

            if now - created_at > ttl:
                expired_keys.append(task_id)

        for key in expired_keys:
            del self._tasks[key]

    def _enforce_max_size(self):
        """
        Elimina las tareas más antiguas si se excede MAX_TASKS.
        """
        if len(self._tasks) <= self.MAX_TASKS:
            return

        # Ordenar por tiempo de creación y eliminar las más antiguas
        sorted_tasks = sorted(
            self._tasks.items(),
            key=lambda x: x[1].get('_created_at', 0)
        )

        # Eliminar el 20% más antiguo
        to_remove = len(sorted_tasks) - int(self.MAX_TASKS * 0.8)
        for task_id, _ in sorted_tasks[:to_remove]:
            del self._tasks[task_id]

    def create(self, task_id: str, initial_data: Dict[str, Any] = None,
               ttl: int = None) -> Dict[str, Any]:
        """
        Crea una nueva tarea.

        Args:
            task_id: Identificador único de la tarea
            initial_data: Datos iniciales (opcional)
            ttl: Time-to-live en segundos (opcional, default 1 hora)

        Returns:
            dict: Los datos de la tarea creada
        """
        with self._lock:
            self._cleanup_expired()
            self._enforce_max_size()

            task_data = initial_data.copy() if initial_data else {}
            task_data.update({
                '_created_at': time.time(),
                '_updated_at': time.time(),
                '_ttl': ttl or self.DEFAULT_TTL_SECONDS,
                'task_id': task_id,
            })

            self._tasks[task_id] = task_data
            return task_data

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene los datos de una tarea.

        Args:
            task_id: Identificador de la tarea

        Returns:
            dict o None: Datos de la tarea (copia) o None si no existe
        """
        with self._lock:
            self._cleanup_expired()

            if task_id not in self._tasks:
                return None

            # Retornar copia para evitar modificaciones no protegidas
            return self._tasks[task_id].copy()

    def update(self, task_id: str, **kwargs) -> bool:
        """
        Actualiza campos de una tarea existente.

        Args:
            task_id: Identificador de la tarea
            **kwargs: Campos a actualizar

        Returns:
            bool: True si se actualizó, False si no existe
        """
        with self._lock:
            if task_id not in self._tasks:
                return False

            self._tasks[task_id].update(kwargs)
            self._tasks[task_id]['_updated_at'] = time.time()
            return True

    def append_log(self, task_id: str, log_entry: Dict[str, Any]) -> bool:
        """
        Agrega una entrada al log de una tarea.

        Args:
            task_id: Identificador de la tarea
            log_entry: Entrada de log a agregar

        Returns:
            bool: True si se agregó, False si no existe
        """
        with self._lock:
            if task_id not in self._tasks:
                return False

            if 'log' not in self._tasks[task_id]:
                self._tasks[task_id]['log'] = []

            # Agregar timestamp si no tiene
            if 'timestamp' not in log_entry:
                log_entry['timestamp'] = datetime.now().isoformat()

            self._tasks[task_id]['log'].append(log_entry)
            self._tasks[task_id]['_updated_at'] = time.time()
            return True

    def delete(self, task_id: str) -> bool:
        """
        Elimina una tarea.

        Args:
            task_id: Identificador de la tarea

        Returns:
            bool: True si se eliminó, False si no existía
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    def exists(self, task_id: str) -> bool:
        """
        Verifica si una tarea existe.

        Args:
            task_id: Identificador de la tarea

        Returns:
            bool: True si existe
        """
        with self._lock:
            return task_id in self._tasks

    def get_all(self, filter_fn=None) -> Dict[str, Dict[str, Any]]:
        """
        Obtiene todas las tareas (opcionalmente filtradas).

        Args:
            filter_fn: Función de filtro (opcional)

        Returns:
            dict: Diccionario de tareas (copias)
        """
        with self._lock:
            self._cleanup_expired()

            if filter_fn:
                return {
                    k: v.copy() for k, v in self._tasks.items()
                    if filter_fn(k, v)
                }

            return {k: v.copy() for k, v in self._tasks.items()}

    def count(self) -> int:
        """
        Retorna el número de tareas almacenadas.

        Returns:
            int: Cantidad de tareas
        """
        with self._lock:
            return len(self._tasks)

    def clear(self):
        """Elimina todas las tareas."""
        with self._lock:
            self._tasks.clear()


# Instancia singleton global
task_store = TaskProgressStore()


# ============================================================================
# FUNCIONES DE CONVENIENCIA PARA COMPATIBILIDAD CON CÓDIGO EXISTENTE
# ============================================================================

def get_progreso_analisis() -> Dict[str, Dict[str, Any]]:
    """
    Obtiene el diccionario completo de progreso (compatible con código legacy).

    NOTA: Esta función retorna copias de los datos. Para modificar,
    usar task_store.update() o task_store.append_log().

    Returns:
        dict: Diccionario de tareas de análisis
    """
    return task_store.get_all(
        filter_fn=lambda k, v: v.get('type') == 'analisis_pdf'
    )


def crear_tarea_analisis(task_id: str) -> Dict[str, Any]:
    """
    Crea una nueva tarea de análisis de PDFs.

    Args:
        task_id: Identificador único

    Returns:
        dict: Datos de la tarea
    """
    return task_store.create(task_id, {
        'type': 'analisis_pdf',
        'status': 'iniciando',
        'total': 0,
        'procesados': 0,
        'errores': 0,
        'actual': None,
        'log': [],
        'finalizado': False
    })
