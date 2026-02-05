#!/usr/bin/env python
"""
Migración: Agregar tabla dominios_remitentes y columna dominios_filtro
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from sqlalchemy import text

def migrar():
    app = create_app()

    with app.app_context():
        print("=" * 60)
        print("  MIGRACIÓN: Sistema de Dominios de Remitentes")
        print("=" * 60)

        # 1. Crear tabla dominios_remitentes
        print("\n[1] Creando tabla dominios_remitentes...")
        try:
            db.session.execute(text('''
                CREATE TABLE IF NOT EXISTS dominios_remitentes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    dominio VARCHAR(100) NOT NULL,
                    nombre_mostrar VARCHAR(100),
                    cantidad_pdfs INTEGER DEFAULT 0,
                    ultimo_pdf DATETIME,
                    activo BOOLEAN DEFAULT 1,
                    fecha_detectado DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
                    UNIQUE (usuario_id, dominio)
                )
            '''))
            db.session.commit()
            print("    OK - Tabla creada")
        except Exception as e:
            if 'already exists' in str(e).lower():
                print("    OK - Tabla ya existe")
            else:
                print(f"    ERROR: {e}")

        # 2. Crear índice para dominios
        print("\n[2] Creando índice para dominios...")
        try:
            db.session.execute(text('''
                CREATE INDEX IF NOT EXISTS ix_dominios_remitentes_dominio
                ON dominios_remitentes (dominio)
            '''))
            db.session.commit()
            print("    OK - Índice creado")
        except Exception as e:
            print(f"    INFO: {e}")

        # 3. Agregar columna dominios_filtro a escaneos
        print("\n[3] Agregando columna dominios_filtro a escaneos...")
        try:
            db.session.execute(text('''
                ALTER TABLE escaneos ADD COLUMN dominios_filtro TEXT
            '''))
            db.session.commit()
            print("    OK - Columna agregada")
        except Exception as e:
            if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                print("    OK - Columna ya existe")
            else:
                print(f"    ERROR: {e}")

        # 4. Poblar dominios existentes desde archivos descargados
        print("\n[4] Detectando dominios desde archivos existentes...")
        try:
            from app.models import ArchivoDescargado, Escaneo, DominioRemitente, Compania
            import re

            # Obtener todos los archivos con remitente
            archivos = db.session.query(
                ArchivoDescargado.remitente,
                Escaneo.usuario_id
            ).join(Escaneo).filter(
                ArchivoDescargado.remitente.isnot(None)
            ).distinct().all()

            dominios_agregados = 0
            dominios_actualizados = 0

            for remitente, usuario_id in archivos:
                if not remitente:
                    continue

                # Extraer dominio
                match = re.search(r'@([a-zA-Z0-9.-]+)', remitente)
                if not match:
                    continue

                dominio = match.group(1).lower()

                # Ignorar dominios genéricos
                dominios_ignorar = {'gmail.com', 'hotmail.com', 'outlook.com', 'yahoo.com',
                                   'yahoo.com.ar', 'hotmail.com.ar', 'live.com', 'live.com.ar'}
                if dominio in dominios_ignorar:
                    continue

                # Contar PDFs de este dominio para este usuario
                cantidad = ArchivoDescargado.query.join(Escaneo).filter(
                    Escaneo.usuario_id == usuario_id,
                    ArchivoDescargado.remitente.like(f'%@{dominio}%')
                ).count()

                # Verificar si ya existe
                dom_existente = DominioRemitente.query.filter_by(
                    usuario_id=usuario_id,
                    dominio=dominio
                ).first()

                if dom_existente:
                    if dom_existente.cantidad_pdfs != cantidad:
                        dom_existente.cantidad_pdfs = cantidad
                        dominios_actualizados += 1
                else:
                    nombre = Compania.extraer_nombre_de_dominio(dominio)
                    nuevo_dom = DominioRemitente(
                        usuario_id=usuario_id,
                        dominio=dominio,
                        nombre_mostrar=nombre,
                        cantidad_pdfs=cantidad,
                        activo=True
                    )
                    db.session.add(nuevo_dom)
                    dominios_agregados += 1

            db.session.commit()
            print(f"    OK - {dominios_agregados} dominios nuevos, {dominios_actualizados} actualizados")

        except Exception as e:
            print(f"    ERROR: {e}")
            import traceback
            traceback.print_exc()

        print("\n" + "=" * 60)
        print("  MIGRACIÓN COMPLETADA")
        print("=" * 60)

if __name__ == '__main__':
    migrar()
