"""
Rutas principales de la aplicación
"""

import logging
import os
import zipfile
import io
from flask import Blueprint, render_template, redirect, url_for, send_file, abort, current_app, request, jsonify, flash, make_response
from flask_login import login_required, current_user
from app.models import (Escaneo, ArchivoDescargado, CuentaGmail, Compania, Cliente,
                        PolizaCliente, LogEscaneo, HistorialEscaneoCarpeta)
from app import db
from datetime import datetime, timedelta
from sqlalchemy import func

logger = logging.getLogger('app.main.routes')

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

    # Forzar lectura fresca de la BD (importante después de escaneos)
    db.session.expire_all()

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

    # Verificar existencia física de cada archivo y agregar info de vigencia
    huerfanos_count = 0
    from datetime import date
    hoy = date.today()

    for archivo in archivos:
        ruta_fisica = archivo.obtener_ruta_fisica()
        archivo.archivo_existe = os.path.exists(ruta_fisica)
        if not archivo.archivo_existe:
            huerfanos_count += 1

        # Obtener póliza asociada y calcular vigencia
        poliza = PolizaCliente.query.filter_by(archivo_id=archivo.id).first()
        if poliza and poliza.fecha_vigencia_hasta:
            dias_restantes = (poliza.fecha_vigencia_hasta - hoy).days
            archivo.vigencia_dias = dias_restantes
            archivo.vigencia_vencida = dias_restantes < 0
            archivo.tiene_vigencia = True
        else:
            archivo.vigencia_dias = None
            archivo.vigencia_vencida = None
            archivo.tiene_vigencia = False

    # Calcular tamaño total (solo de archivos que existen)
    tamano_total = sum(a.tamano_bytes or 0 for a in archivos if a.archivo_existe)

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

    # Convertir a lista ordenada alfabéticamente por nombre de compañía
    grupos_companias = sorted(
        archivos_por_compania.values(),
        key=lambda x: x['compania'].nombre.lower()
    )

    # Contar archivos con correcciones pendientes
    correcciones_pendientes = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id,
        ArchivoDescargado.correccion_compania == True
    ).count()

    response = make_response(render_template('main/archivos.html',
                          archivos=archivos,
                          tamano_total=tamano_total,
                          companias=companias_con_archivos,
                          grupos_companias=grupos_companias,
                          archivos_sin_compania=archivos_sin_compania,
                          compania_seleccionada=compania_id,
                          vista=vista,
                          huerfanos_count=huerfanos_count,
                          correcciones_pendientes=correcciones_pendientes))
    # Headers anti-caché para que siempre muestre datos frescos
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@main_bp.route('/archivos/descargar/<int:archivo_id>')
@login_required
def descargar_archivo(archivo_id):
    """Descarga un archivo PDF individual."""
    from flask import flash

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Usar método que soporta repositorio y archivos legacy
    ruta_fisica = archivo.obtener_ruta_fisica()

    if os.path.exists(ruta_fisica):
        return send_file(
            ruta_fisica,
            as_attachment=True,
            download_name=archivo.nombre_archivo
        )
    else:
        flash(f'El archivo "{archivo.nombre_archivo}" ya no existe en disco. Use "Limpiar huérfanos" para eliminar registros sin archivo.', 'warning')
        return redirect(url_for('main.archivos'))


@main_bp.route('/archivos/ver/<int:archivo_id>')
@login_required
def ver_archivo(archivo_id):
    """Sirve un archivo PDF para visualizacion en el navegador."""
    from flask import flash

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Usar método que soporta repositorio y archivos legacy
    ruta_fisica = archivo.obtener_ruta_fisica()

    if os.path.exists(ruta_fisica):
        return send_file(
            ruta_fisica,
            mimetype='application/pdf',
            as_attachment=False
        )
    else:
        flash(f'El archivo "{archivo.nombre_archivo}" ya no existe en disco.', 'warning')
        return redirect(url_for('main.archivos'))


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
            ruta_fisica = archivo.obtener_ruta_fisica()
            if os.path.exists(ruta_fisica):
                zf.write(ruta_fisica, archivo.nombre_archivo)

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
    from app.models import RegistroAnalisisPDF, PolizaCliente
    from app.distribucion.backup_polizas import crear_backup_poliza

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Verificar si hay polizas asociadas y crear backup si es necesario
    ruta_fisica = archivo.obtener_ruta_fisica()
    polizas_asociadas = PolizaCliente.query.filter_by(archivo_id=archivo.id).all()
    backups_creados = 0
    for poliza in polizas_asociadas:
        if not poliza.ruta_pdf_backup:
            if crear_backup_poliza(poliza, ruta_fisica):
                backups_creados += 1

    # Manejar repositorio si aplica
    if archivo.archivo_repo:
        archivo.archivo_repo.decrementar_referencias()
        # Solo eliminar archivo físico si no hay más referencias
        if archivo.archivo_repo.cantidad_referencias <= 0:
            if os.path.exists(ruta_fisica):
                os.remove(ruta_fisica)
            db.session.delete(archivo.archivo_repo)
    else:
        # Archivo legacy - eliminar directamente
        if os.path.exists(ruta_fisica):
            os.remove(ruta_fisica)

    # Eliminar registros de análisis relacionados primero
    RegistroAnalisisPDF.query.filter_by(archivo_id=archivo.id).delete()

    # Eliminar registro
    db.session.delete(archivo)
    db.session.commit()

    if backups_creados > 0:
        flash(f'Archivo eliminado. Se crearon {backups_creados} backup(s) de polizas asociadas.', 'success')
    else:
        flash('Archivo eliminado correctamente.', 'success')
    return redirect(url_for('main.archivos'))


@main_bp.route('/archivos/eliminar-multiple', methods=['POST'])
@login_required
def eliminar_archivos_multiple():
    """Elimina múltiples archivos PDF seleccionados."""
    from app import db
    from flask import flash
    from app.models import RegistroAnalisisPDF, PolizaCliente
    from app.distribucion.backup_polizas import crear_backup_poliza

    archivo_ids = request.form.getlist('archivo_ids[]')

    if not archivo_ids:
        flash('No se seleccionaron archivos.', 'warning')
        return redirect(url_for('main.archivos'))

    eliminados = 0
    backups_creados = 0
    for archivo_id in archivo_ids:
        try:
            archivo = ArchivoDescargado.query.join(Escaneo).filter(
                ArchivoDescargado.id == int(archivo_id),
                Escaneo.usuario_id == current_user.id
            ).first()

            if archivo:
                ruta_fisica = archivo.obtener_ruta_fisica()
                # Verificar si hay polizas asociadas y crear backup
                polizas_asociadas = PolizaCliente.query.filter_by(archivo_id=archivo.id).all()
                for poliza in polizas_asociadas:
                    if not poliza.ruta_pdf_backup:
                        if crear_backup_poliza(poliza, ruta_fisica):
                            backups_creados += 1

                # Manejar repositorio si aplica
                if archivo.archivo_repo:
                    archivo.archivo_repo.decrementar_referencias()
                    if archivo.archivo_repo.cantidad_referencias <= 0:
                        if os.path.exists(ruta_fisica):
                            os.remove(ruta_fisica)
                        db.session.delete(archivo.archivo_repo)
                else:
                    if os.path.exists(ruta_fisica):
                        os.remove(ruta_fisica)
                # Eliminar registros de análisis relacionados primero
                RegistroAnalisisPDF.query.filter_by(archivo_id=archivo.id).delete()
                # Eliminar registro
                db.session.delete(archivo)
                eliminados += 1
        except Exception as e:
            logger.warning(f"Error eliminando archivo {archivo_id}: {e}")
            continue

    db.session.commit()
    msg = f'Se eliminaron {eliminados} archivo(s) correctamente.'
    if backups_creados > 0:
        msg += f' Se crearon {backups_creados} backup(s) de polizas.'
    flash(msg, 'success')
    return redirect(url_for('main.archivos'))


@main_bp.route('/archivos/limpiar-huerfanos', methods=['POST'])
@login_required
def limpiar_archivos_huerfanos():
    """Elimina registros de BD cuyos archivos físicos ya no existen."""
    from app import db
    from flask import flash
    from app.models import RegistroAnalisisPDF

    # Buscar archivos del usuario actual que no existen físicamente
    archivos = ArchivoDescargado.query.join(Escaneo).filter(
        Escaneo.usuario_id == current_user.id
    ).all()

    huerfanos = []
    for archivo in archivos:
        ruta_fisica = archivo.obtener_ruta_fisica()
        if not os.path.exists(ruta_fisica):
            huerfanos.append(archivo)

    if not huerfanos:
        flash('No se encontraron registros huérfanos.', 'info')
        return redirect(url_for('main.archivos'))

    # Eliminar registros relacionados y luego los archivos
    eliminados = 0
    for archivo in huerfanos:
        try:
            # Eliminar registros de análisis relacionados
            RegistroAnalisisPDF.query.filter_by(archivo_id=archivo.id).delete()
            db.session.delete(archivo)
            eliminados += 1
        except Exception as e:
            logger.warning(f"Error limpiando registro huérfano {archivo.id}: {e}")
            continue

    db.session.commit()
    flash(f'Se limpiaron {eliminados} registro(s) huérfano(s).', 'success')
    return redirect(url_for('main.archivos'))


# ============================================
# API PARA MODAL REFINAR
# ============================================

@main_bp.route('/api/archivo/<int:archivo_id>/datos')
@login_required
def api_datos_archivo(archivo_id):
    """Obtiene datos completos de un archivo para el modal Refinar."""
    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Buscar póliza/cliente asociado
    poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()

    return jsonify({
        'id': archivo.id,
        'nombre': archivo.nombre_archivo,
        'remitente': archivo.remitente,
        'compania': {
            'id': archivo.compania.id if archivo.compania else None,
            'nombre': archivo.compania.nombre if archivo.compania else 'Sin asignar',
            'dominio': archivo.compania.dominio_email if archivo.compania else None
        } if archivo.compania else None,
        'cliente': {
            'id': poliza.cliente.id,
            'nombre': f"{poliza.cliente.nombre or ''} {poliza.cliente.apellido or ''}".strip(),
            'telefono': poliza.cliente.telefono_whatsapp,
            'email': poliza.cliente.email
        } if poliza and poliza.cliente else None,
        'poliza_id': poliza.id if poliza else None
    })


@main_bp.route('/api/archivo/<int:archivo_id>/compania', methods=['POST'])
@login_required
def api_cambiar_compania_archivo(archivo_id):
    """Cambia la compañía asignada a un archivo y registra la corrección."""
    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    data = request.get_json()
    compania_id = data.get('compania_id')
    es_correccion = data.get('es_correccion', False)  # Flag para marcar como corrección manual

    if compania_id:
        compania = Compania.query.get(compania_id)
        if not compania:
            return jsonify({'success': False, 'message': 'Compañía no encontrada'}), 404

    # Si es una corrección, guardar la compañía original
    if es_correccion and archivo.compania_id != compania_id:
        if not archivo.correccion_compania:  # Solo guardar original la primera vez
            archivo.compania_id_original = archivo.compania_id
        archivo.correccion_compania = True
        archivo.fecha_correccion = datetime.utcnow()

    # Actualizar archivo
    archivo.compania_id = compania_id if compania_id else None
    archivo.nombre_compania_original = compania.nombre if compania_id else None

    # Actualizar póliza si existe
    poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()
    if poliza:
        poliza.compania_id = compania_id

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"Compañía actualizada a '{compania.nombre}'" if compania_id else "Compañía removida",
        'correccion_registrada': es_correccion
    })


@main_bp.route('/api/archivo/<int:archivo_id>/cliente', methods=['POST'])
@login_required
def api_asignar_cliente_archivo(archivo_id):
    """Asigna o cambia el cliente de un archivo."""
    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    data = request.get_json()
    cliente_id = data.get('cliente_id')
    accion = data.get('accion', 'asignar')  # 'asignar' o 'desvincular'

    if accion == 'desvincular':
        # Eliminar póliza existente
        poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()
        if poliza:
            db.session.delete(poliza)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Cliente desvinculado'})
        return jsonify({'success': False, 'message': 'No hay cliente asignado'})

    if not cliente_id:
        return jsonify({'success': False, 'message': 'ID de cliente requerido'}), 400

    cliente = Cliente.query.filter_by(id=cliente_id, activo=True).first()
    if not cliente:
        return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404

    # Buscar o crear póliza
    poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()
    if poliza:
        poliza.cliente_id = cliente_id
    else:
        poliza = PolizaCliente(
            cliente_id=cliente_id,
            archivo_id=archivo_id,
            compania_id=archivo.compania_id,
            fecha_creacion=datetime.utcnow()
        )
        db.session.add(poliza)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"Cliente asignado: {cliente.nombre} {cliente.apellido or ''}"
    })


@main_bp.route('/api/companias', methods=['GET', 'POST'])
@login_required
def api_companias():
    """GET: Lista compañías. POST: Crea nueva."""
    if request.method == 'GET':
        companias_bd = Compania.query.order_by(Compania.nombre).all()
        return jsonify([{
            'id': c.id,
            'nombre': c.nombre,
            'dominio': c.dominio_email
        } for c in companias_bd])

    # POST - Crear nueva
    data = request.get_json()
    nombre = data.get('nombre', '').strip()
    dominio = data.get('dominio', '').strip().lower()

    if not nombre:
        return jsonify({'success': False, 'message': 'Nombre requerido'}), 400

    existente = Compania.query.filter_by(dominio_email=dominio).first() if dominio else None
    if existente:
        return jsonify({'success': False, 'message': f"Dominio '{dominio}' ya existe"}), 400

    nueva = Compania(nombre=nombre, dominio_email=dominio or None)
    db.session.add(nueva)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"Compañía '{nombre}' creada",
        'compania': {
            'id': nueva.id,
            'nombre': nueva.nombre,
            'dominio': nueva.dominio_email
        }
    })


@main_bp.route('/api/clientes/buscar')
@login_required
def api_buscar_clientes():
    """Busca clientes por nombre, apellido o documento."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    clientes = Cliente.query.filter(
        Cliente.usuario_id == current_user.id
    ).filter(
        db.or_(
            Cliente.nombre.ilike(f'%{q}%'),
            Cliente.apellido.ilike(f'%{q}%'),
            Cliente.dni_cuit.ilike(f'%{q}%'),
            Cliente.email.ilike(f'%{q}%')
        )
    ).limit(20).all()

    return jsonify([{
        'id': c.id,
        'nombre': c.nombre,
        'apellido': c.apellido,
        'dni_cuit': c.dni_cuit,
        'email': c.email,
        'telefono': c.telefono_whatsapp,
        'display': f"{c.nombre or ''} {c.apellido or ''} ({c.dni_cuit or 'Sin DNI'})"
    } for c in clientes])


@main_bp.route('/api/clientes', methods=['POST'])
@login_required
def api_crear_cliente():
    """Crea un nuevo cliente (unifica si existe con mismo documento)."""
    data = request.get_json()

    nombre = data.get('nombre', '').strip()
    apellido = data.get('apellido', '').strip()
    documento = data.get('dni_cuit', '').strip() or data.get('documento_identidad', '').strip() or None
    email = data.get('email', '').strip() or None
    telefono = data.get('telefono', '').strip() or None

    if not nombre:
        return jsonify({'success': False, 'message': 'Nombre requerido'}), 400

    # Usar método que unifica por documento
    cliente, es_nuevo, mensaje = Cliente.obtener_o_crear(
        usuario_id=current_user.id,
        nombre=nombre,
        apellido=apellido,
        documento_identidad=documento,
        email=email,
        telefono_whatsapp=telefono,
        actualizar_existente=True
    )
    db.session.commit()

    return jsonify({
        'success': True,
        'es_nuevo': es_nuevo,
        'message': mensaje if not es_nuevo else f"Cliente '{nombre} {apellido}' creado",
        'cliente': {
            'id': cliente.id,
            'nombre': cliente.nombre,
            'apellido': cliente.apellido,
            'display': cliente.nombre_completo
        }
    })


