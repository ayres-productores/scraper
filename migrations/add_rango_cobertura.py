"""
Migracion: Crear tabla rangos_cobertura
Fecha: 2026-02-10

Ejecutar con: python migrations/add_rango_cobertura.py

Esta tabla rastrea las ventanas de tiempo que fueron escaneadas para cada
cuenta/carpeta, permitiendo identificar gaps en la cobertura de escaneos.
"""

import sys
import os

# Agregar el directorio padre al path para importar app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, create_app
from sqlalchemy import text


def upgrade():
    """Aplicar migracion - crear tabla rangos_cobertura."""
    app = create_app()
    with app.app_context():
        conn = db.engine.connect()

        print("=" * 50)
        print("  MIGRACION: Tabla RangoCobertura")
        print("=" * 50)
        print()

        # 1. Crear tabla rangos_cobertura
        print("[1/2] Creando tabla rangos_cobertura...")
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rangos_cobertura (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cuenta_gmail_id INTEGER NOT NULL,
                    carpeta VARCHAR(100) NOT NULL,
                    fecha_inicio DATE NOT NULL,
                    fecha_fin DATE NOT NULL,
                    escaneo_id INTEGER,
                    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (cuenta_gmail_id) REFERENCES cuentas_gmail(id),
                    FOREIGN KEY (escaneo_id) REFERENCES escaneos(id)
                )
            """))
            print("      + Tabla rangos_cobertura creada")
        except Exception as e:
            if 'already exists' in str(e).lower():
                print("      ~ Tabla ya existe")
            else:
                print(f"      ! Error: {e}")

        # 2. Crear indice compuesto
        print("[2/2] Creando indice ix_cobertura_cuenta_carpeta...")
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_cobertura_cuenta_carpeta
                ON rangos_cobertura(cuenta_gmail_id, carpeta)
            """))
            print("      + Indice creado")
        except Exception as e:
            if 'already exists' in str(e).lower():
                print("      ~ Indice ya existe")
            else:
                print(f"      ! Error: {e}")

        conn.commit()
        conn.close()

        print()
        print("=" * 50)
        print("  MIGRACION COMPLETADA")
        print("=" * 50)


def downgrade():
    """Revertir migracion - eliminar tabla rangos_cobertura."""
    app = create_app()
    with app.app_context():
        conn = db.engine.connect()

        print("Eliminando tabla rangos_cobertura...")
        try:
            conn.execute(text("DROP TABLE IF EXISTS rangos_cobertura"))
            print("Tabla eliminada")
        except Exception as e:
            print(f"Error: {e}")

        conn.commit()
        conn.close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()
