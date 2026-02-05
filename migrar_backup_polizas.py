"""
Script de migración para agregar soporte de backup de PDFs en pólizas.

Cambios:
1. Agrega columnas 'ruta_pdf_backup' y 'fecha_backup' a 'polizas_cliente'
2. Crea la carpeta de backup si no existe

Ejecutar: python migrar_backup_polizas.py
"""

import sqlite3
import os

# Ruta a la base de datos
DB_PATH = os.path.join(os.path.dirname(__file__), 'portal_seguros.db')
BACKUP_FOLDER = os.path.join(os.path.dirname(__file__), 'polizas_backup')


def migrar():
    """Ejecuta la migración."""
    print(f"Conectando a: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        print("ERROR: Base de datos no encontrada")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # =====================================================================
        # 1. Crear carpeta de backup
        # =====================================================================
        print("\n1. Creando carpeta de backup...")

        if not os.path.exists(BACKUP_FOLDER):
            os.makedirs(BACKUP_FOLDER)
            print(f"   - Carpeta creada: {BACKUP_FOLDER}")
        else:
            print(f"   - Carpeta ya existe: {BACKUP_FOLDER}")

        # =====================================================================
        # 2. Agregar columna ruta_pdf_backup a polizas_cliente
        # =====================================================================
        print("\n2. Agregando columna 'ruta_pdf_backup' a 'polizas_cliente'...")

        cursor.execute("PRAGMA table_info(polizas_cliente)")
        columnas = [col[1] for col in cursor.fetchall()]

        if 'ruta_pdf_backup' in columnas:
            print("   - Columna 'ruta_pdf_backup' ya existe, saltando...")
        else:
            cursor.execute("""
                ALTER TABLE polizas_cliente
                ADD COLUMN ruta_pdf_backup VARCHAR(500)
            """)
            print("   - Columna 'ruta_pdf_backup' agregada correctamente")

        # =====================================================================
        # 3. Agregar columna fecha_backup a polizas_cliente
        # =====================================================================
        print("\n3. Agregando columna 'fecha_backup' a 'polizas_cliente'...")

        cursor.execute("PRAGMA table_info(polizas_cliente)")
        columnas = [col[1] for col in cursor.fetchall()]

        if 'fecha_backup' in columnas:
            print("   - Columna 'fecha_backup' ya existe, saltando...")
        else:
            cursor.execute("""
                ALTER TABLE polizas_cliente
                ADD COLUMN fecha_backup DATETIME
            """)
            print("   - Columna 'fecha_backup' agregada correctamente")

        # Commit de los cambios
        conn.commit()
        print("\n" + "=" * 60)
        print("MIGRACION COMPLETADA EXITOSAMENTE")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\nERROR durante la migración: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


if __name__ == '__main__':
    migrar()
