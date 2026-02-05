"""
Servicio de gestión de escaneos.

Encapsula la lógica de negocio relacionada con escaneos de correo,
cuentas Gmail y operaciones relacionadas.
"""

from datetime import datetime
from typing import Optional, List, Tuple
from flask import current_app

from app import db
from app.models import Escaneo, CuentaGmail, LogEscaneo, Usuario


class EscaneoService:
    """Servicio para operaciones de escaneos."""

    @staticmethod
    def obtener_cuenta_usuario(cuenta_id: int, usuario: Usuario) -> Optional[CuentaGmail]:
        """
        Obtiene una cuenta Gmail verificando que pertenezca al usuario.

        Returns:
            CuentaGmail o None si no existe o no pertenece al usuario
        """
        return CuentaGmail.query.filter_by(
            id=cuenta_id,
            usuario_id=usuario.id
        ).first()

    @staticmethod
    def listar_cuentas_usuario(usuario: Usuario, solo_activas: bool = True) -> List[CuentaGmail]:
        """Lista las cuentas Gmail de un usuario."""
        query = CuentaGmail.query.filter_by(usuario_id=usuario.id)
        if solo_activas:
            query = query.filter_by(activa=True)
        return query.order_by(CuentaGmail.correo_gmail).all()

    @staticmethod
    def agregar_cuenta(usuario: Usuario, correo_gmail: str,
                       contrasena_app: str) -> Tuple[Optional[CuentaGmail], str]:
        """
        Agrega una nueva cuenta Gmail.

        Returns:
            Tuple[CuentaGmail|None, str]: Cuenta creada y mensaje
        """
        # Verificar si ya existe
        existente = CuentaGmail.query.filter_by(
            usuario_id=usuario.id,
            correo_gmail=correo_gmail
        ).first()

        if existente:
            return None, "Ya tienes esta cuenta Gmail configurada"

        cuenta = CuentaGmail(
            usuario_id=usuario.id,
            correo_gmail=correo_gmail
        )
        cuenta.establecer_contrasena_app(contrasena_app)

        db.session.add(cuenta)
        db.session.commit()

        return cuenta, "Cuenta agregada exitosamente"

    @staticmethod
    def eliminar_cuenta(cuenta: CuentaGmail) -> Tuple[bool, str]:
        """Elimina una cuenta Gmail."""
        try:
            db.session.delete(cuenta)
            db.session.commit()
            return True, "Cuenta eliminada"
        except Exception as e:
            db.session.rollback()
            return False, f"Error al eliminar: {str(e)}"

    @staticmethod
    def obtener_escaneo_usuario(escaneo_id: int, usuario: Usuario) -> Optional[Escaneo]:
        """
        Obtiene un escaneo verificando que pertenezca al usuario.

        Returns:
            Escaneo o None si no existe o no pertenece al usuario
        """
        return Escaneo.query.filter_by(
            id=escaneo_id,
            usuario_id=usuario.id
        ).first()

    @staticmethod
    def listar_escaneos_usuario(usuario: Usuario, limite: int = None,
                                 estado: str = None) -> List[Escaneo]:
        """Lista los escaneos de un usuario."""
        query = Escaneo.query.filter_by(usuario_id=usuario.id)

        if estado:
            query = query.filter_by(estado=estado)

        query = query.order_by(Escaneo.fecha_inicio.desc())

        if limite:
            query = query.limit(limite)

        return query.all()

    @staticmethod
    def crear_escaneo(usuario: Usuario, cuenta_gmail_id: int = None,
                      dominios_filtro: str = None, fecha_desde=None,
                      fecha_hasta=None) -> Escaneo:
        """Crea un nuevo registro de escaneo."""
        escaneo = Escaneo(
            usuario_id=usuario.id,
            cuenta_gmail_id=cuenta_gmail_id,
            dominios_filtro=dominios_filtro,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            estado='en_progreso'
        )
        db.session.add(escaneo)
        db.session.commit()
        return escaneo

    @staticmethod
    def finalizar_escaneo(escaneo: Escaneo, estado: str = 'completado',
                          mensaje_error: str = None) -> None:
        """Finaliza un escaneo actualizando su estado."""
        escaneo.estado = estado
        escaneo.fecha_fin = datetime.utcnow()
        if mensaje_error:
            escaneo.mensaje_error = mensaje_error
        db.session.commit()

    @staticmethod
    def obtener_escaneo_activo(usuario: Usuario) -> Optional[Escaneo]:
        """Obtiene el escaneo activo del usuario si existe."""
        return Escaneo.query.filter_by(
            usuario_id=usuario.id,
            estado='en_progreso'
        ).first()

    @staticmethod
    def cancelar_escaneo(escaneo: Escaneo) -> Tuple[bool, str]:
        """Cancela un escaneo en progreso."""
        if escaneo.estado != 'en_progreso':
            return False, "El escaneo no está en progreso"

        escaneo.estado = 'cancelado'
        escaneo.fecha_fin = datetime.utcnow()
        db.session.commit()

        return True, "Escaneo cancelado"

    @staticmethod
    def obtener_estadisticas_usuario(usuario: Usuario) -> dict:
        """Obtiene estadísticas de escaneos del usuario."""
        from sqlalchemy import func

        total = Escaneo.query.filter_by(usuario_id=usuario.id).count()
        completados = Escaneo.query.filter_by(
            usuario_id=usuario.id, estado='completado'
        ).count()

        pdfs_total = db.session.query(func.sum(Escaneo.pdfs_descargados)).filter(
            Escaneo.usuario_id == usuario.id
        ).scalar() or 0

        correos_total = db.session.query(func.sum(Escaneo.correos_escaneados)).filter(
            Escaneo.usuario_id == usuario.id
        ).scalar() or 0

        return {
            'total_escaneos': total,
            'escaneos_completados': completados,
            'total_pdfs_descargados': pdfs_total,
            'total_correos_escaneados': correos_total
        }
