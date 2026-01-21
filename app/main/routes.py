"""
Rutas principales de la aplicación
"""

from flask import Blueprint, render_template, redirect, url_for, send_file, abort, current_app, request
from flask_login import login_required, current_user
from app.models import Escaneo, ArchivoDescargado, CuentaGmail, Compania
from datetime import datetime, timedelta
from sqlalchemy import func
import os
import zipfile
import io

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Página principal - redirige al dashboard o login."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Panel principal del usuario."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    # Estadísticas del usuario
    total_cuentas = current_user.cuentas_gmail.filter_by(activa=True).count()
    total_escaneos = current_user.escaneos.count()
    escaneos_completados = current_user.escaneos.filter_by(estado='completado').count()

    # PDFs descargados en total
    total_pdfs = 0
    for escaneo in current_user.escaneos.all():
        total_pdfs += escaneo.pdfs_descargados or 0

    # Últimos escaneos
    ultimos_escaneos = current_user.escaneos.order_by(
        Escaneo.fecha_inicio.desc()
    ).limit(5).all()

    # Escaneo en progreso
    escaneo_activo = current_user.escaneos.filter_by(estado='en_progreso').first()

    # Estadísticas de los últimos 30 días
    hace_30_dias = datetime.utcnow() - timedelta(days=30)
    escaneos_recientes = current_user.escaneos.filter(
        Escaneo.fecha_inicio >= hace_30_dias
    ).count()

    pdfs_recientes = 0
    for escaneo in current_user.escaneos.filter(Escaneo.fecha_inicio >= hace_30_dias).all():
        pdfs_recientes += escaneo.pdfs_descargados or 0

    # Top compañías por cantidad de documentos del usuario
    top_companias = Compania.query.join(ArchivoDescargado).join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    ).group_by(Compania.id).order_by(
        func.count(ArchivoDescargado.id).desc()
    ).limit(5).all()

    # Contar documentos por compañía para el usuario actual
    companias_con_conteo = []
    for compania in top_companias:
        conteo = ArchivoDescargado.query.join(Escaneo).filter(
            Escaneo.usuario_id == current_user.id,
            ArchivoDescargado.compania_id == compania.id
        ).count()
        companias_con_conteo.append({
            'compania': compania,
            'cantidad': conteo
        })

    return render_template('main/dashboard.html',
                          total_cuentas=total_cuentas,
                          total_escaneos=total_escaneos,
                          escaneos_completados=escaneos_completados,
                          total_pdfs=total_pdfs,
                          ultimos_escaneos=ultimos_escaneos,
                          escaneo_activo=escaneo_activo,
                          escaneos_recientes=escaneos_recientes,
                          pdfs_recientes=pdfs_recientes,
                          top_companias=companias_con_conteo)


@main_bp.route('/archivos')
@login_required
def archivos():
    """Listado de archivos PDF descargados con vista agrupada por compañía."""
    if current_user.debe_cambiar_contrasena:
        return redirect(url_for('auth.cambiar_contrasena_obligatorio'))

    # Parámetros de filtro
    compania_id = request.args.get('compania', type=int)
    vista = request.args.get('vista', 'agrupada')  # 'agrupada' o 'lista'

    # Query base de archivos del usuario
    query = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    )

    # Filtrar por compañía si se especifica
    if compania_id:
        query = query.filter(ArchivoDescargado.compania_id == compania_id)

    archivos = query.order_by(ArchivoDescargado.fecha_descarga.desc()).all()

    # Calcular tamaño total
    tamano_total = sum(a.tamano_bytes or 0 for a in archivos)

    # Obtener todas las compañías que tienen archivos del usuario
    companias_con_archivos = Compania.query.join(ArchivoDescargado).join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    ).distinct().all()

    # Agrupar archivos por compañía para la vista agrupada
    archivos_por_compania = {}
    archivos_sin_compania = []

    for archivo in archivos:
        if archivo.compania:
            if archivo.compania.id not in archivos_por_compania:
                archivos_por_compania[archivo.compania.id] = {
                    'compania': archivo.compania,
                    'archivos': [],
                    'tamano_total': 0
                }
            archivos_por_compania[archivo.compania.id]['archivos'].append(archivo)
            archivos_por_compania[archivo.compania.id]['tamano_total'] += archivo.tamano_bytes or 0
        else:
            archivos_sin_compania.append(archivo)

    # Convertir a lista ordenada por cantidad de documentos
    grupos_companias = sorted(
        archivos_por_compania.values(),
        key=lambda x: len(x['archivos']),
        reverse=True
    )

    return render_template('main/archivos.html',
                          archivos=archivos,
                          tamano_total=tamano_total,
                          companias=companias_con_archivos,
                          grupos_companias=grupos_companias,
                          archivos_sin_compania=archivos_sin_compania,
                          compania_seleccionada=compania_id,
                          vista=vista)


@main_bp.route('/archivos/descargar/<int:archivo_id>')
@login_required
def descargar_archivo(archivo_id):
    """Descarga un archivo PDF individual."""
    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    if os.path.exists(archivo.ruta_archivo):
        return send_file(
            archivo.ruta_archivo,
            as_attachment=True,
            download_name=archivo.nombre_archivo
        )
    else:
        abort(404)


@main_bp.route('/archivos/ver/<int:archivo_id>')
@login_required
def ver_archivo(archivo_id):
    """Sirve un archivo PDF para visualizacion en el navegador."""
    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    if os.path.exists(archivo.ruta_archivo):
        return send_file(
            archivo.ruta_archivo,
            mimetype='application/pdf',
            as_attachment=False
        )
    else:
        abort(404)


@main_bp.route('/archivos/descargar-todos')
@login_required
def descargar_todos_archivos():
    """Descarga todos los archivos del usuario en un ZIP."""
    archivos = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    ).all()

    if not archivos:
        abort(404)

    # Crear ZIP en memoria
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, 'w', zipfile.ZIP_DEFLATED) as zf:
        for archivo in archivos:
            if os.path.exists(archivo.ruta_archivo):
                zf.write(archivo.ruta_archivo, archivo.nombre_archivo)

    memoria.seek(0)

    fecha = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        memoria,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'polizas_seguros_{fecha}.zip'
    )


@main_bp.route('/archivos/eliminar/<int:archivo_id>', methods=['POST'])
@login_required
def eliminar_archivo(archivo_id):
    """Elimina un archivo PDF."""
    from app import db
    from flask import flash

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Eliminar archivo físico
    if os.path.exists(archivo.ruta_archivo):
        os.remove(archivo.ruta_archivo)

    # Eliminar registro
    db.session.delete(archivo)
    db.session.commit()

    flash('Archivo eliminado correctamente.', 'success')
    return redirect(url_for('main.archivos'))
