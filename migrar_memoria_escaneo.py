"""
Script de migracion para el sistema de memoria de escaneo.
Crea las tablas para evitar busquedas repetidas de correos.
Ejecutar con: python migrar_memoria_escaneo.py
"""

import os
import sys

# Anadir el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from sqlalchemy import text, inspect


def tabla_existe(inspector, tabla):
    """Verifica si una tabla existe."""
    return tabla in inspector.get_table_names()


def migrar():
    """Ejecuta la migracion para crear tablas de memoria de escaneo."""
    app = create_app()

    with app.app_context():
        inspector = inspect(db.engine)

        print("=" * 70)
        print("MIGRACION: Sistema de Memoria de Escaneo")
        print("=" * 70)
        print("Este sistema evita busquedas repetidas guardando:")
        print("  - IDs de correos ya procesados")
        print("  - Ultima fecha escaneada por carpeta")
        print("=" * 70)

        # ================================================================
        # TABLA 1: correos_procesados
        # ================================================================
        print("\n[1/2] Creando tabla 'correos_procesados'...")

        if tabla_existe(inspector, 'correos_procesados'):
            print("      -> Tabla ya existe, saltando...")
        else:
            try:
                db.session.execute(text("""
                    CREATE TABLE correos_procesados (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cuenta_gmail_id INTEGER NOT NULL,
                        message_id VARCHAR(255) NOT NULL,
                        carpeta VARCHAR(100) NOT NULL,
                        fecha_correo DATETIME,
                        remitente VARCHAR(255),
                        asunto VARCHAR(500),
                        tiene_pdfs BOOLEAN DEFAULT 0,
                        pdfs_descargados INTEGER DEFAULT 0,
                        fecha_procesado DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (cuenta_gmail_id) REFERENCES cuentas_gmail(id),
                        UNIQUE (cuenta_gmail_id, message_id, carpeta)
                    )
                """))
                db.session.commit()
                print("      -> Tabla creada exitosamente")

                # Crear indices
                db.session.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_correo_message_id
                    ON correos_procesados (message_id)
                """))
                db.session.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_correo_cuenta_carpeta
                    ON correos_procesados (cuenta_gmail_id, carpeta)
                """))
                db.session.commit()
                print("      -> Indices creados")
            except Exception as e:
                db.session.rollback()
                print(f"      -> ERROR: {e}")

        # ================================================================
        # TABLA 2: historial_escaneo_carpeta
        # ================================================================
        print("\n[2/2] Creando tabla 'historial_escaneo_carpeta'...")

        if tabla_existe(inspector, 'historial_escaneo_carpeta'):
            print("      -> Tabla ya existe, saltando...")
        else:
            try:
                db.session.execute(text("""
                    CREATE TABLE historial_escaneo_carpeta (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cuenta_gmail_id INTEGER NOT NULL,
                        carpeta VARCHAR(100) NOT NULL,
                        ultima_fecha_escaneada DATETIME,
                        ultimo_escaneo DATETIME DEFAULT CURRENT_TIMESTAMP,
                        correos_totales INTEGER DEFAULT 0,
                        correos_con_pdf INTEGER DEFAULT 0,
                        pdfs_descargados INTEGER DEFAULT 0,
                        FOREIGN KEY (cuenta_gmail_id) REFERENCES cuentas_gmail(id),
                        UNIQUE (cuenta_gmail_id, carpeta)
                    )
                """))
                db.session.commit()
                print("      -> Tabla creada exitosamente")
            except Exception as e:
                db.session.rollback()
                print(f"      -> ERROR: {e}")

        # ================================================================
        # RESUMEN
        # ================================================================
        print("\n" + "=" * 70)
        print("MIGRACION COMPLETADA")
        print("=" * 70)

        # Mostrar estadisticas
        inspector = inspect(db.engine)
        tablas = ['correos_procesados', 'historial_escaneo_carpeta']
        for tabla in tablas:
            if tabla_existe(inspector, tabla):
                try:
                    result = db.session.execute(text(f"SELECT COUNT(*) FROM {tabla}"))
                    count = result.scalar()
                    print(f"  - {tabla}: {count} registros")
                except:
                    print(f"  - {tabla}: creada")

        print("\nEl sistema ahora recordara:")
        print("  1. Que correos ya fueron revisados (por Message-ID)")
        print("  2. Hasta que fecha se escaneo cada carpeta")
        print("\nEsto evitara busquedas repetidas en futuros escaneos.")
        print("=" * 70)


if __name__ == '__main__':
    migrar()
