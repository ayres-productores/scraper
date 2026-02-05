"""
Migración: Crear tabla log_correcciones_extraccion
Para el sistema de aprendizaje predictivo de extracción de PDFs.
"""

import os
import sys

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import LogCorreccionExtraccion

def migrar():
    """Ejecuta la migración para crear la tabla log_correcciones_extraccion."""
    app = create_app()

    with app.app_context():
        print("=" * 60)
        print("MIGRACIÓN: Crear tabla log_correcciones_extraccion")
        print("=" * 60)

        # Verificar si la tabla ya existe
        inspector = db.inspect(db.engine)
        tablas_existentes = inspector.get_table_names()

        if 'log_correcciones_extraccion' in tablas_existentes:
            print("\n[INFO] La tabla 'log_correcciones_extraccion' ya existe.")
            print("No es necesario ejecutar esta migración.")
            return

        print("\n[1/2] Creando tabla log_correcciones_extraccion...")

        try:
            # Crear solo la tabla específica
            LogCorreccionExtraccion.__table__.create(db.engine, checkfirst=True)
            print("      Tabla creada correctamente.")
        except Exception as e:
            print(f"      Error creando tabla: {e}")
            # Intentar con db.create_all() como fallback
            print("      Intentando con db.create_all()...")
            db.create_all()

        print("\n[2/2] Verificando índices...")

        # Verificar que los índices se crearon
        indices = inspector.get_indexes('log_correcciones_extraccion')
        print(f"      Índices creados: {len(indices)}")
        for idx in indices:
            print(f"        - {idx['name']}: {idx['column_names']}")

        print("\n" + "=" * 60)
        print("MIGRACIÓN COMPLETADA EXITOSAMENTE")
        print("=" * 60)

        # Mostrar estructura de la tabla
        print("\nEstructura de la tabla:")
        columns = inspector.get_columns('log_correcciones_extraccion')
        for col in columns:
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            print(f"  - {col['name']}: {col['type']} {nullable}")


if __name__ == '__main__':
    migrar()
