"""
Modelos para el tracking de uso.

Este módulo es independiente y puede copiarse a otros proyectos Flask.
"""

from datetime import datetime
from app import db


class EventoUso(db.Model):
    """Registro de evento de uso (clic, navegación, etc.)."""
    __tablename__ = 'eventos_uso'

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    mes = db.Column(db.String(7), index=True)  # "2026-02" para agregación mensual

    # Qué página y elemento
    pagina = db.Column(db.String(200), index=True)
    elemento = db.Column(db.String(100))  # tag: button, a, input, etc.
    elemento_id = db.Column(db.String(100))  # id del elemento si existe
    elemento_texto = db.Column(db.String(200))  # texto visible del elemento
    accion = db.Column(db.String(50), default='click')  # click, submit, etc.

    # Posición para heatmap visual
    posicion_x = db.Column(db.Integer)
    posicion_y = db.Column(db.Integer)
    viewport_width = db.Column(db.Integer)
    viewport_height = db.Column(db.Integer)

    def __repr__(self):
        return f'<EventoUso {self.pagina} - {self.elemento_texto[:20] if self.elemento_texto else ""}>'

    @classmethod
    def registrar(cls, datos):
        """Registra un nuevo evento de uso.

        Args:
            datos: dict con pagina, elemento, elemento_id, elemento_texto,
                   accion, posicion_x, posicion_y, viewport_width, viewport_height
        """
        mes_actual = datetime.now().strftime('%Y-%m')

        evento = cls(
            mes=mes_actual,
            pagina=(datos.get('pagina') or '')[:200],
            elemento=(datos.get('elemento') or '')[:100],
            elemento_id=(datos.get('elemento_id') or '')[:100] if datos.get('elemento_id') else None,
            elemento_texto=(datos.get('elemento_texto') or '')[:200],
            accion=(datos.get('accion') or 'click')[:50],
            posicion_x=datos.get('posicion_x'),
            posicion_y=datos.get('posicion_y'),
            viewport_width=datos.get('viewport_width'),
            viewport_height=datos.get('viewport_height')
        )

        db.session.add(evento)
        return evento

    @classmethod
    def estadisticas_paginas(cls, mes):
        """Obtiene estadísticas de uso por página para un mes.

        Returns:
            Lista de tuplas (pagina, total_clics)
        """
        from sqlalchemy import func

        return db.session.query(
            cls.pagina,
            func.count(cls.id).label('total')
        ).filter(
            cls.mes == mes
        ).group_by(
            cls.pagina
        ).order_by(
            func.count(cls.id).desc()
        ).all()

    @classmethod
    def estadisticas_elementos(cls, mes, limite=50):
        """Obtiene estadísticas de uso por elemento para un mes.

        Returns:
            Lista de tuplas (pagina, elemento_texto, total_clics)
        """
        from sqlalchemy import func

        return db.session.query(
            cls.pagina,
            cls.elemento_texto,
            func.count(cls.id).label('total')
        ).filter(
            cls.mes == mes,
            cls.elemento_texto.isnot(None),
            cls.elemento_texto != ''
        ).group_by(
            cls.pagina,
            cls.elemento_texto
        ).order_by(
            func.count(cls.id).desc()
        ).limit(limite).all()

    @classmethod
    def datos_heatmap(cls, mes, pagina=None):
        """Obtiene datos de posición para generar heatmap.

        Args:
            mes: Mes en formato "YYYY-MM"
            pagina: Filtrar por página específica (opcional)

        Returns:
            Lista de tuplas (pagina, posicion_x, posicion_y, viewport_width, count)
        """
        from sqlalchemy import func

        query = db.session.query(
            cls.pagina,
            cls.posicion_x,
            cls.posicion_y,
            cls.viewport_width,
            func.count(cls.id).label('count')
        ).filter(
            cls.mes == mes,
            cls.posicion_x.isnot(None),
            cls.posicion_y.isnot(None)
        )

        if pagina:
            query = query.filter(cls.pagina == pagina)

        return query.group_by(
            cls.pagina,
            cls.posicion_x,
            cls.posicion_y,
            cls.viewport_width
        ).all()

    @classmethod
    def meses_disponibles(cls):
        """Obtiene lista de meses con datos disponibles.

        Returns:
            Lista de strings "YYYY-MM" ordenados descendentemente
        """
        from sqlalchemy import func

        result = db.session.query(
            cls.mes
        ).distinct().order_by(
            cls.mes.desc()
        ).all()

        return [r[0] for r in result]

    @classmethod
    def limpiar_antiguos(cls, meses_a_mantener=6):
        """Elimina eventos más antiguos que N meses.

        Args:
            meses_a_mantener: Cantidad de meses a conservar

        Returns:
            Cantidad de registros eliminados
        """
        from datetime import datetime
        from dateutil.relativedelta import relativedelta

        fecha_limite = datetime.now() - relativedelta(months=meses_a_mantener)
        mes_limite = fecha_limite.strftime('%Y-%m')

        eliminados = cls.query.filter(cls.mes < mes_limite).delete()
        db.session.commit()

        return eliminados
