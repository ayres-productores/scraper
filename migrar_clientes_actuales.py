"""
Script de migración para agregar campos de estado 'cliente actual'.
Sistema de seguimiento CRM para identificar clientes a reactivar.
"""

import sqlite3
import os

# Ruta a la base de datos
DB_PATH = os.path.join(os.path.dirname(__file__), 'portal_seguros.db')


def migrar():
    """Ejecuta la migración."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Verificar qué columnas ya existen
    cursor.execute("PRAGMA table_info(clientes)")
    columnas_existentes = [col[1] for col in cursor.fetchall()]

    cambios = 0

    # 1. Agregar columna es_cliente_actual
    if 'es_cliente_actual' not in columnas_existentes:
        print("Agregando columna 'es_cliente_actual'...")
        cursor.execute("""
            ALTER TABLE clientes
            ADD COLUMN es_cliente_actual BOOLEAN DEFAULT 1
        """)
        cambios += 1
    else:
        print("Columna 'es_cliente_actual' ya existe.")

    # 2. Agregar columna fecha_evaluacion_actual
    if 'fecha_evaluacion_actual' not in columnas_existentes:
        print("Agregando columna 'fecha_evaluacion_actual'...")
        cursor.execute("""
            ALTER TABLE clientes
            ADD COLUMN fecha_evaluacion_actual DATETIME
        """)
        cambios += 1
    else:
        print("Columna 'fecha_evaluacion_actual' ya existe.")

    # 3. Agregar columna motivo_no_actual
    if 'motivo_no_actual' not in columnas_existentes:
        print("Agregando columna 'motivo_no_actual'...")
        cursor.execute("""
            ALTER TABLE clientes
            ADD COLUMN motivo_no_actual VARCHAR(100)
        """)
        cambios += 1
    else:
        print("Columna 'motivo_no_actual' ya existe.")

    conn.commit()
    conn.close()

    if cambios > 0:
        print(f"\nMigración completada: {cambios} columna(s) agregada(s).")
    else:
        print("\nNo se requirieron cambios.")

    print("")
    print("Campos agregados al modelo Cliente:")
    print("  - es_cliente_actual: Boolean (default True)")
    print("  - fecha_evaluacion_actual: DateTime")
    print("  - motivo_no_actual: String (sin_comunicacion, sin_poliza_reciente, ambos)")
    print("")
    print("Para ejecutar la primera evaluación de clientes, usa:")
    print("  from app.tasks.clientes_actuales import evaluar_clientes_actuales")
    print("  evaluar_clientes_actuales(usuario_id)")


if __name__ == '__main__':
    migrar()
