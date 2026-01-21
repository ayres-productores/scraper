#!/usr/bin/env python
"""
Script de inicio del Portal de Seguros
"""

import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    # Crear directorio de archivos si no existe
    archivos_dir = os.path.join(os.path.dirname(__file__), 'archivos_usuarios')
    if not os.path.exists(archivos_dir):
        os.makedirs(archivos_dir)

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

    app.run(
        host='127.0.0.1',
        port=5000,
        debug=True
    )
