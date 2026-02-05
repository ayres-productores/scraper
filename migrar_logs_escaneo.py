"""
Script de migración para agregar tabla logs_escaneo.
Sistema de logs persistentes para monitoreo de escaneos desatendidos.
"""

import sqlite3
import os

# Ruta a la base de datos
DB_PATH = os.path.join(os.path.dirname(__file__), 'portal_seguros.db')

def migrar():
    """Ejecuta la migración."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Verificar si la tabla ya existe
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='logs_escaneo'
    """)

    if cursor.fetchone():
        print("La tabla 'logs_escaneo' ya existe.")
        conn.close()
        return

    # Crear tabla logs_escaneo
    print("Creando tabla 'logs_escaneo'...")
    cursor.execute("""
        CREATE TABLE logs_escaneo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            escaneo_id INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            nivel VARCHAR(10) DEFAULT 'info',
            categoria VARCHAR(30) DEFAULT 'sistema',
            mensaje VARCHAR(500) NOT NULL,
            cuenta_gmail VARCHAR(120),
            carpeta VARCHAR(100),
            correo_message_id VARCHAR(200),
            archivo_nombre VARCHAR(255),
            datos_extra TEXT,
            FOREIGN KEY (escaneo_id) REFERENCES escaneos(id) ON DELETE CASCADE
        )
    """)

    # Crear índices para consultas rápidas
    print("Creando índices...")
    cursor.execute("""
        CREATE INDEX idx_logs_escaneo_escaneo_id ON logs_escaneo(escaneo_id)
    """)
    cursor.execute("""
        CREATE INDEX idx_logs_escaneo_timestamp ON logs_escaneo(timestamp)
    """)
    cursor.execute("""
        CREATE INDEX idx_logs_escaneo_nivel ON logs_escaneo(nivel)
    """)

    conn.commit()
    conn.close()

    print("Migración completada exitosamente.")
    print("")
    print("Campos de logs_escaneo:")
    print("  - escaneo_id: ID del escaneo")
    print("  - timestamp: Fecha/hora del evento")
    print("  - nivel: info, success, warning, error")
    print("  - categoria: conexion, carpeta, correo, pdf, sistema, memoria")
    print("  - mensaje: Descripción del evento")
    print("  - cuenta_gmail: Cuenta procesada")
    print("  - carpeta: Carpeta IMAP")
    print("  - correo_message_id: ID del correo")
    print("  - archivo_nombre: Nombre del PDF")
    print("  - datos_extra: JSON con info adicional")


if __name__ == '__main__':
    migrar()
