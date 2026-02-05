#!/usr/bin/env python
"""
Script de inicio del Portal de Seguros
Con diagnóstico de inicialización para detectar ventanas fantasma
"""

import os
import sys
import traceback
from datetime import datetime

# Archivo de log para diagnóstico
LOG_FILE = os.path.join(os.path.dirname(__file__), 'inicio_diagnostico.log')

def log(mensaje):
    """Registra mensaje en consola y archivo."""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    linea = f"[{timestamp}] {mensaje}"
    print(linea)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(linea + '\n')
    except:
        pass

def main():
    log("=" * 60)
    log("INICIO DE DIAGNOSTICO - Portal de Seguros")
    log("=" * 60)
    log(f"Python: {sys.version}")
    log(f"Ejecutable: {sys.executable}")
    log(f"Directorio: {os.getcwd()}")
    log(f"Archivo: {__file__}")
    log("-" * 60)

    # Paso 1: Importar Flask app
    log("[PASO 1] Importando aplicación Flask...")
    try:
        from app import create_app
        log("[PASO 1] OK - Módulo app importado")
    except Exception as e:
        log(f"[PASO 1] ERROR al importar app: {e}")
        traceback.print_exc()
        return False

    # Paso 2: Crear la aplicación
    log("[PASO 2] Creando instancia de Flask...")
    try:
        app = create_app()
        log("[PASO 2] OK - Aplicación creada")
    except Exception as e:
        log(f"[PASO 2] ERROR al crear app: {e}")
        traceback.print_exc()
        return False

    # Paso 3: Crear directorios
    log("[PASO 3] Verificando directorios...")
    try:
        archivos_dir = os.path.join(os.path.dirname(__file__), 'archivos_usuarios')
        if not os.path.exists(archivos_dir):
            os.makedirs(archivos_dir)
            log(f"[PASO 3] Directorio creado: {archivos_dir}")
        else:
            log(f"[PASO 3] OK - Directorio existe: {archivos_dir}")
    except Exception as e:
        log(f"[PASO 3] ERROR en directorios: {e}")
        traceback.print_exc()
        return False

    # Paso 4: Verificar extensiones cargadas
    log("[PASO 4] Verificando extensiones...")
    try:
        log(f"  - Blueprints: {list(app.blueprints.keys())}")
        log(f"  - Debug: {app.debug}")
        log("[PASO 4] OK - Extensiones verificadas")
    except Exception as e:
        log(f"[PASO 4] ERROR: {e}")

    log("-" * 60)
    log("DIAGNOSTICO COMPLETADO - Iniciando servidor...")
    log("-" * 60)

    print()
    print("=" * 50)
    print("  PORTAL DE SEGUROS")
    print("  Extractor de Pólizas")
    print("=" * 50)
    print()
    print("  Servidor iniciando en: http://127.0.0.1:5000")
    print()
    print("  Credenciales por defecto:")
    print("  Usuario: admin@empresa.com")
    print("  Contraseña: CambiarEnPrimerLogin123!")
    print()
    print("=" * 50)
    print()

    # Paso 5: Iniciar servidor
    log("[PASO 5] Iniciando servidor Flask...")
    try:
        app.run(
            host='127.0.0.1',
            port=5000,
            debug=False,  # Desactivado para evitar ventana fantasma del stat-reloader
            use_reloader=False
        )
    except Exception as e:
        log(f"[PASO 5] ERROR al iniciar servidor: {e}")
        traceback.print_exc()
        return False

    return True

if __name__ == '__main__':
    # Limpiar log anterior
    try:
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
    except:
        pass

    try:
        exito = main()
        if not exito:
            print("\n" + "=" * 50)
            print("  HUBO ERRORES - Revisa arriba")
            print("=" * 50)
            input("\nPresiona Enter para cerrar...")
    except KeyboardInterrupt:
        log("\nServidor detenido por el usuario (Ctrl+C)")
    except Exception as e:
        log(f"\nERROR FATAL: {e}")
        traceback.print_exc()
        print("\n" + "=" * 50)
        print("  ERROR FATAL - Revisa el log arriba")
        print("=" * 50)
        input("\nPresiona Enter para cerrar...")
