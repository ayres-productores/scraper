"""
Script de migración para el módulo de distribución de pólizas
Ejecutar con: python migrar_distribucion.py
"""

import os
import sys

# Añadir el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from sqlalchemy import text, inspect

def migrar():
    """Ejecuta la migración de la base de datos para distribución."""
    app = create_app()

    with app.app_context():
        inspector = inspect(db.engine)
        tablas_existentes = inspector.get_table_names()

        print("=" * 60)
        print("MIGRACIÓN: Módulo de Distribución de Pólizas por WhatsApp")
        print("=" * 60)

        # 1. Crear tabla clientes
        if 'clientes' not in tablas_existentes:
            print("\n[1/5] Creando tabla 'clientes'...")
            db.session.execute(text("""
                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                    nombre VARCHAR(100) NOT NULL,
                    apellido VARCHAR(100),
                    telefono_whatsapp VARCHAR(20) NOT NULL,
                    email VARCHAR(120),
                    documento_identidad VARCHAR(30),
                    notas TEXT,
                    mensaje_personalizado TEXT,
                    usar_mensaje_estandar BOOLEAN DEFAULT 1,
                    activo BOOLEAN DEFAULT 1,
                    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ultimo_envio DATETIME
                )
            """))
            db.session.commit()
            print("    Tabla 'clientes' creada correctamente.")
        else:
            print("\n[1/5] Tabla 'clientes' ya existe. Saltando...")

        # 2. Crear tabla polizas_cliente
        if 'polizas_cliente' not in tablas_existentes:
            print("\n[2/5] Creando tabla 'polizas_cliente'...")
            db.session.execute(text("""
                CREATE TABLE polizas_cliente (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
                    archivo_id INTEGER REFERENCES archivos_descargados(id),
                    compania_id INTEGER REFERENCES companias(id),
                    numero_poliza VARCHAR(50),
                    tipo_seguro VARCHAR(50),
                    fecha_vigencia_desde DATE,
                    fecha_vigencia_hasta DATE,
                    prima_anual DECIMAL(10,2),
                    notas TEXT,
                    fecha_asignacion DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.commit()
            print("    Tabla 'polizas_cliente' creada correctamente.")
        else:
            print("\n[2/5] Tabla 'polizas_cliente' ya existe. Saltando...")

        # 3. Crear tabla envios_whatsapp
        if 'envios_whatsapp' not in tablas_existentes:
            print("\n[3/5] Creando tabla 'envios_whatsapp'...")
            db.session.execute(text("""
                CREATE TABLE envios_whatsapp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
                    poliza_cliente_id INTEGER REFERENCES polizas_cliente(id),
                    archivo_id INTEGER REFERENCES archivos_descargados(id),
                    mensaje_enviado TEXT,
                    estado VARCHAR(20) DEFAULT 'pendiente',
                    fecha_programada DATETIME,
                    fecha_envio DATETIME,
                    mensaje_error TEXT,
                    intentos INTEGER DEFAULT 0
                )
            """))
            db.session.commit()
            print("    Tabla 'envios_whatsapp' creada correctamente.")
        else:
            print("\n[3/5] Tabla 'envios_whatsapp' ya existe. Saltando...")

        # 4. Crear tabla plantillas_mensaje
        if 'plantillas_mensaje' not in tablas_existentes:
            print("\n[4/5] Creando tabla 'plantillas_mensaje'...")
            db.session.execute(text("""
                CREATE TABLE plantillas_mensaje (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                    nombre_plantilla VARCHAR(100) NOT NULL,
                    mensaje TEXT NOT NULL,
                    es_predeterminada BOOLEAN DEFAULT 0,
                    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                    fecha_modificacion DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.commit()
            print("    Tabla 'plantillas_mensaje' creada correctamente.")
        else:
            print("\n[4/5] Tabla 'plantillas_mensaje' ya existe. Saltando...")

        # 5. Crear plantilla de mensaje predeterminada para usuarios existentes
        print("\n[5/5] Creando plantillas predeterminadas...")
        from app.models import Usuario, PlantillaMensaje

        usuarios = Usuario.query.all()
        plantillas_creadas = 0

        mensaje_default = """Estimado/a {nombre},

Le adjuntamos su póliza de {tipo_seguro} con {compania}.

Número de póliza: {numero_poliza}
Vigencia: {vigencia_desde} - {vigencia_hasta}

Quedamos a su disposición para cualquier consulta.

Saludos cordiales."""

        for usuario in usuarios:
            # Verificar si ya tiene plantilla predeterminada
            tiene_plantilla = PlantillaMensaje.query.filter_by(
                usuario_id=usuario.id,
                es_predeterminada=True
            ).first()

            if not tiene_plantilla:
                plantilla = PlantillaMensaje(
                    usuario_id=usuario.id,
                    nombre_plantilla='Mensaje Estándar',
                    mensaje=mensaje_default,
                    es_predeterminada=True
                )
                db.session.add(plantilla)
                plantillas_creadas += 1

        if plantillas_creadas > 0:
            db.session.commit()
            print(f"    {plantillas_creadas} plantilla(s) predeterminada(s) creada(s).")
        else:
            print("    Todos los usuarios ya tienen plantillas predeterminadas.")

        print("\n" + "=" * 60)
        print("MIGRACIÓN COMPLETADA EXITOSAMENTE")
        print("=" * 60)
        print("\nNuevas tablas creadas:")
        print("  - clientes: Cartera de clientes del broker")
        print("  - polizas_cliente: Asignación de pólizas a clientes")
        print("  - envios_whatsapp: Historial de envíos")
        print("  - plantillas_mensaje: Plantillas de mensajes")
        print("\nPuedes acceder al módulo en: /distribucion")


if __name__ == '__main__':
    migrar()
