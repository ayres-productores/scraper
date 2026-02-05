"""
Rutas principales de la aplicación
"""

from flask import Blueprint, render_template, redirect, url_for, send_file, abort, current_app, request, jsonify, flash
from flask_login import login_required, current_user
from app.models import Escaneo, ArchivoDescargado, CuentaGmail, Compania, Cliente, PolizaCliente
from app import db
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

    # Verificar existencia física de cada archivo y contar huérfanos
    huerfanos_count = 0
    for archivo in archivos:
        archivo.archivo_existe = os.path.exists(archivo.ruta_archivo)
        if not archivo.archivo_existe:
            huerfanos_count += 1

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

    return render_template('main/archivos.html',
                          archivos=archivos,
                          tamano_total=tamano_total,
                          companias=companias_con_archivos,
                          grupos_companias=grupos_companias,
                          archivos_sin_compania=archivos_sin_compania,
                          compania_seleccionada=compania_id,
                          vista=vista,
                          huerfanos_count=huerfanos_count)


@main_bp.route('/archivos/descargar/<int:archivo_id>')
@login_required
def descargar_archivo(archivo_id):
    """Descarga un archivo PDF individual."""
    from flask import flash

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

    if os.path.exists(archivo.ruta_archivo):
        return send_file(
            archivo.ruta_archivo,
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
    from app.models import RegistroAnalisisPDF, PolizaCliente
    from app.distribucion.backup_polizas import crear_backup_poliza

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Verificar si hay polizas asociadas y crear backup si es necesario
    polizas_asociadas = PolizaCliente.query.filter_by(archivo_id=archivo.id).all()
    backups_creados = 0
    for poliza in polizas_asociadas:
        if not poliza.ruta_pdf_backup:
            if crear_backup_poliza(poliza, archivo.ruta_archivo):
                backups_creados += 1

    # Eliminar archivo físico
    if os.path.exists(archivo.ruta_archivo):
        os.remove(archivo.ruta_archivo)

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
                # Verificar si hay polizas asociadas y crear backup
                polizas_asociadas = PolizaCliente.query.filter_by(archivo_id=archivo.id).all()
                for poliza in polizas_asociadas:
                    if not poliza.ruta_pdf_backup:
                        if crear_backup_poliza(poliza, archivo.ruta_archivo):
                            backups_creados += 1

                # Eliminar archivo físico
                if os.path.exists(archivo.ruta_archivo):
                    os.remove(archivo.ruta_archivo)
                # Eliminar registros de análisis relacionados primero
                RegistroAnalisisPDF.query.filter_by(archivo_id=archivo.id).delete()
                # Eliminar registro
                db.session.delete(archivo)
                eliminados += 1
        except (ValueError, Exception):
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
        if not os.path.exists(archivo.ruta_archivo):
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
    """Cambia la compañía asignada a un archivo."""
    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    data = request.get_json()
    compania_id = data.get('compania_id')

    if compania_id:
        compania = Compania.query.get(compania_id)
        if not compania:
            return jsonify({'success': False, 'message': 'Compañía no encontrada'}), 404

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
        'message': f"Compañía actualizada a '{compania.nombre}'" if compania_id else "Compañía removida"
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

    cliente = Cliente.query.filter_by(id=cliente_id, usuario_id=current_user.id).first()
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


@main_bp.route('/api/reglas/palabras-globales', methods=['GET', 'POST'])
@login_required
def api_palabras_globales():
    """GET: Obtiene palabras clave globales. POST: Actualiza."""
    from app.extractor.gestor_reglas import cargar_palabras_globales, guardar_palabras_globales

    if request.method == 'GET':
        palabras = cargar_palabras_globales()
        return jsonify(palabras)

    # POST - Actualizar
    data = request.get_json()
    exito, mensaje = guardar_palabras_globales(
        data.get('palabras_poliza', []),
        data.get('palabras_excluir', []),
        data.get('servicios_excluidos', [])
    )

    return jsonify({'success': exito, 'message': mensaje})


@main_bp.route('/api/reglas/compania/<compania_id>', methods=['GET', 'POST'])
@login_required
def api_reglas_compania(compania_id):
    """GET: Obtiene reglas de una compañía. POST: Actualiza."""
    from app.extractor.gestor_reglas import cargar_reglas_compania, guardar_reglas_compania

    if request.method == 'GET':
        reglas = cargar_reglas_compania(compania_id)
        if not reglas:
            return jsonify({'error': 'Compañía no encontrada'}), 404
        return jsonify(reglas)

    # POST - Actualizar
    data = request.get_json()
    exito, mensaje = guardar_reglas_compania(compania_id, data)

    return jsonify({'success': exito, 'message': mensaje})


@main_bp.route('/api/companias', methods=['GET', 'POST'])
@login_required
def api_companias():
    """GET: Lista compañías. POST: Crea nueva."""
    from app.extractor.gestor_reglas import cargar_lista_companias, agregar_compania_json

    if request.method == 'GET':
        # Obtener de BD
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

    # Crear en BD
    existente = Compania.query.filter_by(dominio_email=dominio).first() if dominio else None
    if existente:
        return jsonify({'success': False, 'message': f"Dominio '{dominio}' ya existe"}), 400

    nueva = Compania(nombre=nombre, dominio_email=dominio or None)
    db.session.add(nueva)
    db.session.commit()

    # También agregar al JSON de configuración
    if dominio:
        compania_id = nombre.lower().replace(' ', '_').replace('.', '')
        agregar_compania_json(compania_id, nombre, [dominio])

    return jsonify({
        'success': True,
        'message': f"Compañía '{nombre}' creada",
        'compania': {
            'id': nueva.id,
            'nombre': nueva.nombre,
            'dominio': nueva.dominio_email
        }
    })


@main_bp.route('/api/companias-config')
@login_required
def api_companias_config():
    """Lista compañías del archivo de configuración JSON."""
    from app.extractor.gestor_reglas import cargar_lista_companias
    return jsonify(cargar_lista_companias())


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
    """Crea un nuevo cliente."""
    data = request.get_json()

    nombre = data.get('nombre', '').strip()
    apellido = data.get('apellido', '').strip()

    if not nombre:
        return jsonify({'success': False, 'message': 'Nombre requerido'}), 400

    nuevo = Cliente(
        usuario_id=current_user.id,
        nombre=nombre,
        apellido=apellido,
        dni_cuit=data.get('dni_cuit', '').strip() or None,
        email=data.get('email', '').strip() or None,
        telefono_whatsapp=data.get('telefono', '').strip() or None
    )
    db.session.add(nuevo)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"Cliente '{nombre} {apellido}' creado",
        'cliente': {
            'id': nuevo.id,
            'nombre': nuevo.nombre,
            'apellido': nuevo.apellido,
            'display': f"{nuevo.nombre or ''} {nuevo.apellido or ''}"
        }
    })


# ============================================
# API PARA DATOS PDF Y APRENDIZAJE
# ============================================

@main_bp.route('/api/archivo/<int:archivo_id>/datos-pdf')
@login_required
def api_datos_pdf(archivo_id):
    """Obtiene datos extraídos del PDF para visualización y corrección."""
    from app.extractor.pdf_parser import extraer_datos_poliza

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Obtener póliza asociada (datos ya guardados)
    poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()

    # Extraer datos frescos del PDF si el archivo existe
    datos_extraidos = {}
    confianza_extraccion = 0
    if os.path.exists(archivo.ruta_archivo):
        try:
            datos_extraidos = extraer_datos_poliza(archivo.ruta_archivo) or {}
            confianza_extraccion = datos_extraidos.get('confianza_extraccion', 0.5)
        except Exception as e:
            print(f"Error extrayendo datos del PDF: {e}")

    # Definir campos a mostrar organizados por categoría
    campos_config = {
        'asegurado': [
            ('asegurado_nombre', 'Nombre', 'text'),
            ('asegurado_documento', 'DNI/CUIT', 'text'),
            ('asegurado_direccion', 'Dirección', 'text'),
            ('asegurado_telefono', 'Teléfono', 'text'),
            ('asegurado_email', 'Email', 'email'),
        ],
        'poliza': [
            ('numero_poliza', 'Número Póliza', 'text'),
            ('tipo_seguro', 'Tipo Seguro', 'select'),
            ('fecha_vigencia_desde', 'Vigencia Desde', 'date'),
            ('fecha_vigencia_hasta', 'Vigencia Hasta', 'date'),
            ('prima_anual', 'Prima Total', 'currency'),
        ],
        'vehiculo': [
            ('vehiculo_patente', 'Patente', 'text'),
            ('vehiculo_marca', 'Marca', 'text'),
            ('vehiculo_modelo', 'Modelo', 'text'),
            ('vehiculo_anio', 'Año', 'number'),
            ('vehiculo_chasis', 'Chasis', 'text'),
            ('vehiculo_motor', 'Motor', 'text'),
            ('vehiculo_color', 'Color', 'text'),
        ],
        'inmueble': [
            ('inmueble_direccion', 'Dirección Inmueble', 'text'),
            ('inmueble_tipo', 'Tipo Inmueble', 'text'),
            ('inmueble_superficie', 'Superficie (m²)', 'number'),
        ],
        'coberturas': [
            ('suma_asegurada', 'Suma Asegurada', 'currency'),
            ('deducible', 'Deducible', 'text'),
        ]
    }

    # Construir datos combinando: 1) póliza guardada, 2) extracción fresca del PDF
    datos = {}
    confianza_total = 0
    campos_con_valor = 0

    for categoria, campos in campos_config.items():
        datos[categoria] = []
        for campo_id, label, tipo in campos:
            valor = None
            valor_original = None
            estado = 'vacio'

            # Prioridad 1: Valor guardado en póliza (si existe)
            if poliza:
                valor_guardado = getattr(poliza, campo_id, None)
                if valor_guardado is not None and str(valor_guardado).strip():
                    valor = valor_guardado
                    estado = 'extraido'

            # Prioridad 2: Valor extraído del PDF (si no hay guardado)
            if valor is None and campo_id in datos_extraidos:
                valor_pdf = datos_extraidos.get(campo_id)
                if valor_pdf is not None and str(valor_pdf).strip():
                    valor = valor_pdf
                    valor_original = valor_pdf  # Marcar como recién extraído
                    estado = 'extraido'

            if valor is not None:
                campos_con_valor += 1
                confianza_total += confianza_extraccion if confianza_extraccion else 0.5

            # Formatear valores para visualización
            valor_display = valor
            if valor and tipo == 'date' and hasattr(valor, 'strftime'):
                valor_display = valor.strftime('%d/%m/%Y')
            elif valor and tipo == 'currency':
                try:
                    valor_display = f"${float(valor):,.2f}"
                except (ValueError, TypeError):
                    valor_display = str(valor)

            datos[categoria].append({
                'id': campo_id,
                'label': label,
                'tipo': tipo,
                'valor': str(valor) if valor else '',
                'valor_display': valor_display if valor_display else '',
                'valor_original': valor_original,
                'estado': estado
            })

    # Calcular confianza promedio
    confianza = (confianza_total / max(campos_con_valor, 1)) if campos_con_valor > 0 else 0

    return jsonify({
        'success': True,
        'archivo_id': archivo_id,
        'archivo_nombre': archivo.nombre_archivo,
        'tiene_poliza': poliza is not None,
        'poliza_id': poliza.id if poliza else None,
        'datos': datos,
        'confianza': round(confianza * 100),
        'campos_con_valor': campos_con_valor
    })


@main_bp.route('/api/archivo/<int:archivo_id>/corregir-campo', methods=['POST'])
@login_required
def api_corregir_campo(archivo_id):
    """Guarda la corrección de un campo y registra para aprendizaje."""
    from app.extractor.aprendizaje import registrar_correccion

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    data = request.get_json()
    campo = data.get('campo')
    valor_nuevo = data.get('valor_nuevo', '').strip()
    valor_original = data.get('valor_original', '').strip()

    if not campo:
        return jsonify({'success': False, 'message': 'Campo requerido'}), 400

    # Obtener o crear póliza
    poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()
    if not poliza:
        poliza = PolizaCliente(
            archivo_id=archivo_id,
            compania_id=archivo.compania_id,
            fecha_creacion=datetime.utcnow()
        )
        db.session.add(poliza)

    # Verificar que el campo existe en el modelo
    if not hasattr(poliza, campo):
        return jsonify({'success': False, 'message': f'Campo "{campo}" no válido'}), 400

    # Convertir valor según tipo de campo
    valor_convertido = valor_nuevo
    if valor_nuevo:
        # Campos de fecha
        if campo in ['fecha_emision', 'fecha_vigencia_desde', 'fecha_vigencia_hasta']:
            try:
                for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
                    try:
                        valor_convertido = datetime.strptime(valor_nuevo, fmt).date()
                        break
                    except ValueError:
                        continue
            except Exception:
                pass
        # Campos numéricos
        elif campo in ['vehiculo_anio', 'inmueble_superficie']:
            try:
                valor_convertido = int(valor_nuevo)
            except ValueError:
                pass
        # Campos de moneda
        elif campo in ['prima_total', 'suma_asegurada']:
            try:
                # Limpiar formato de moneda
                limpio = valor_nuevo.replace('$', '').replace('.', '').replace(',', '.')
                valor_convertido = float(limpio)
            except ValueError:
                pass

    # Actualizar campo en póliza
    setattr(poliza, campo, valor_convertido if valor_nuevo else None)
    db.session.commit()

    # Registrar corrección para aprendizaje (solo si hay valor original diferente)
    mensaje_aprendizaje = ""
    if valor_original and valor_original != valor_nuevo:
        compania_id = archivo.compania.dominio_email if archivo.compania else None
        exito, msg = registrar_correccion(campo, valor_original, valor_nuevo, compania=compania_id)
        if exito:
            mensaje_aprendizaje = f" ({msg})"

    return jsonify({
        'success': True,
        'message': f'Campo actualizado{mensaje_aprendizaje}',
        'campo': campo,
        'valor': valor_nuevo
    })


@main_bp.route('/api/archivo/<int:archivo_id>/confirmar-datos', methods=['POST'])
@login_required
def api_confirmar_datos(archivo_id):
    """Confirma que todos los datos extraídos son correctos."""
    from app.extractor.aprendizaje import obtener_motor

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()
    if not poliza:
        return jsonify({'success': False, 'message': 'No hay datos para confirmar'}), 400

    data = request.get_json() or {}
    campos = data.get('campos', [])

    # Registrar confirmaciones
    motor = obtener_motor()
    confirmados = 0
    for campo in campos:
        valor = getattr(poliza, campo, None)
        if valor:
            motor.confirmar_datos(campo, str(valor))
            confirmados += 1

    # Marcar póliza como revisada (podríamos agregar un campo para esto)
    # Por ahora solo respondemos con éxito

    return jsonify({
        'success': True,
        'message': f'{confirmados} campos confirmados como correctos',
        'confirmados': confirmados
    })


@main_bp.route('/api/archivo/<int:archivo_id>/reextraer', methods=['POST'])
@login_required
def api_reextraer_pdf(archivo_id):
    """Re-extrae datos del PDF usando diferentes algoritmos.

    Soporta rotación de algoritmos:
    - modo=auto: Detecta compañía automáticamente
    - modo=generico: Solo patrones genéricos
    - modo=liderar, berkley, etc: Fuerza extractor específico
    - modo=siguiente: Rota al siguiente algoritmo disponible
    """
    from app.extractor.pdf_parser import ExtractorDatosPoliza
    from flask import session

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    if not os.path.exists(archivo.ruta_archivo):
        return jsonify({'success': False, 'message': 'Archivo PDF no encontrado'}), 404

    # Modos de extracción disponibles
    modos_disponibles = ['auto', 'liderar', 'berkley', 'mercantil_andina', 'rio_uruguay', 'generico']

    # Obtener modo solicitado o usar rotación
    data = request.get_json() or {}
    modo_solicitado = data.get('modo', 'siguiente')

    # Manejar rotación de modos
    session_key = f'modo_extraccion_{archivo_id}'
    if modo_solicitado == 'siguiente':
        modo_actual_idx = session.get(session_key, -1)
        modo_idx = (modo_actual_idx + 1) % len(modos_disponibles)
        modo = modos_disponibles[modo_idx]
        session[session_key] = modo_idx
    else:
        modo = modo_solicitado
        session[session_key] = modos_disponibles.index(modo) if modo in modos_disponibles else 0

    try:
        extractor = ExtractorDatosPoliza()
        texto = extractor.extraer_texto_pdf(archivo.ruta_archivo)

        if not texto:
            return jsonify({'success': False, 'message': 'No se pudo leer el PDF'}), 400

        # Aplicar extracción según el modo
        if modo == 'auto':
            compania = extractor.detectar_compania(texto)
            datos = extractor.extraer_datos(archivo.ruta_archivo)
            modo_usado = f"auto ({compania or 'genérico'})"
        elif modo == 'generico':
            # Solo usar patrones genéricos sin detección de compañía
            datos = extractor.extraer_datos(archivo.ruta_archivo)
            # Limpiar datos específicos de compañía
            datos['compania_detectada'] = None
            modo_usado = "genérico"
        elif modo in ['liderar', 'berkley', 'mercantil_andina', 'rio_uruguay']:
            # Forzar extractor específico
            metodo = f'_extraer_datos_{modo}'
            if hasattr(extractor, metodo):
                datos_especificos = getattr(extractor, metodo)(texto)
                # Combinar con datos base
                datos = extractor.extraer_datos(archivo.ruta_archivo)
                for campo, valor in datos_especificos.items():
                    if valor:
                        datos[campo] = valor
                datos['compania_detectada'] = modo
                modo_usado = modo.replace('_', ' ').title()
            else:
                datos = extractor.extraer_datos(archivo.ruta_archivo)
                modo_usado = f"{modo} (no disponible, usando auto)"
        else:
            datos = extractor.extraer_datos(archivo.ruta_archivo)
            modo_usado = "auto"

        if not datos:
            return jsonify({'success': False, 'message': 'No se pudieron extraer datos'}), 400

        # Actualizar o crear póliza
        poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()
        if not poliza:
            poliza = PolizaCliente(
                archivo_id=archivo_id,
                compania_id=archivo.compania_id,
                fecha_creacion=datetime.utcnow()
            )
            db.session.add(poliza)

        # Mapear datos extraídos a campos de póliza
        campos_actualizados = 0
        for campo, valor in datos.items():
            if hasattr(poliza, campo) and valor is not None:
                setattr(poliza, campo, valor)
                campos_actualizados += 1

        db.session.commit()

        # Calcular siguiente modo para mostrar al usuario
        modo_idx_actual = modos_disponibles.index(modo) if modo in modos_disponibles else 0
        siguiente_modo = modos_disponibles[(modo_idx_actual + 1) % len(modos_disponibles)]

        return jsonify({
            'success': True,
            'message': f'Modo: {modo_usado} | {campos_actualizados} campos',
            'modo_usado': modo_usado,
            'siguiente_modo': siguiente_modo,
            'campos_actualizados': campos_actualizados,
            'datos': datos
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


@main_bp.route('/api/archivo/<int:archivo_id>/renombrar', methods=['POST'])
@login_required
def api_renombrar_archivo(archivo_id):
    """Aplica datos extraídos: crea/actualiza cliente, póliza y renombra archivo.

    1. Extrae datos frescos del PDF con los patrones mejorados
    2. Crea o actualiza el CLIENTE con datos del asegurado
    3. Crea o actualiza la PÓLIZA con datos extraídos y vehículo
    4. Vincula la póliza con el cliente
    5. Renombra el archivo en formato: ASEGURADO/BIEN_FECHA.pdf
    """
    from app.extractor.pdf_parser import extraer_datos_poliza

    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    if not os.path.exists(archivo.ruta_archivo):
        return jsonify({'success': False, 'message': 'Archivo PDF no encontrado'}), 404

    try:
        # Extraer datos del PDF con patrones mejorados
        datos = extraer_datos_poliza(archivo.ruta_archivo)

        if not datos:
            return jsonify({'success': False, 'message': 'No se pudieron extraer datos del PDF'}), 400

        asegurado_nombre = datos.get('asegurado_nombre', '').strip()
        if not asegurado_nombre:
            return jsonify({'success': False, 'message': 'No se encontró nombre del asegurado'}), 400

        # ============================================================
        # 1. CREAR O ACTUALIZAR CLIENTE
        # ============================================================
        cliente = None
        cliente_creado = False
        documento = datos.get('asegurado_documento', '').replace('-', '').replace(' ', '')

        # Buscar cliente existente por documento
        if documento:
            cliente = Cliente.query.filter(
                Cliente.usuario_id == current_user.id,
                Cliente.documento_identidad == documento
            ).first()

        # Si no se encontró por documento, buscar por nombre similar
        if not cliente and asegurado_nombre:
            # Separar nombre y apellido
            partes_nombre = asegurado_nombre.split(',')
            if len(partes_nombre) >= 2:
                apellido = partes_nombre[0].strip()
                nombre = partes_nombre[1].strip()
            else:
                partes_nombre = asegurado_nombre.split()
                apellido = partes_nombre[0] if partes_nombre else ''
                nombre = ' '.join(partes_nombre[1:]) if len(partes_nombre) > 1 else ''

            cliente = Cliente.query.filter(
                Cliente.usuario_id == current_user.id,
                Cliente.apellido.ilike(f'%{apellido}%'),
                Cliente.nombre.ilike(f'%{nombre[:10]}%') if nombre else True
            ).first()

        # Si no existe, crear nuevo cliente
        if not cliente:
            partes_nombre = asegurado_nombre.split(',')
            if len(partes_nombre) >= 2:
                apellido = partes_nombre[0].strip()
                nombre = partes_nombre[1].strip()
            else:
                partes_nombre = asegurado_nombre.split()
                apellido = partes_nombre[0] if partes_nombre else asegurado_nombre
                nombre = ' '.join(partes_nombre[1:]) if len(partes_nombre) > 1 else ''

            telefono = datos.get('asegurado_telefono', '').strip()
            # Si no hay teléfono, usar un placeholder
            if not telefono:
                telefono = '0000000000'

            cliente = Cliente(
                usuario_id=current_user.id,
                nombre=nombre[:100] if nombre else apellido[:100],
                apellido=apellido[:100] if nombre else None,
                telefono_whatsapp=telefono[:20],
                email=datos.get('asegurado_email', '')[:120] if datos.get('asegurado_email') else None,
                documento_identidad=documento[:30] if documento else None,
                notas=f"Dirección: {datos.get('asegurado_direccion', '')}"[:500] if datos.get('asegurado_direccion') else None,
                fecha_registro=datetime.utcnow()
            )
            db.session.add(cliente)
            db.session.flush()  # Para obtener el ID
            cliente_creado = True
        else:
            # Actualizar datos del cliente existente si están vacíos
            if not cliente.documento_identidad and documento:
                cliente.documento_identidad = documento[:30]
            if not cliente.email and datos.get('asegurado_email'):
                cliente.email = datos['asegurado_email'][:120]

        # ============================================================
        # 2. CREAR O ACTUALIZAR PÓLIZA
        # ============================================================
        poliza = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()
        if not poliza:
            poliza = PolizaCliente(
                cliente_id=cliente.id,
                archivo_id=archivo_id,
                compania_id=archivo.compania_id,
                fecha_creacion=datetime.utcnow()
            )
            db.session.add(poliza)
        else:
            # Vincular con el cliente si no lo estaba
            poliza.cliente_id = cliente.id

        # Mapear datos extraídos a campos de póliza
        campos_actualizados = 0
        campos_poliza = [
            'numero_poliza', 'tipo_seguro', 'prima_anual', 'suma_asegurada', 'deducible',
            'asegurado_nombre', 'asegurado_documento', 'asegurado_direccion',
            'asegurado_telefono', 'asegurado_email',
            'vehiculo_marca', 'vehiculo_modelo', 'vehiculo_anio', 'vehiculo_patente',
            'vehiculo_chasis', 'vehiculo_motor', 'vehiculo_color', 'vehiculo_uso',
            'productor_nombre', 'coberturas', 'bien_asegurado_tipo',
            'fecha_vigencia_desde', 'fecha_vigencia_hasta'
        ]

        for campo in campos_poliza:
            valor = datos.get(campo)
            if valor is not None and hasattr(poliza, campo):
                setattr(poliza, campo, valor)
                campos_actualizados += 1

        # Marcar como confirmado
        poliza.estado_confirmacion = 'definitivo'
        poliza.fecha_confirmacion = datetime.utcnow()
        poliza.confirmado_por = 'manual'

        # ============================================================
        # 3. GENERAR NUEVO NOMBRE DE ARCHIVO
        # ============================================================
        asegurado_limpio = asegurado_nombre[:40]

        # Obtener bien asegurado (patente, tipo de seguro, o número de póliza)
        bien = ''
        if datos.get('vehiculo_patente'):
            bien = datos['vehiculo_patente'].replace(' ', '').replace('-', '')[:10]
        elif datos.get('tipo_seguro'):
            bien = datos['tipo_seguro'][:15]
        elif datos.get('numero_poliza'):
            bien = datos['numero_poliza'].replace(' ', '')[:15]

        # Obtener fecha del archivo
        fecha = archivo.fecha_correo or archivo.fecha_descarga or datetime.utcnow()
        fecha_str = fecha.strftime('%Y%m%d')

        # Detectar si es Liderar para usar formato especial
        es_liderar = False
        if archivo.compania:
            es_liderar = 'liderar' in archivo.compania.nombre.lower()
        elif datos.get('compania_detectada'):
            es_liderar = 'liderar' in datos['compania_detectada'].lower()

        # Generar nuevo nombre
        if es_liderar and asegurado_limpio and bien:
            nuevo_nombre = f"{asegurado_limpio}/{bien}_{fecha_str}.pdf"
        elif asegurado_limpio and bien:
            nuevo_nombre = f"{asegurado_limpio}_{bien}_{fecha_str}.pdf"
        elif asegurado_limpio:
            nuevo_nombre = f"{asegurado_limpio}_{fecha_str}.pdf"
        else:
            return jsonify({'success': False, 'message': 'Datos insuficientes para renombrar'}), 400

        nombre_anterior = archivo.nombre_archivo
        archivo.nombre_archivo = nuevo_nombre

        # ============================================================
        # 4. GUARDAR TODO
        # ============================================================
        db.session.commit()

        # Preparar datos del cliente para el frontend
        cliente_data = {
            'id': cliente.id,
            'nombre': cliente.nombre_completo,
            'documento': cliente.documento_identidad,
            'telefono': cliente.telefono_whatsapp,
            'email': cliente.email,
            'creado': cliente_creado
        }

        # Preparar datos del vehículo si existen
        vehiculo_data = None
        if datos.get('vehiculo_patente'):
            vehiculo_data = {
                'patente': datos.get('vehiculo_patente'),
                'marca': datos.get('vehiculo_marca'),
                'modelo': datos.get('vehiculo_modelo'),
                'anio': datos.get('vehiculo_anio'),
                'chasis': datos.get('vehiculo_chasis'),
                'motor': datos.get('vehiculo_motor')
            }

        # Preparar datos de la póliza
        poliza_data = {
            'id': poliza.id,
            'numero': poliza.numero_poliza,
            'tipo': poliza.tipo_seguro,
            'vigencia_desde': str(poliza.fecha_vigencia_desde) if poliza.fecha_vigencia_desde else None,
            'vigencia_hasta': str(poliza.fecha_vigencia_hasta) if poliza.fecha_vigencia_hasta else None,
            'prima': float(poliza.prima_anual) if poliza.prima_anual else None,
            'estado': poliza.estado_confirmacion
        }

        return jsonify({
            'success': True,
            'nombre_anterior': nombre_anterior,
            'nombre_nuevo': nuevo_nombre,
            'asegurado': asegurado_limpio,
            'bien': bien,
            'cliente': cliente_data,
            'vehiculo': vehiculo_data,
            'poliza': poliza_data,
            'campos_actualizados': campos_actualizados,
            'datos': datos,
            'message': f'{"Cliente creado" if cliente_creado else "Cliente actualizado"} + {campos_actualizados} campos guardados'
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


@main_bp.route('/api/aprendizaje/estadisticas')
@login_required
def api_estadisticas_aprendizaje():
    """Obtiene estadísticas del motor de aprendizaje."""
    from app.extractor.aprendizaje import obtener_motor

    motor = obtener_motor()
    stats = motor.obtener_estadisticas()

    return jsonify({
        'success': True,
        'estadisticas': stats
    })


# ============================================
# API PARA CREAR CLIENTE + POLIZA DESDE MODAL
# ============================================

@main_bp.route('/archivos/crear-desde-pdf/<int:archivo_id>', methods=['POST'])
@login_required
def crear_desde_pdf(archivo_id):
    """
    Crea un cliente y una póliza a partir de un PDF y los datos del formulario.

    Recibe:
    - nombre, apellido, telefono, email, documento (del formulario)
    - archivo_id (de la URL)

    Acciones:
    1. Crea un nuevo Cliente con los datos del formulario
    2. Extrae datos del PDF
    3. Crea una PolizaCliente vinculada al cliente y al archivo
    4. Retorna JSON con resultado
    """
    from app.extractor.pdf_parser import ExtractorDatosPoliza

    # Verificar que el archivo pertenece al usuario
    archivo = ArchivoDescargado.query.join(Escaneo).filter(
        ArchivoDescargado.id == archivo_id,
        Escaneo.usuario_id == current_user.id
    ).first_or_404()

    # Obtener datos del formulario
    nombre = request.form.get('nombre', '').strip()
    apellido = request.form.get('apellido', '').strip()
    telefono = request.form.get('telefono', '').strip()
    email = request.form.get('email', '').strip()
    documento = request.form.get('documento', '').strip()

    # Validaciones
    if not nombre:
        return jsonify({'exito': False, 'error': 'El nombre es requerido'}), 400
    if not telefono:
        return jsonify({'exito': False, 'error': 'El teléfono es requerido'}), 400

    try:
        # 1. Crear cliente
        cliente = Cliente(
            usuario_id=current_user.id,
            nombre=nombre[:100],
            apellido=apellido[:100] if apellido else None,
            telefono_whatsapp=telefono[:20],
            email=email[:120] if email else None,
            documento_identidad=documento[:30] if documento else None,
            fecha_registro=datetime.utcnow()
        )
        db.session.add(cliente)
        db.session.flush()  # Para obtener el ID

        # 2. Extraer datos del PDF
        datos_poliza = {}
        confianza = 0.5

        if os.path.exists(archivo.ruta_archivo):
            try:
                extractor = ExtractorDatosPoliza()
                datos_extraidos = extractor.extraer_datos(archivo.ruta_archivo)
                if datos_extraidos:
                    datos_poliza = extractor.datos_para_poliza(datos_extraidos)
                    confianza = datos_extraidos.get('confianza', 0.5)
            except Exception as e:
                print(f"Error extrayendo datos del PDF: {e}")

        # 3. Crear póliza
        poliza = PolizaCliente(
            cliente_id=cliente.id,
            archivo_id=archivo.id,
            compania_id=archivo.compania_id,
            numero_poliza=datos_poliza.get('numero_poliza'),
            tipo_seguro=datos_poliza.get('tipo_seguro'),
            fecha_vigencia_desde=datos_poliza.get('fecha_vigencia_desde'),
            fecha_vigencia_hasta=datos_poliza.get('fecha_vigencia_hasta'),
            prima_anual=datos_poliza.get('prima_anual'),
            suma_asegurada=datos_poliza.get('suma_asegurada'),
            deducible=datos_poliza.get('deducible'),
            asegurado_nombre=f"{nombre} {apellido}".strip(),
            asegurado_documento=documento,
            asegurado_email=email,
            vehiculo_marca=datos_poliza.get('vehiculo_marca'),
            vehiculo_modelo=datos_poliza.get('vehiculo_modelo'),
            vehiculo_anio=datos_poliza.get('vehiculo_anio'),
            vehiculo_patente=datos_poliza.get('vehiculo_patente'),
            vehiculo_chasis=datos_poliza.get('vehiculo_chasis'),
            vehiculo_motor=datos_poliza.get('vehiculo_motor'),
            inmueble_direccion=datos_poliza.get('inmueble_direccion'),
            inmueble_tipo=datos_poliza.get('inmueble_tipo'),
            confianza_extraccion=confianza,
            fecha_extraccion=datetime.utcnow(),
            estado_confirmacion='definitivo',
            fecha_confirmacion=datetime.utcnow(),
            confirmado_por='modal_archivos'
        )
        db.session.add(poliza)

        # 4. Marcar archivo como procesado
        archivo.estado_confirmacion = 'definitivo'
        archivo.fecha_confirmacion = datetime.utcnow()
        archivo.confirmado_por = 'modal_archivos'

        db.session.commit()

        return jsonify({
            'exito': True,
            'cliente_id': cliente.id,
            'poliza_id': poliza.id,
            'mensaje': f'Cliente "{nombre} {apellido}" y póliza creados exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'exito': False, 'error': str(e)}), 500
