"""
Migración: Agregar campos de vigencia a registros_analisis_pdf
Fecha: 2026-01-30

Ejecutar con: python migrations/add_vigencia_analisis.py
"""

import sys
import os

# Agregar el directorio padre al path para importar app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, create_app
from sqlalchemy import text


def upgrade():
    """Aplicar migración - agregar campos de vigencia detectada."""
    app = create_app()
    with app.app_context():
        conn = db.engine.connect()

        print("=" * 50)
        print("  MIGRACIÓN: Campos de Vigencia en Análisis PDF")
        print("=" * 50)
        print()

        # 1. RegistroAnalisisPDF - agregar campos de vigencia detectada
        print("[1/2] Agregando campos a registros_analisis_pdf...")
        for column, definition in [
            ('fecha_vigencia_desde_detectada', 'DATE'),
            ('fecha_vigencia_hasta_detectada', 'DATE'),
            ('asegurado_detectado', 'VARCHAR(200)')
        ]:
            try:
                conn.execute(text(f"ALTER TABLE registros_analisis_pdf ADD COLUMN {column} {definition}"))
                print(f"      + {column} agregado")
            except Exception as e:
                if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f"      ~ {column} ya existe")
                else:
                    print(f"      ! Error en {column}: {e}")

        # 2. Crear índice para fecha_vigencia_hasta_detectada
        print("[2/2] Creando índice para vigencia...")
        try:
            conn.execute(text("CREATE INDEX ix_registro_analisis_vigencia ON registros_analisis_pdf(fecha_vigencia_hasta_detectada)"))
            print("      + Índice ix_registro_analisis_vigencia creado")
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print("      ~ Índice ya existe")
            else:
                print(f"      ! Error: {e}")

        conn.commit()
        conn.close()

        print()
        print("=" * 50)
        print("  MIGRACIÓN COMPLETADA")
        print("=" * 50)


if __name__ == '__main__':
    upgrade()
