"""
Rutas del módulo API
"""

from flask import Blueprint

api_bp = Blueprint('api', __name__)

# Importar rutas de webhook
from app.api import whatsapp_webhook
