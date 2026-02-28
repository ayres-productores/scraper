"""
Módulo Representante - Vista especializada para rol collaborator.

Este módulo proporciona una interfaz para que los representantes
visualicen todas las pólizas del sistema y gestionen el contacto
con los clientes.
"""

from flask import Blueprint

representante_bp = Blueprint('representante', __name__, url_prefix='/representante')

from app.representante import routes  # noqa: E402, F401
