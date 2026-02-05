"""
Script de migración para agregar índices a foreign keys.

Este script crea los índices necesarios para mejorar el rendimiento
de las consultas en la base de datos.

Ejecutar: python migrar_indices.py
"""

import os
import sys

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configurar modo desarrollo para evitar errores de claves
os.environ['FLASK_ENV'] = 'development'

from app import create_app, db
from sqlalchemy import text, inspect

app = create_app()

# Definir índices a crear
INDICES = [
    # (nombre_indice, tabla, columna)
    ('ix_cuentas_gmail_usuario_id', 'cuentas_gmail', 'usuario_id'),
    ('ix_escaneos_usuario_id', 'escaneos', 'usuario_id'),
    ('ix_escaneos_cuenta_gmail_id', 'escaneos', 'cuenta_gmail_id'),
    ('ix_escaneos_estado', 'escaneos', 'estado'),
    ('ix_logs_escaneo_escaneo_id', 'logs_escaneo', 'escaneo_id'),
    ('ix_archivos_descargados_escaneo_id', 'archivos_descargados', 'escaneo_id'),
    ('ix_archivos_descargados_compania_id', 'archivos_descargados', 'compania_id'),
    ('ix_archivos_descargados_hash_archivo', 'archivos_descargados', 'hash_archivo'),
    ('ix_archivos_descargados_fecha_descarga', 'archivos_descargados', 'fecha_descarga'),
    ('ix_logs_actividad_usuario_id', 'logs_actividad', 'usuario_id'),
    ('ix_logs_actividad_accion', 'logs_actividad', 'accion'),
    ('ix_clientes_usuario_id', 'clientes', 'usuario_id'),
    ('ix_clientes_nombre', 'clientes', 'nombre'),
    ('ix_clientes_apellido', 'clientes', 'apellido'),
    ('ix_clientes_documento_identidad', 'clientes', 'documento_identidad'),
    ('ix_clientes_activo', 'clientes', 'activo'),
    ('ix_clientes_es_cliente_actual', 'clientes', 'es_cliente_actual'),
    ('ix_polizas_cliente_cliente_id', 'polizas_cliente', 'cliente_id'),
    ('ix_polizas_cliente_archivo_id', 'polizas_cliente', 'archivo_id'),
    ('ix_polizas_cliente_compania_id', 'polizas_cliente', 'compania_id'),
    ('ix_polizas_cliente_inmobiliaria_id', 'polizas_cliente', 'inmobiliaria_id'),
    ('ix_polizas_cliente_numero_poliza', 'polizas_cliente', 'numero_poliza'),
    ('ix_polizas_cliente_tipo_seguro', 'polizas_cliente', 'tipo_seguro'),
    ('ix_polizas_cliente_fecha_vigencia_desde', 'polizas_cliente', 'fecha_vigencia_desde'),
    ('ix_polizas_cliente_fecha_vigencia_hasta', 'polizas_cliente', 'fecha_vigencia_hasta'),
    ('ix_polizas_cliente_estado', 'polizas_cliente', 'estado'),
]


def obtener_indices_existentes(inspector, tabla):
    """Obtiene los nombres de índices existentes en una tabla."""
    try:
        indices = inspector.get_indexes(tabla)
        return {idx['name'] for idx in indices if idx['name']}
    except Exception:
        return set()


def crear_indice(conn, nombre, tabla, columna):
    """Crea un índice si no existe."""
    try:
        sql = text(f'CREATE INDEX IF NOT EXISTS {nombre} ON {tabla} ({columna})')
        conn.execute(sql)
        return True
    except Exception as e:
        print(f"  Error creando índice {nombre}: {e}")
        return False


def main():
    print("=" * 60)
    print("MIGRACIÓN DE ÍNDICES - Portal de Seguros")
    print("=" * 60)

    with app.app_context():
        inspector = inspect(db.engine)

        # Obtener tablas existentes
        tablas_existentes = set(inspector.get_table_names())

        print(f"\nTablas encontradas: {len(tablas_existentes)}")

        creados = 0
        omitidos = 0
        errores = 0

        with db.engine.connect() as conn:
            for nombre_idx, tabla, columna in INDICES:
                # Verificar que la tabla existe
                if tabla not in tablas_existentes:
                    print(f"  [OMITIDO] {nombre_idx} - Tabla '{tabla}' no existe")
                    omitidos += 1
                    continue

                # Verificar si el índice ya existe
                indices_tabla = obtener_indices_existentes(inspector, tabla)
                if nombre_idx in indices_tabla:
                    print(f"  [EXISTE] {nombre_idx}")
                    omitidos += 1
                    continue

                # Crear el índice
                print(f"  [CREANDO] {nombre_idx} en {tabla}({columna})...", end=" ")
                if crear_indice(conn, nombre_idx, tabla, columna):
                    print("OK")
                    creados += 1
                else:
                    errores += 1

            conn.commit()

        print("\n" + "=" * 60)
        print(f"RESUMEN:")
        print(f"  - Índices creados: {creados}")
        print(f"  - Índices omitidos (ya existentes o tabla faltante): {omitidos}")
        print(f"  - Errores: {errores}")
        print("=" * 60)

        if creados > 0:
            print("\n¡Migración completada! Los nuevos índices mejorarán el rendimiento.")
        else:
            print("\nNo se crearon nuevos índices (ya estaban todos aplicados).")


if __name__ == '__main__':
    main()
