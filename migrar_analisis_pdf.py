"""
Script de migracion para crear tabla de registros de analisis de PDF.
Ejecutar una sola vez: python migrar_analisis_pdf.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import RegistroAnalisisPDF, ArchivoDescargado
from sqlalchemy import text

def migrar():
    app = create_app()

    with app.app_context():
        print("=== MIGRACION: Registros de Analisis de PDF ===\n")

        # Crear tabla si no existe
        try:
            db.session.execute(text("SELECT 1 FROM registros_analisis_pdf LIMIT 1"))
            print("[OK] Tabla registros_analisis_pdf ya existe")
        except:
            print("[*] Creando tabla registros_analisis_pdf...")
            db.create_all()
            print("[OK] Tabla creada")

        # Inicializar registros para archivos existentes
        archivos = db.session.query(ArchivoDescargado).outerjoin(
            RegistroAnalisisPDF
        ).filter(RegistroAnalisisPDF.id == None).all()

        if archivos:
            print(f"\n[*] Inicializando {len(archivos)} registros de analisis...")

            for i, archivo in enumerate(archivos, 1):
                registro = RegistroAnalisisPDF.obtener_o_crear(archivo.id)

                if i % 100 == 0:
                    print(f"    Procesados {i}/{len(archivos)}...")
                    db.session.commit()

            db.session.commit()
            print(f"[OK] Inicializados {len(archivos)} registros")
        else:
            print("[OK] No hay archivos pendientes de inicializar")

        # Mostrar estadisticas
        print("\n=== ESTADISTICAS ===")
        stats = RegistroAnalisisPDF.obtener_estadisticas()
        print(f"  Total registros: {stats['total']}")
        for estado, cantidad in stats['por_estado'].items():
            print(f"  - {estado}: {cantidad}")


if __name__ == '__main__':
    migrar()
