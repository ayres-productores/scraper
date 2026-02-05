"""
Script de migración para agregar ID de documento a PDFs existentes.
Ejecutar una sola vez: python migrar_id_documento.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import ArchivoDescargado
from sqlalchemy import text

def migrar():
    app = create_app()

    with app.app_context():
        # Verificar si la columna existe
        try:
            db.session.execute(text("SELECT id_documento FROM archivos_descargados LIMIT 1"))
            print("[OK] Columna id_documento ya existe")
        except:
            # Crear la columna
            print("[*] Creando columna id_documento...")
            db.session.execute(text("ALTER TABLE archivos_descargados ADD COLUMN id_documento VARCHAR(10)"))
            db.session.commit()
            print("[OK] Columna creada")

        # Contar archivos sin ID
        archivos_sin_id = ArchivoDescargado.query.filter(
            (ArchivoDescargado.id_documento == None) | (ArchivoDescargado.id_documento == '')
        ).order_by(ArchivoDescargado.id).all()

        total = len(archivos_sin_id)
        if total == 0:
            print("[OK] Todos los archivos ya tienen ID de documento")
            return

        print(f"[*] Asignando ID a {total} archivos...")

        # Obtener el último número usado
        ultimo_doc = db.session.query(ArchivoDescargado.id_documento).filter(
            ArchivoDescargado.id_documento.isnot(None),
            ArchivoDescargado.id_documento != ''
        ).order_by(ArchivoDescargado.id_documento.desc()).first()

        siguiente_num = 1
        if ultimo_doc and ultimo_doc[0]:
            try:
                siguiente_num = int(ultimo_doc[0].replace('PDF-', '')) + 1
            except:
                pass

        # Asignar IDs
        for i, archivo in enumerate(archivos_sin_id, 1):
            archivo.id_documento = f"PDF-{siguiente_num:04d}"
            siguiente_num += 1

            if i % 100 == 0:
                print(f"    Procesados {i}/{total}...")
                db.session.commit()

        db.session.commit()
        print(f"[OK] Asignados {total} IDs de documento (PDF-0001 a PDF-{siguiente_num-1:04d})")

        # Crear índice si no existe
        try:
            db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_archivos_id_documento ON archivos_descargados(id_documento)"))
            db.session.commit()
            print("[OK] Índice creado")
        except Exception as e:
            print(f"[!] Índice ya existe o error: {e}")

        # Mostrar algunos ejemplos
        print("\n[*] Ejemplos de IDs asignados:")
        ejemplos = ArchivoDescargado.query.order_by(ArchivoDescargado.id).limit(5).all()
        for ej in ejemplos:
            print(f"    {ej.id_documento}: {ej.nombre_archivo[:50]}...")


if __name__ == '__main__':
    migrar()
