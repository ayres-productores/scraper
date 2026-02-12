"""
Migración: Agregar campos de detección de cliente existente al momento del escaneo
Fecha: 2026-02-12

Ejecutar con: python migrations/add_cliente_existente_campos.py

Estos campos permiten detectar y vincular clientes existentes cuando se escanea un PDF,
evitando la creación de duplicados.
"""

import sys
import os

# Agregar el directorio padre al path para importar app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, create_app
from sqlalchemy import text


def upgrade():
    """Aplicar migración - agregar campos de cliente existente detectado."""
    app = create_app()
    with app.app_context():
        conn = db.engine.connect()

        print("=" * 60)
        print("  MIGRACIÓN: Cliente Existente Detectado al Escanear")
        print("=" * 60)
        print()

        # 1. ArchivoDescargado - agregar campos de datos asegurado extraídos
        print("[1/3] Agregando campos de datos asegurado extraídos...")
        for column, definition in [
            ('asegurado_nombre_extraido', 'VARCHAR(255)'),
            ('asegurado_documento_extraido', 'VARCHAR(50)'),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE archivos_descargados ADD COLUMN {column} {definition}"))
                print(f"      + {column} agregado")
            except Exception as e:
                if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f"      ~ {column} ya existe")
                else:
                    print(f"      ! Error en {column}: {e}")

        # 2. ArchivoDescargado - agregar campos de cliente existente detectado
        print("[2/3] Agregando campos de cliente existente detectado...")
        for column, definition in [
            ('cliente_existente_id', 'INTEGER REFERENCES clientes(id)'),
            ('cliente_match_tipo', 'VARCHAR(20)'),
            ('cliente_match_confianza', 'FLOAT'),
            ('fecha_matching', 'DATETIME'),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE archivos_descargados ADD COLUMN {column} {definition}"))
                print(f"      + {column} agregado")
            except Exception as e:
                if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f"      ~ {column} ya existe")
                else:
                    print(f"      ! Error en {column}: {e}")

        # 3. Crear índices para búsquedas eficientes
        print("[3/3] Creando índices...")
        indices = [
            ('ix_archivos_descargados_asegurado_documento', 'archivos_descargados(asegurado_documento_extraido)'),
            ('ix_archivos_descargados_cliente_existente', 'archivos_descargados(cliente_existente_id)'),
        ]
        for idx_name, idx_def in indices:
            try:
                conn.execute(text(f"CREATE INDEX {idx_name} ON {idx_def}"))
                print(f"      + Índice {idx_name} creado")
            except Exception as e:
                if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                    print(f"      ~ Índice {idx_name} ya existe")
                else:
                    print(f"      ! Error: {e}")

        conn.commit()
        conn.close()

        print()
        print("=" * 60)
        print("  MIGRACIÓN COMPLETADA")
        print("=" * 60)
        print()
        print("Nuevos campos agregados a archivos_descargados:")
        print("  - asegurado_nombre_extraido: Nombre del asegurado extraído del PDF")
        print("  - asegurado_documento_extraido: DNI/CUIT extraído del PDF")
        print("  - cliente_existente_id: FK al cliente si se encontró coincidencia")
        print("  - cliente_match_tipo: 'documento' | 'nombre_fuzzy' | NULL")
        print("  - cliente_match_confianza: 0.0 - 1.0 (1.0 = match exacto por documento)")
        print("  - fecha_matching: Cuándo se realizó el matching")


if __name__ == '__main__':
    upgrade()
