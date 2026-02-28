#!/usr/bin/env python
"""
Portal de Seguros - Servidor Principal
Accesible desde red local (LAN) y localhost.
"""

import os
import sys
import socket
import logging

def get_base_path():
    """Obtiene la ruta base, funciona tanto en desarrollo como en ejecutable."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_local_ip():
    """Obtiene la IP local de la maquina en la red."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def setup_environment():
    """Configura el entorno y crea directorios necesarios."""
    base_path = get_base_path()
    os.chdir(base_path)

    for folder in ['archivos_usuarios', 'uploads', 'downloads', 'logs']:
        folder_path = os.path.join(base_path, folder)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

    return base_path


def setup_logging(base_path):
    """Configura el sistema de logging."""
    log_format = '%(asctime)s [%(levelname)s] %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(os.path.join(base_path, 'logs', 'servidor.log'), encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


def main():
    """Funcion principal del servidor."""
    base_path = setup_environment()
    logger = setup_logging(base_path)
    local_ip = get_local_ip()
    port = 5000

    banner = f"""
{'=' * 60}
       PORTAL DE SEGUROS
       Extractor y CRM de Polizas
{'=' * 60}

  Directorio base: {base_path}

  ACCESO AL SISTEMA:
  {'-' * 40}
  Desde esta PC:     http://localhost:{port}
  Desde la red LAN:  http://{local_ip}:{port}
  {'-' * 40}

  Credenciales por defecto:
  Usuario:    admin@empresa.com
  Contrasena: CambiarEnPrimerLogin123!

  IMPORTANTE:
  - Asegurese de que el firewall permita conexiones al puerto {port}
  - No cierre esta ventana mientras el servidor este en uso

{'=' * 60}
  Presione Ctrl+C para detener el servidor
{'=' * 60}
"""
    print(banner)
    logger.info(f"Iniciando servidor en puerto {port}")

    from app import create_app
    app = create_app()

    logger.info(f"Blueprints cargados: {list(app.blueprints.keys())}")

    # Intentar usar waitress (servidor de produccion)
    try:
        from waitress import serve
        print("  [*] Iniciando servidor con Waitress (produccion)...")
        logger.info("Servidor Waitress iniciado")
        print()
        serve(app, host='0.0.0.0', port=port, threads=4)
    except ImportError:
        print("  [!] Waitress no instalado, usando servidor de desarrollo Flask")
        print("  [!] Para mejor rendimiento, instale: pip install waitress")
        logger.info("Servidor Flask (desarrollo) iniciado")
        print()
        app.run(
            host='0.0.0.0',
            port=port,
            debug=False,
            threaded=True
        )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  [*] Servidor detenido por el usuario")
        logging.info("Servidor detenido por el usuario")
    except Exception as e:
        print(f"\n  [ERROR] {e}")
        logging.error(f"Error: {e}")
        input("\n  Presione Enter para cerrar...")
