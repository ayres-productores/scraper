"""
Script para limpiar TODOS los datos de PDFs y escaneos.
Permite re-escanear desde cero con el nuevo formato de nombres.

ADVERTENCIA: Esta operación es IRREVERSIBLE.
"""

import os
import shutil
from app import create_app, db
from app.models import (
    ArchivoDescargado, RegistroAnalisisPDF, LogEscaneo, Escaneo,
    CorreoProcesado, HistorialEscaneoCarpeta, EnvioWhatsApp,
    PolizaCliente, NotificacionInmobiliaria, Pago, Siniestro,
    AlertaVencimiento, Interaccion, Compania, DominioRemitente
)

def limpiar_base_datos():
    """Limpia todas las tablas relacionadas con PDFs y escaneos."""
    print("\n=== LIMPIANDO BASE DE DATOS ===\n")

    # Orden de limpieza (respetando foreign keys)
    tablas = [
        # Dependientes de polizas_cliente
        ("NotificacionInmobiliaria", NotificacionInmobiliaria),
        ("Pago", Pago),
        ("Siniestro", Siniestro),
        ("AlertaVencimiento", AlertaVencimiento),
        ("Interaccion", Interaccion),

        # Dependientes de archivos_descargados
        ("EnvioWhatsApp", EnvioWhatsApp),
        ("RegistroAnalisisPDF", RegistroAnalisisPDF),

        # Polizas (depende de archivos)
        ("PolizaCliente", PolizaCliente),

        # Archivos descargados
        ("ArchivoDescargado", ArchivoDescargado),

        # Logs y escaneos
        ("LogEscaneo", LogEscaneo),
        ("Escaneo", Escaneo),

        # Memoria de escaneo
        ("CorreoProcesado", CorreoProcesado),
        ("HistorialEscaneoCarpeta", HistorialEscaneoCarpeta),

        # Compañías y dominios (opcional - regenerables)
        ("Compania", Compania),
        ("DominioRemitente", DominioRemitente),
    ]

    for nombre, modelo in tablas:
        try:
            cantidad = modelo.query.count()
            if cantidad > 0:
                modelo.query.delete()
                print(f"  [OK] {nombre}: {cantidad} registros eliminados")
            else:
                print(f"  [--] {nombre}: ya vacía")
        except Exception as e:
            print(f"  [ERROR] {nombre}: {e}")

    db.session.commit()
    print("\n[OK] Base de datos limpiada correctamente")


def limpiar_archivos():
    """Elimina todos los PDFs de la carpeta uploads."""
    print("\n=== LIMPIANDO ARCHIVOS ===\n")

    uploads_dir = os.path.join(os.path.dirname(__file__), 'uploads')

    if not os.path.exists(uploads_dir):
        print(f"  [--] Carpeta uploads no existe: {uploads_dir}")
        return

    # Contar archivos antes de borrar
    total_archivos = 0
    total_bytes = 0

    for root, dirs, files in os.walk(uploads_dir):
        for f in files:
            total_archivos += 1
            try:
                total_bytes += os.path.getsize(os.path.join(root, f))
            except:
                pass

    print(f"  Archivos encontrados: {total_archivos}")
    print(f"  Tamaño total: {total_bytes / (1024*1024):.2f} MB")

    # Borrar contenido de uploads (mantener la carpeta)
    for item in os.listdir(uploads_dir):
        item_path = os.path.join(uploads_dir, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
                print(f"  [OK] Carpeta eliminada: {item}")
            else:
                os.remove(item_path)
                print(f"  [OK] Archivo eliminado: {item}")
        except Exception as e:
            print(f"  [ERROR] No se pudo eliminar {item}: {e}")

    print(f"\n[OK] Archivos limpiados: {total_archivos} archivos ({total_bytes / (1024*1024):.2f} MB)")


def main():
    """Ejecuta la limpieza completa."""
    print("=" * 60)
    print("   LIMPIEZA COMPLETA - PORTAL DE SEGUROS")
    print("=" * 60)
    print("\nEsto eliminará:")
    print("  - Todos los PDFs descargados")
    print("  - Todos los registros de escaneos")
    print("  - Todas las pólizas y datos asociados")
    print("  - Historial de correos procesados")
    print("\nEsta operación es IRREVERSIBLE.")
    print("-" * 60)

    confirmacion = input("\n¿Confirmar limpieza? Escriba 'SI' para continuar: ")

    if confirmacion.strip().upper() != 'SI':
        print("\n[CANCELADO] No se realizó ningún cambio.")
        return

    app = create_app()
    with app.app_context():
        limpiar_base_datos()
        limpiar_archivos()

    print("\n" + "=" * 60)
    print("   LIMPIEZA COMPLETADA")
    print("=" * 60)
    print("\nAhora puedes re-escanear los correos.")
    print("Los nuevos PDFs usarán el formato:")
    print("  COMPAÑIA - TOMADOR - BIEN - FECHA.pdf")
    print("=" * 60)


if __name__ == '__main__':
    main()
