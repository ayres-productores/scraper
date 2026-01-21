"""
Script de migracion para el sistema CRM completo.
Agrega columnas expandidas a polizas_cliente y crea nuevas tablas CRM.
Ejecutar con: python migrar_crm_completo.py
"""

import os
import sys

# Anadir el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from sqlalchemy import text, inspect


def columna_existe(inspector, tabla, columna):
    """Verifica si una columna existe en una tabla."""
    columnas = [c['name'] for c in inspector.get_columns(tabla)]
    return columna in columnas


def agregar_columna(tabla, columna, tipo_sql):
    """Agrega una columna a una tabla si no existe."""
    try:
        db.session.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sql}"))
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        return False


def migrar():
    """Ejecuta la migracion de la base de datos para CRM completo."""
    app = create_app()

    with app.app_context():
        inspector = inspect(db.engine)
        tablas_existentes = inspector.get_table_names()

        print("=" * 70)
        print("MIGRACION: Sistema CRM Completo de Polizas")
        print("=" * 70)

        # ================================================================
        # PARTE 1: Agregar columnas a polizas_cliente
        # ================================================================
        print("\n[FASE 1] Expandiendo tabla 'polizas_cliente'...")

        if 'polizas_cliente' in tablas_existentes:
            columnas_nuevas = [
                # Datos del asegurado
                ("asegurado_nombre", "VARCHAR(150)"),
                ("asegurado_documento", "VARCHAR(30)"),
                ("asegurado_direccion", "VARCHAR(255)"),
                ("asegurado_telefono", "VARCHAR(30)"),
                ("asegurado_email", "VARCHAR(120)"),

                # Bien asegurado
                ("bien_asegurado_tipo", "VARCHAR(50)"),
                ("bien_asegurado_descripcion", "TEXT"),
                ("bien_asegurado_valor", "DECIMAL(12,2)"),

                # Datos de vehiculo
                ("vehiculo_marca", "VARCHAR(50)"),
                ("vehiculo_modelo", "VARCHAR(50)"),
                ("vehiculo_anio", "INTEGER"),
                ("vehiculo_patente", "VARCHAR(20)"),
                ("vehiculo_chasis", "VARCHAR(50)"),
                ("vehiculo_motor", "VARCHAR(50)"),
                ("vehiculo_color", "VARCHAR(30)"),
                ("vehiculo_uso", "VARCHAR(50)"),

                # Datos de inmueble
                ("inmueble_direccion", "VARCHAR(255)"),
                ("inmueble_tipo", "VARCHAR(50)"),
                ("inmueble_superficie", "DECIMAL(10,2)"),
                ("inmueble_construccion", "VARCHAR(50)"),

                # Coberturas y deducibles
                ("coberturas", "TEXT"),
                ("suma_asegurada", "DECIMAL(12,2)"),
                ("deducible", "DECIMAL(10,2)"),
                ("franquicia", "DECIMAL(10,2)"),

                # Beneficiarios
                ("beneficiarios", "TEXT"),

                # Estado y renovacion
                ("estado", "VARCHAR(20) DEFAULT 'activa'"),
                ("renovacion_automatica", "BOOLEAN DEFAULT 0"),
                ("poliza_anterior_id", "INTEGER"),
                ("motivo_cancelacion", "TEXT"),
                ("fecha_cancelacion", "DATE"),

                # Forma de pago
                ("forma_pago", "VARCHAR(20)"),
                ("cantidad_cuotas", "INTEGER"),
                ("dia_vencimiento_cuota", "INTEGER"),
                ("medio_pago", "VARCHAR(30)"),

                # Contacto productor
                ("productor_nombre", "VARCHAR(100)"),
                ("productor_telefono", "VARCHAR(30)"),
                ("productor_email", "VARCHAR(120)"),
                ("sucursal", "VARCHAR(100)"),

                # Datos extraidos automaticamente
                ("datos_extraidos", "TEXT"),
                ("confianza_extraccion", "FLOAT"),
                ("requiere_revision", "BOOLEAN DEFAULT 0"),
                ("fecha_extraccion", "DATETIME"),

                # Auditoria
                ("fecha_ultima_modificacion", "DATETIME"),
                ("modificado_por_id", "INTEGER"),
            ]

            columnas_agregadas = 0
            columnas_existentes = 0

            for columna, tipo_sql in columnas_nuevas:
                if columna_existe(inspector, 'polizas_cliente', columna):
                    columnas_existentes += 1
                else:
                    if agregar_columna('polizas_cliente', columna, tipo_sql):
                        columnas_agregadas += 1
                        print(f"    + Columna '{columna}' agregada")
                    else:
                        print(f"    ! Error agregando columna '{columna}'")

            print(f"\n    Resumen: {columnas_agregadas} columnas nuevas, {columnas_existentes} ya existian")
        else:
            print("    ! Tabla 'polizas_cliente' no existe. Ejecuta primero migrar_distribucion.py")

        # ================================================================
        # PARTE 2: Crear nuevas tablas CRM
        # ================================================================
        print("\n[FASE 2] Creando tablas CRM...")

        # Tabla: pagos
        if 'pagos' not in tablas_existentes:
            print("\n    Creando tabla 'pagos'...")
            db.session.execute(text("""
                CREATE TABLE pagos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    poliza_cliente_id INTEGER NOT NULL REFERENCES polizas_cliente(id),
                    numero_cuota INTEGER,
                    monto DECIMAL(10,2) NOT NULL,
                    fecha_vencimiento DATE NOT NULL,
                    fecha_pago DATE,
                    estado VARCHAR(20) DEFAULT 'pendiente',
                    metodo_pago VARCHAR(30),
                    comprobante VARCHAR(100),
                    notas TEXT,
                    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.commit()
            print("    Tabla 'pagos' creada correctamente.")
        else:
            print("\n    Tabla 'pagos' ya existe. Saltando...")

        # Tabla: interacciones
        if 'interacciones' not in tablas_existentes:
            print("\n    Creando tabla 'interacciones'...")
            db.session.execute(text("""
                CREATE TABLE interacciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
                    poliza_cliente_id INTEGER REFERENCES polizas_cliente(id),
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                    tipo VARCHAR(30) NOT NULL,
                    direccion VARCHAR(20),
                    asunto VARCHAR(200),
                    descripcion TEXT,
                    fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
                    duracion_minutos INTEGER,
                    requiere_seguimiento BOOLEAN DEFAULT 0,
                    fecha_seguimiento DATE,
                    seguimiento_completado BOOLEAN DEFAULT 0,
                    notas_seguimiento TEXT
                )
            """))
            db.session.commit()
            print("    Tabla 'interacciones' creada correctamente.")
        else:
            print("\n    Tabla 'interacciones' ya existe. Saltando...")

        # Tabla: alertas_vencimiento
        if 'alertas_vencimiento' not in tablas_existentes:
            print("\n    Creando tabla 'alertas_vencimiento'...")
            db.session.execute(text("""
                CREATE TABLE alertas_vencimiento (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                    poliza_cliente_id INTEGER REFERENCES polizas_cliente(id),
                    pago_id INTEGER REFERENCES pagos(id),
                    tipo VARCHAR(30) NOT NULL,
                    fecha_alerta DATE NOT NULL,
                    dias_anticipacion INTEGER,
                    estado VARCHAR(20) DEFAULT 'pendiente',
                    fecha_notificacion DATETIME,
                    mensaje TEXT,
                    prioridad VARCHAR(10) DEFAULT 'media',
                    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.commit()
            print("    Tabla 'alertas_vencimiento' creada correctamente.")
        else:
            print("\n    Tabla 'alertas_vencimiento' ya existe. Saltando...")

        # Tabla: siniestros
        if 'siniestros' not in tablas_existentes:
            print("\n    Creando tabla 'siniestros'...")
            db.session.execute(text("""
                CREATE TABLE siniestros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    poliza_cliente_id INTEGER NOT NULL REFERENCES polizas_cliente(id),
                    numero_siniestro VARCHAR(50),
                    numero_siniestro_compania VARCHAR(50),
                    fecha_ocurrencia DATE NOT NULL,
                    fecha_denuncia DATE,
                    hora_ocurrencia TIME,
                    descripcion TEXT NOT NULL,
                    ubicacion VARCHAR(255),
                    tipo_siniestro VARCHAR(50),
                    terceros_involucrados TEXT,
                    hay_lesionados BOOLEAN DEFAULT 0,
                    descripcion_lesiones TEXT,
                    monto_reclamado DECIMAL(12,2),
                    monto_aprobado DECIMAL(12,2),
                    monto_pagado DECIMAL(12,2),
                    deducible_aplicado DECIMAL(10,2),
                    estado VARCHAR(30) DEFAULT 'denunciado',
                    fecha_resolucion DATE,
                    motivo_rechazo TEXT,
                    documentos TEXT,
                    fotos TEXT,
                    notas TEXT,
                    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                    fecha_ultima_actualizacion DATETIME
                )
            """))
            db.session.commit()
            print("    Tabla 'siniestros' creada correctamente.")
        else:
            print("\n    Tabla 'siniestros' ya existe. Saltando...")

        # ================================================================
        # PARTE 3: Actualizar polizas existentes con estado por defecto
        # ================================================================
        print("\n[FASE 3] Actualizando registros existentes...")

        try:
            # Actualizar polizas sin estado
            result = db.session.execute(text("""
                UPDATE polizas_cliente
                SET estado = 'activa'
                WHERE estado IS NULL
            """))
            db.session.commit()
            print(f"    {result.rowcount} polizas actualizadas con estado 'activa'")
        except Exception as e:
            db.session.rollback()
            print(f"    Nota: {e}")

        # ================================================================
        # RESUMEN FINAL
        # ================================================================
        print("\n" + "=" * 70)
        print("MIGRACION COMPLETADA EXITOSAMENTE")
        print("=" * 70)
        print("\nCambios realizados:")
        print("  - polizas_cliente: Columnas expandidas para datos completos")
        print("  - pagos: Gestion de cuotas y primas")
        print("  - interacciones: Historial CRM de contactos")
        print("  - alertas_vencimiento: Sistema de alertas automaticas")
        print("  - siniestros: Gestion de siniestros")
        print("\nNuevas funcionalidades disponibles:")
        print("  - /distribucion/crm - Panel CRM")
        print("  - /distribucion/alertas - Centro de alertas")
        print("  - /distribucion/pagos/pendientes - Pagos pendientes")
        print("  - /distribucion/siniestros - Todos los siniestros")


if __name__ == '__main__':
    migrar()
