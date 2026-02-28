"""
Rutas del módulo API
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

api_bp = Blueprint('api', __name__)

# Importar rutas de webhook
from app.api import whatsapp_webhook


@api_bp.route('/extractor/reset-total', methods=['POST'])
@login_required
def reset_total():
    """
    Borra TODOS los datos del extractor (desarrollo).
    Requiere confirmación explícita.
    """
    from app.models import (
        db, ArchivoDescargado, Escaneo, PolizaCliente, Cliente,
        EnvioWhatsApp, Pago, Interaccion, AlertaVencimiento,
        CorreoProcesado, RangoCobertura, LogEscaneo, Siniestro
    )
    import shutil
    from pathlib import Path
    from flask import current_app

    # Solo admin puede hacer reset total
    if not current_user.es_admin():
        return jsonify({
            "success": False,
            "error": "Solo administradores pueden ejecutar reset total"
        }), 403

    data = request.get_json() or {}
    confirmacion = data.get('confirmar')

    if confirmacion != 'BORRAR_TODO':
        return jsonify({
            "success": False,
            "error": "Confirmación requerida"
        }), 400

    try:
        resultados = {}

        # Orden de eliminación (respetando foreign keys)
        # 1. Tablas dependientes primero
        resultados['alertas'] = db.session.query(AlertaVencimiento).delete()
        resultados['siniestros'] = db.session.query(Siniestro).delete()
        resultados['pagos'] = db.session.query(Pago).delete()
        resultados['interacciones'] = db.session.query(Interaccion).delete()
        resultados['envios'] = db.session.query(EnvioWhatsApp).delete()

        # 2. Pólizas
        resultados['polizas'] = db.session.query(PolizaCliente).delete()

        # 3. Clientes
        resultados['clientes'] = db.session.query(Cliente).filter(
            Cliente.usuario_id == current_user.id
        ).delete()

        # 4. Logs de escaneo
        resultados['logs_escaneo'] = db.session.query(LogEscaneo).delete()

        # 5. Archivos descargados
        resultados['archivos'] = db.session.query(ArchivoDescargado).delete()

        # 6. Memoria de escaneo
        resultados['correos_procesados'] = db.session.query(CorreoProcesado).delete()
        resultados['rangos_cobertura'] = db.session.query(RangoCobertura).delete()

        # 7. Escaneos
        resultados['escaneos'] = db.session.query(Escaneo).delete()

        db.session.commit()

        # Limpiar carpeta de archivos
        archivos_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'archivos_usuarios'))
        if archivos_dir.exists():
            for item in archivos_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                elif item.is_file():
                    item.unlink(missing_ok=True)
            resultados['carpeta_archivos'] = 'limpiada'

        return jsonify({
            "success": True,
            "mensaje": "Reset total completado",
            "resultados": resultados
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
