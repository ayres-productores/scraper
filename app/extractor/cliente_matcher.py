"""
Servicio para buscar clientes existentes basándose en datos extraídos del PDF.

Este módulo permite detectar si un PDF corresponde a un cliente existente
al momento del escaneo, antes de que el usuario procese manualmente el PDF.
"""

import logging
from typing import Optional, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class ClienteMatcher:
    """
    Busca clientes existentes basándose en datos extraídos del PDF.

    La búsqueda sigue esta prioridad:
    1. Match por documento (exacto) → confianza 1.0
    2. Match por nombre (fuzzy > 0.75) → confianza = ratio
    """

    def __init__(self, db_session=None):
        """
        Inicializa el matcher.

        Args:
            db_session: Sesión de SQLAlchemy opcional.
                        Si no se proporciona, usa db.session de Flask.
        """
        self._db_session = db_session

    @property
    def session(self):
        """Obtiene la sesión de base de datos apropiada."""
        if self._db_session:
            return self._db_session
        # Fallback a sesión de Flask
        from app import db
        return db.session

    def buscar_cliente(
        self,
        usuario_id: int,
        documento: Optional[str] = None,
        nombre: Optional[str] = None
    ) -> Tuple[Optional['Cliente'], Optional[str], float]:
        """
        Busca un cliente existente que coincida con los datos proporcionados.

        Args:
            usuario_id: ID del usuario dueño de los clientes
            documento: DNI/CUIT extraído del PDF (puede tener puntos, guiones, etc.)
            nombre: Nombre del asegurado extraído del PDF

        Returns:
            Tuple (cliente, tipo_match, confianza):
            - cliente: Objeto Cliente encontrado o None
            - tipo_match: 'documento' | 'nombre_fuzzy' | None
            - confianza: 1.0 para documento exacto, 0.75-1.0 para nombre fuzzy, 0.0 si no hay match
        """
        from app.models import Cliente

        # Prioridad 1: Buscar por documento (match exacto)
        if documento:
            cliente, confianza = self._buscar_por_documento(usuario_id, documento)
            if cliente:
                logger.debug(f"ClienteMatcher: Match por documento para usuario {usuario_id}")
                return cliente, 'documento', confianza

        # Prioridad 2: Buscar por nombre (fuzzy match)
        if nombre:
            cliente, confianza = self._buscar_por_nombre(usuario_id, nombre)
            if cliente:
                logger.debug(f"ClienteMatcher: Match por nombre (confianza={confianza:.2f}) para usuario {usuario_id}")
                return cliente, 'nombre_fuzzy', confianza

        return None, None, 0.0

    def _buscar_por_documento(
        self,
        usuario_id: int,
        documento: str
    ) -> Tuple[Optional['Cliente'], float]:
        """
        Busca un cliente por documento (DNI/CUIT).

        La comparación se hace solo con dígitos para ignorar formato.
        """
        from app.models import Cliente

        # Limpiar documento: solo dígitos
        doc_limpio = ''.join(c for c in documento if c.isdigit())

        # Documento muy corto no es válido
        if len(doc_limpio) < 7:
            return None, 0.0

        # Buscar clientes del usuario
        clientes = self.session.query(Cliente).filter(
            Cliente.usuario_id == usuario_id,
            Cliente.activo == True,
            Cliente.documento_identidad.isnot(None)
        ).all()

        for cliente in clientes:
            doc_cliente = ''.join(c for c in cliente.documento_identidad if c.isdigit())
            if doc_limpio == doc_cliente:
                return cliente, 1.0  # Match exacto por documento

        return None, 0.0

    def _buscar_por_nombre(
        self,
        usuario_id: int,
        nombre: str,
        umbral: float = 0.75
    ) -> Tuple[Optional['Cliente'], float]:
        """
        Busca un cliente por nombre usando coincidencia fuzzy.

        Args:
            usuario_id: ID del usuario
            nombre: Nombre a buscar
            umbral: Ratio mínimo de similitud (default 0.75)

        Returns:
            Tuple (cliente_mejor_match, ratio)
        """
        from app.models import Cliente

        nombre_upper = nombre.upper().strip()
        if not nombre_upper:
            return None, 0.0

        # Buscar clientes del usuario (limitar para performance)
        clientes = self.session.query(Cliente).filter(
            Cliente.usuario_id == usuario_id,
            Cliente.activo == True
        ).limit(500).all()

        mejor_cliente = None
        mejor_ratio = 0.0

        for cliente in clientes:
            nombre_cliente = cliente.nombre_completo.upper()
            ratio = SequenceMatcher(None, nombre_upper, nombre_cliente).ratio()

            if ratio > mejor_ratio and ratio >= umbral:
                mejor_cliente = cliente
                mejor_ratio = ratio

        if mejor_cliente:
            return mejor_cliente, mejor_ratio

        return None, 0.0

    def buscar_multiples(
        self,
        usuario_id: int,
        documento: Optional[str] = None,
        nombre: Optional[str] = None,
        limite: int = 5
    ) -> list:
        """
        Busca múltiples clientes que coincidan (para sugerir opciones).

        Returns:
            Lista de dicts con: id, nombre, documento, telefono, score, razon
        """
        from app.models import Cliente

        sugeridos = []

        # Buscar por documento
        if documento:
            doc_limpio = ''.join(c for c in documento if c.isdigit())
            if len(doc_limpio) >= 7:
                clientes = self.session.query(Cliente).filter(
                    Cliente.usuario_id == usuario_id,
                    Cliente.activo == True,
                    Cliente.documento_identidad.isnot(None)
                ).all()

                for c in clientes:
                    doc_cliente = ''.join(x for x in c.documento_identidad if x.isdigit())
                    if doc_limpio == doc_cliente:
                        sugeridos.append({
                            'id': c.id,
                            'nombre': c.nombre_completo,
                            'documento': c.documento_identidad,
                            'telefono': c.telefono_whatsapp,
                            'email': c.email,
                            'score': 1.0,
                            'razon': 'documento_coincide'
                        })

        # Buscar por nombre si no hay resultados por documento
        if not sugeridos and nombre:
            nombre_upper = nombre.upper().strip()
            clientes = self.session.query(Cliente).filter(
                Cliente.usuario_id == usuario_id,
                Cliente.activo == True
            ).limit(200).all()

            for c in clientes:
                ratio = SequenceMatcher(None, nombre_upper, c.nombre_completo.upper()).ratio()
                if ratio > 0.75:
                    sugeridos.append({
                        'id': c.id,
                        'nombre': c.nombre_completo,
                        'documento': c.documento_identidad,
                        'telefono': c.telefono_whatsapp,
                        'email': c.email,
                        'score': ratio,
                        'razon': 'nombre_similar'
                    })

        # Ordenar por score y limitar
        sugeridos = sorted(sugeridos, key=lambda x: x['score'], reverse=True)[:limite]

        return sugeridos
