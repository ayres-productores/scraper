"""
Servicio de gestión de archivos descargados.

Encapsula la lógica de negocio relacionada con archivos PDF,
verificación de propiedad y operaciones de archivos.
"""

import os
import hashlib
from datetime import datetime
from typing import Optional, List, Tuple
from flask import current_app

from app import db
from app.models import ArchivoDescargado, Escaneo, Usuario, RegistroAnalisisPDF


class ArchivoService:
    """Servicio para operaciones de archivos."""

    @staticmethod
    def obtener_archivo_usuario(archivo_id: int, usuario: Usuario) -> Optional[ArchivoDescargado]:
        """
        Obtiene un archivo verificando que pertenezca al usuario.

        Returns:
            ArchivoDescargado o None si no existe o no pertenece al usuario
        """
        return ArchivoDescargado.query.join(Escaneo).filter(
            ArchivoDescargado.id == archivo_id,
            Escaneo.usuario_id == usuario.id
        ).first()

    @staticmethod
    def listar_archivos_usuario(usuario: Usuario, limite: int = None,
                                 ordenar_por: str = 'fecha_descarga',
                                 orden_desc: bool = True) -> List[ArchivoDescargado]:
        """
        Lista archivos de un usuario con opciones de ordenamiento.

        Args:
            usuario: Usuario propietario
            limite: Cantidad máxima de resultados
            ordenar_por: Campo para ordenar ('fecha_descarga', 'nombre_archivo', 'tamano_bytes')
            orden_desc: True para orden descendente

        Returns:
            Lista de ArchivoDescargado
        """
        query = ArchivoDescargado.query.join(Escaneo).filter(
            Escaneo.usuario_id == usuario.id
        )

        # Aplicar ordenamiento
        campo_orden = getattr(ArchivoDescargado, ordenar_por, ArchivoDescargado.fecha_descarga)
        if orden_desc:
            query = query.order_by(campo_orden.desc())
        else:
            query = query.order_by(campo_orden.asc())

        if limite:
            query = query.limit(limite)

        return query.all()

    @staticmethod
    def eliminar_archivo(archivo: ArchivoDescargado) -> Tuple[bool, str]:
        """
        Elimina un archivo de la BD y del disco.

        Returns:
            Tuple[bool, str]: Éxito y mensaje
        """
        try:
            # Eliminar registros relacionados
            RegistroAnalisisPDF.query.filter_by(archivo_id=archivo.id).delete()

            # Eliminar archivo físico si existe
            if archivo.ruta_archivo and os.path.exists(archivo.ruta_archivo):
                os.remove(archivo.ruta_archivo)

            # Eliminar de BD
            db.session.delete(archivo)
            db.session.commit()

            return True, "Archivo eliminado correctamente"
        except Exception as e:
            db.session.rollback()
            return False, f"Error al eliminar: {str(e)}"

    @staticmethod
    def calcular_hash(ruta_archivo: str) -> Optional[str]:
        """Calcula el hash SHA-256 de un archivo."""
        try:
            with open(ruta_archivo, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return None

    @staticmethod
    def archivo_existe_por_hash(hash_archivo: str, usuario: Usuario) -> Optional[ArchivoDescargado]:
        """Busca si ya existe un archivo con el mismo hash para el usuario."""
        return ArchivoDescargado.query.join(Escaneo).filter(
            ArchivoDescargado.hash_archivo == hash_archivo,
            Escaneo.usuario_id == usuario.id
        ).first()

    @staticmethod
    def contar_archivos_usuario(usuario: Usuario) -> int:
        """Cuenta la cantidad de archivos de un usuario."""
        return ArchivoDescargado.query.join(Escaneo).filter(
            Escaneo.usuario_id == usuario.id
        ).count()

    @staticmethod
    def obtener_estadisticas_usuario(usuario: Usuario) -> dict:
        """
        Obtiene estadísticas de archivos del usuario.

        Returns:
            dict con total_archivos, tamano_total, por_compania, etc.
        """
        from sqlalchemy import func

        archivos = ArchivoDescargado.query.join(Escaneo).filter(
            Escaneo.usuario_id == usuario.id
        )

        total = archivos.count()
        tamano_total = db.session.query(func.sum(ArchivoDescargado.tamano_bytes)).join(
            Escaneo
        ).filter(Escaneo.usuario_id == usuario.id).scalar() or 0

        # Por compañía
        por_compania = db.session.query(
            ArchivoDescargado.compania_id,
            func.count(ArchivoDescargado.id)
        ).join(Escaneo).filter(
            Escaneo.usuario_id == usuario.id
        ).group_by(ArchivoDescargado.compania_id).all()

        return {
            'total_archivos': total,
            'tamano_total_bytes': tamano_total,
            'tamano_total_mb': round(tamano_total / (1024 * 1024), 2) if tamano_total else 0,
            'por_compania': dict(por_compania)
        }
