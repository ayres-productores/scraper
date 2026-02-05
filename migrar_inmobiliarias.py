"""
Script de migración para agregar soporte de inmobiliarias.

Cambios:
1. Crea tabla 'inmobiliarias'
2. Crea tabla 'notificaciones_inmobiliaria'
3. Agrega columna 'inmobiliaria_id' a 'polizas_cliente'

Ejecutar: python migrar_inmobiliarias.py
"""

import sqlite3
import os

# Ruta a la base de datos
DB_PATH = os.path.join(os.path.dirname(__file__), 'portal_seguros.db')


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
        # 1. Crear tabla inmobiliarias
        # =====================================================================
        print("\n1. Creando tabla 'inmobiliarias'...")

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='inmobiliarias'
        """)

        if cursor.fetchone():
            print("   - Tabla 'inmobiliarias' ya existe, saltando...")
        else:
            cursor.execute("""
                CREATE TABLE inmobiliarias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    nombre VARCHAR(150) NOT NULL,
                    telefono_whatsapp VARCHAR(30),
                    email VARCHAR(120),
                    persona_contacto VARCHAR(100),
                    activa BOOLEAN DEFAULT 1,
                    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                    notas TEXT,
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
                    UNIQUE (usuario_id, nombre)
                )
            """)
            print("   - Tabla 'inmobiliarias' creada correctamente")

        # =====================================================================
        # 2. Crear tabla notificaciones_inmobiliaria
        # =====================================================================
        print("\n2. Creando tabla 'notificaciones_inmobiliaria'...")

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='notificaciones_inmobiliaria'
        """)

        if cursor.fetchone():
            print("   - Tabla 'notificaciones_inmobiliaria' ya existe, saltando...")
        else:
            cursor.execute("""
                CREATE TABLE notificaciones_inmobiliaria (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inmobiliaria_id INTEGER NOT NULL,
                    poliza_id INTEGER NOT NULL,
                    tipo VARCHAR(30) NOT NULL,
                    mensaje TEXT,
                    estado VARCHAR(20) DEFAULT 'pendiente',
                    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                    fecha_envio DATETIME,
                    intentos INTEGER DEFAULT 0,
                    mensaje_error TEXT,
                    FOREIGN KEY (inmobiliaria_id) REFERENCES inmobiliarias(id),
                    FOREIGN KEY (poliza_id) REFERENCES polizas_cliente(id)
                )
            """)
            print("   - Tabla 'notificaciones_inmobiliaria' creada correctamente")

        # =====================================================================
        # 3. Agregar columna inmobiliaria_id a polizas_cliente
        # =====================================================================
        print("\n3. Agregando columna 'inmobiliaria_id' a 'polizas_cliente'...")

        # Verificar si la columna ya existe
        cursor.execute("PRAGMA table_info(polizas_cliente)")
        columnas = [col[1] for col in cursor.fetchall()]

        if 'inmobiliaria_id' in columnas:
            print("   - Columna 'inmobiliaria_id' ya existe, saltando...")
        else:
            cursor.execute("""
                ALTER TABLE polizas_cliente
                ADD COLUMN inmobiliaria_id INTEGER REFERENCES inmobiliarias(id)
            """)
            print("   - Columna 'inmobiliaria_id' agregada correctamente")

        # =====================================================================
        # 4. Crear índices
        # =====================================================================
        print("\n4. Creando índices...")

        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS ix_notif_inmob_estado
                ON notificaciones_inmobiliaria(estado)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS ix_notif_inmob_fecha
                ON notificaciones_inmobiliaria(fecha_creacion)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS ix_poliza_inmobiliaria
                ON polizas_cliente(inmobiliaria_id)
            """)
            print("   - Índices creados correctamente")
        except Exception as e:
            print(f"   - Advertencia creando índices: {e}")

        # Commit de los cambios
        conn.commit()
        print("\n" + "=" * 60)
        print("MIGRACION COMPLETADA EXITOSAMENTE")
        print("=" * 60)

        # Mostrar resumen
        print("\nResumen de tablas:")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tablas = cursor.fetchall()
        for tabla in tablas:
            cursor.execute(f"SELECT COUNT(*) FROM {tabla[0]}")
            count = cursor.fetchone()[0]
            print(f"  - {tabla[0]}: {count} registros")

        return True

    except Exception as e:
        print(f"\nERROR durante la migración: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


if __name__ == '__main__':
    migrar()
