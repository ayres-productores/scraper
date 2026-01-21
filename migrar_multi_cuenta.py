"""
Script de migración para soporte multi-cuenta y compañías
Ejecutar con: python migrar_multi_cuenta.py
"""

import os
import sys

# Añadir el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from sqlalchemy import text, inspect

def migrar():
    """Ejecuta la migración de la base de datos."""
    app = create_app()

    with app.app_context():
        inspector = inspect(db.engine)
        tablas_existentes = inspector.get_table_names()

        print("=" * 50)
        print("MIGRACIÓN: Soporte Multi-Cuenta y Compañías")
        print("=" * 50)

        # 1. Crear tabla companias si no existe
        if 'companias' not in tablas_existentes:
            print("\n[1/4] Creando tabla 'companias'...")
            db.session.execute(text("""
                CREATE TABLE companias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre VARCHAR(100) NOT NULL,
                    dominio_email VARCHAR(100) UNIQUE,
                    cantidad_documentos INTEGER DEFAULT 0,
                    fecha_primer_documento DATETIME,
                    fecha_ultimo_documento DATETIME
                )
            """))
            db.session.execute(text("CREATE INDEX ix_companias_nombre ON companias (nombre)"))
            db.session.commit()
            print("    Tabla 'companias' creada correctamente.")
        else:
            print("\n[1/4] Tabla 'companias' ya existe. Saltando...")

        # 2. Añadir columnas a tabla escaneos
        print("\n[2/4] Actualizando tabla 'escaneos'...")
        columnas_escaneos = [col['name'] for col in inspector.get_columns('escaneos')]

        columnas_nuevas_escaneos = {
            'es_multi_cuenta': 'BOOLEAN DEFAULT 0',
            'cuentas_escaneadas': 'TEXT',
            'cuenta_actual': 'VARCHAR(120)'
        }

        for columna, tipo in columnas_nuevas_escaneos.items():
            if columna not in columnas_escaneos:
                print(f"    Añadiendo columna '{columna}'...")
                db.session.execute(text(f"ALTER TABLE escaneos ADD COLUMN {columna} {tipo}"))
                db.session.commit()
            else:
                print(f"    Columna '{columna}' ya existe. Saltando...")

        # 3. Añadir columnas a tabla archivos_descargados
        print("\n[3/4] Actualizando tabla 'archivos_descargados'...")
        columnas_archivos = [col['name'] for col in inspector.get_columns('archivos_descargados')]

        columnas_nuevas_archivos = {
            'compania_id': 'INTEGER REFERENCES companias(id)',
            'nombre_compania_original': 'VARCHAR(255)',
            'cuenta_origen': 'VARCHAR(120)'
        }

        for columna, tipo in columnas_nuevas_archivos.items():
            if columna not in columnas_archivos:
                print(f"    Añadiendo columna '{columna}'...")
                db.session.execute(text(f"ALTER TABLE archivos_descargados ADD COLUMN {columna} {tipo}"))
                db.session.commit()
            else:
                print(f"    Columna '{columna}' ya existe. Saltando...")

        # 4. Migrar datos existentes (detectar compañías de archivos existentes)
        print("\n[4/4] Migrando datos existentes...")

        from app.models import ArchivoDescargado, Compania

        archivos_sin_compania = ArchivoDescargado.query.filter_by(compania_id=None).all()
        migrados = 0

        for archivo in archivos_sin_compania:
            if archivo.remitente:
                compania = Compania.detectar_o_crear(archivo.remitente)
                if compania:
                    archivo.compania_id = compania.id
                    archivo.nombre_compania_original = archivo.remitente.split('<')[0].strip()[:255]
                    compania.incrementar_contador()
                    migrados += 1

        if migrados > 0:
            db.session.commit()
            print(f"    {migrados} archivos migrados con compañía detectada.")
        else:
            print("    No hay archivos pendientes de migrar.")

        print("\n" + "=" * 50)
        print("MIGRACIÓN COMPLETADA EXITOSAMENTE")
        print("=" * 50)
        print("\nPuedes reiniciar el servidor Flask para aplicar los cambios.")


if __name__ == '__main__':
    migrar()
