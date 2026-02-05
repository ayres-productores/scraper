"""
Sistema de backup de PDFs de pólizas.

Guarda copias permanentes de los PDFs cuando se asignan a pólizas.
Estos backups NO se eliminan cuando se limpian los archivos del extractor.
"""

import os
import shutil
from datetime import datetime
from flask import current_app


def obtener_carpeta_backup():
    """Obtiene la carpeta base de backup."""
    return current_app.config.get('POLIZAS_BACKUP_FOLDER',
                                   os.path.join(os.path.dirname(current_app.root_path), 'polizas_backup'))


def generar_ruta_backup(cliente_id, poliza_id, nombre_original):
    """
    Genera la ruta donde se guardará el backup del PDF.

    Estructura: polizas_backup/{cliente_id}/{poliza_id}_{nombre_original}
    """
    carpeta_base = obtener_carpeta_backup()
    carpeta_cliente = os.path.join(carpeta_base, str(cliente_id))

    # Crear carpeta del cliente si no existe
    if not os.path.exists(carpeta_cliente):
        os.makedirs(carpeta_cliente)

    # Sanitizar nombre del archivo
    nombre_seguro = "".join(c for c in nombre_original if c.isalnum() or c in '._- ')
    nombre_seguro = nombre_seguro[:100]  # Limitar longitud

    # Agregar prefijo con ID de póliza
    nombre_backup = f"poliza_{poliza_id}_{nombre_seguro}"
    if not nombre_backup.lower().endswith('.pdf'):
        nombre_backup += '.pdf'

    return os.path.join(carpeta_cliente, nombre_backup)


def crear_backup_poliza(poliza, archivo_origen=None):
    """
    Crea un backup del PDF de una póliza.

    Args:
        poliza: Objeto PolizaCliente
        archivo_origen: Ruta al archivo PDF origen (opcional, usa poliza.archivo si no se provee)

    Returns:
        str: Ruta al backup creado, o None si falló
    """
    from app import db

    # Determinar archivo origen
    if archivo_origen and os.path.exists(archivo_origen):
        ruta_origen = archivo_origen
        nombre_original = os.path.basename(archivo_origen)
    elif poliza.archivo and os.path.exists(poliza.archivo.ruta_archivo):
        ruta_origen = poliza.archivo.ruta_archivo
        nombre_original = poliza.archivo.nombre_archivo
    else:
        return None

    # Generar ruta de backup
    ruta_backup = generar_ruta_backup(poliza.cliente_id, poliza.id, nombre_original)

    try:
        # Copiar archivo
        shutil.copy2(ruta_origen, ruta_backup)

        # Actualizar póliza con ruta de backup
        poliza.ruta_pdf_backup = ruta_backup
        poliza.fecha_backup = datetime.utcnow()
        db.session.commit()

        return ruta_backup

    except Exception as e:
        print(f"Error creando backup de póliza {poliza.id}: {e}")
        return None


def verificar_backup_existe(poliza):
    """Verifica si el backup de una póliza existe físicamente."""
    if not poliza.ruta_pdf_backup:
        return False
    return os.path.exists(poliza.ruta_pdf_backup)


def obtener_pdf_poliza(poliza):
    """
    Obtiene la ruta al PDF de una póliza.
    Prioriza el backup, luego el archivo original.

    Returns:
        tuple: (ruta, es_backup) o (None, None) si no existe
    """
    # Primero intentar backup
    if poliza.ruta_pdf_backup and os.path.exists(poliza.ruta_pdf_backup):
        return poliza.ruta_pdf_backup, True

    # Luego intentar archivo original
    if poliza.archivo and os.path.exists(poliza.archivo.ruta_archivo):
        return poliza.archivo.ruta_archivo, False

    return None, None


def crear_backups_pendientes(usuario_id=None):
    """
    Crea backups para todas las pólizas que tienen archivo pero no backup.

    Args:
        usuario_id: Si se especifica, solo para pólizas de este usuario

    Returns:
        tuple: (creados, errores)
    """
    from app.models import PolizaCliente, Cliente, ArchivoDescargado

    query = PolizaCliente.query.filter(
        PolizaCliente.archivo_id.isnot(None),
        PolizaCliente.ruta_pdf_backup.is_(None)
    )

    if usuario_id:
        query = query.join(Cliente).filter(Cliente.usuario_id == usuario_id)

    polizas = query.all()

    creados = 0
    errores = 0

    for poliza in polizas:
        resultado = crear_backup_poliza(poliza)
        if resultado:
            creados += 1
        else:
            errores += 1

    return creados, errores


def eliminar_backup_poliza(poliza):
    """
    Elimina el backup de una póliza (usar con precaución).

    Args:
        poliza: Objeto PolizaCliente

    Returns:
        bool: True si se eliminó correctamente
    """
    from app import db

    if not poliza.ruta_pdf_backup:
        return True

    try:
        if os.path.exists(poliza.ruta_pdf_backup):
            os.remove(poliza.ruta_pdf_backup)

        poliza.ruta_pdf_backup = None
        poliza.fecha_backup = None
        db.session.commit()

        return True

    except Exception as e:
        print(f"Error eliminando backup de póliza {poliza.id}: {e}")
        return False


def obtener_estadisticas_backup(usuario_id=None):
    """
    Obtiene estadísticas de backups.

    Returns:
        dict con estadísticas
    """
    from app.models import PolizaCliente, Cliente
    from sqlalchemy import func

    query = PolizaCliente.query
    if usuario_id:
        query = query.join(Cliente).filter(Cliente.usuario_id == usuario_id)

    total_polizas = query.count()
    con_archivo = query.filter(PolizaCliente.archivo_id.isnot(None)).count()
    con_backup = query.filter(PolizaCliente.ruta_pdf_backup.isnot(None)).count()

    # Verificar cuántos backups existen físicamente
    polizas_con_backup = query.filter(PolizaCliente.ruta_pdf_backup.isnot(None)).all()
    backups_validos = sum(1 for p in polizas_con_backup if verificar_backup_existe(p))

    return {
        'total_polizas': total_polizas,
        'con_archivo': con_archivo,
        'con_backup': con_backup,
        'backups_validos': backups_validos,
        'sin_backup': con_archivo - con_backup
    }
