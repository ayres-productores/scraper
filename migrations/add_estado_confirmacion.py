"""
Migración: Agregar campos de estado de confirmación
Fecha: 2026-01-28

Ejecutar con: python migrations/add_estado_confirmacion.py
"""

import sys
import os

# Agregar el directorio padre al path para importar app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, create_app
from sqlalchemy import text


def upgrade():
    """Aplicar migración - agregar campos de estado de confirmación."""
    app = create_app()
    with app.app_context():
        conn = db.engine.connect()

        print("=" * 50)
        print("  MIGRACIÓN: Estado de Confirmación")
        print("=" * 50)
        print()

        # 1. PolizaCliente - agregar campos de confirmación
        print("[1/4] Agregando campos a polizas_cliente...")
        for column, definition in [
            ('estado_confirmacion', "VARCHAR(20) DEFAULT 'pendiente'"),
            ('fecha_confirmacion', 'DATETIME'),
            ('confirmado_por', 'VARCHAR(50)')
        ]:
            try:
                conn.execute(text(f"ALTER TABLE polizas_cliente ADD COLUMN {column} {definition}"))
                print(f"      + {column} agregado")
            except Exception as e:
                if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f"      ~ {column} ya existe")
                else:
                    print(f"      ! Error en {column}: {e}")

        # 2. ArchivoDescargado - agregar campos de confirmación
        print("[2/4] Agregando campos a archivos_descargados...")
        for column, definition in [
            ('estado_confirmacion', "VARCHAR(20) DEFAULT 'pendiente'"),
            ('fecha_confirmacion', 'DATETIME'),
            ('confirmado_por', 'VARCHAR(50)')
        ]:
            try:
                conn.execute(text(f"ALTER TABLE archivos_descargados ADD COLUMN {column} {definition}"))
                print(f"      + {column} agregado")
            except Exception as e:
                if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f"      ~ {column} ya existe")
                else:
                    print(f"      ! Error en {column}: {e}")

        # 3. EnvioWhatsApp - agregar campos de tracking
        print("[3/4] Agregando campos a envios_whatsapp...")
        for column, definition in [
            ('wamid', 'VARCHAR(100)'),
            ('estado_mensaje', 'VARCHAR(20)'),
            ('fecha_entregado', 'DATETIME'),
            ('fecha_leido', 'DATETIME')
        ]:
            try:
                conn.execute(text(f"ALTER TABLE envios_whatsapp ADD COLUMN {column} {definition}"))
                print(f"      + {column} agregado")
            except Exception as e:
                if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f"      ~ {column} ya existe")
                else:
                    print(f"      ! Error en {column}: {e}")

        # 4. Crear índice para wamid
        print("[4/4] Creando índice para wamid...")
        try:
            conn.execute(text("CREATE INDEX ix_envios_whatsapp_wamid ON envios_whatsapp(wamid)"))
            print("      + Índice ix_envios_whatsapp_wamid creado")
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
