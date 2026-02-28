#!/usr/bin/env python
"""
Script de migración: Agregar salt a encriptación de credenciales Gmail.

Este script:
1. Agrega la columna encryption_salt a la tabla cuentas_gmail (si no existe)
2. Migra las credenciales existentes al nuevo formato con salt

IMPORTANTE:
- Hacer backup de la BD antes de ejecutar
- Ejecutar con la app configurada (ENCRYPTION_KEY disponible)

Uso:
    python scripts/migrar_encriptacion_salt.py
    python scripts/migrar_encriptacion_salt.py --dry-run  # Solo verificar
"""

import os
import sys
import argparse

# Agregar directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verificar_columna_existe(engine, tabla, columna):
    """Verifica si una columna existe en una tabla."""
    from sqlalchemy import inspect
    inspector = inspect(engine)
    columnas = [col['name'] for col in inspector.get_columns(tabla)]
    return columna in columnas


def agregar_columna_salt(db, engine):
    """Agrega la columna encryption_salt si no existe."""
    if verificar_columna_existe(engine, 'cuentas_gmail', 'encryption_salt'):
        print("[OK] Columna encryption_salt ya existe")
        return False

    print("[...] Agregando columna encryption_salt...")
    with engine.connect() as conn:
        conn.execute(db.text(
            "ALTER TABLE cuentas_gmail ADD COLUMN encryption_salt VARCHAR(64)"
        ))
        conn.commit()
    print("[OK] Columna encryption_salt agregada")
    return True


def migrar_cuentas(app, db, dry_run=False):
    """Migra las cuentas existentes al nuevo formato con salt."""
    from app.models import CuentaGmail

    with app.app_context():
        cuentas = CuentaGmail.query.filter(
            CuentaGmail.encryption_salt.is_(None)
        ).all()

        total = len(cuentas)
        if total == 0:
            print("[OK] No hay cuentas para migrar (todas usan salt)")
            return 0

        print(f"[...] Migrando {total} cuentas al nuevo formato...")

        migradas = 0
        errores = 0

        for cuenta in cuentas:
            try:
                if dry_run:
                    # Solo verificar que se puede desencriptar
                    _ = cuenta.obtener_contrasena_app()
                    print(f"  [DRY-RUN] {cuenta.correo_gmail} - OK (se puede migrar)")
                else:
                    # Migrar realmente
                    if cuenta.migrar_encriptacion():
                        db.session.commit()
                        print(f"  [OK] {cuenta.correo_gmail} migrada")
                        migradas += 1
            except Exception as e:
                errores += 1
                print(f"  [ERROR] {cuenta.correo_gmail}: {e}")
                if not dry_run:
                    db.session.rollback()

        if dry_run:
            print(f"\n[DRY-RUN] {total - errores} cuentas se pueden migrar, {errores} con errores")
        else:
            print(f"\n[OK] Migradas: {migradas}, Errores: {errores}")

        return migradas


def verificar_migracion(app, db):
    """Verifica el estado de la migración."""
    from app.models import CuentaGmail

    with app.app_context():
        total = CuentaGmail.query.count()
        con_salt = CuentaGmail.query.filter(
            CuentaGmail.encryption_salt.isnot(None)
        ).count()
        sin_salt = total - con_salt

        print("\n=== Estado de Migración ===")
        print(f"Total cuentas: {total}")
        print(f"Con salt (nuevo formato): {con_salt}")
        print(f"Sin salt (legacy): {sin_salt}")

        if sin_salt > 0:
            print(f"\n[!] Hay {sin_salt} cuentas pendientes de migrar")
            print("    Ejecutar: python scripts/migrar_encriptacion_salt.py")
        else:
            print("\n[OK] Todas las cuentas usan el nuevo formato seguro")


def main():
    parser = argparse.ArgumentParser(
        description='Migrar encriptación de credenciales Gmail a formato con salt'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Solo verificar, no hacer cambios'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Solo verificar estado de migración'
    )
    args = parser.parse_args()

    # Importar app después de configurar path
    from app import create_app, db

    print("=" * 60)
    print("MIGRACIÓN: Encriptación con Salt para Credenciales Gmail")
    print("=" * 60)

    app = create_app()

    with app.app_context():
        if args.verify:
            verificar_migracion(app, db)
            return

        if args.dry_run:
            print("[DRY-RUN] Modo simulación - no se harán cambios\n")

        # Paso 1: Agregar columna si no existe
        if not args.dry_run:
            agregar_columna_salt(db, db.engine)
        else:
            if verificar_columna_existe(db.engine, 'cuentas_gmail', 'encryption_salt'):
                print("[DRY-RUN] Columna encryption_salt ya existe")
            else:
                print("[DRY-RUN] Se agregaría columna encryption_salt")

        print()

        # Paso 2: Migrar cuentas existentes
        migrar_cuentas(app, db, dry_run=args.dry_run)

        print()

        # Paso 3: Verificar estado final
        if not args.dry_run:
            verificar_migracion(app, db)


if __name__ == '__main__':
    main()
