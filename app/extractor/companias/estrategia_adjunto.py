"""
Estrategia para compañías que envían pólizas como adjuntos PDF.
Es el método más común usado por la mayoría de aseguradoras.
"""

import re
from email.header import decode_header
from typing import List, Optional

from app.extractor.companias.estrategia_base import (
    EstrategiaExtraccion,
    ResultadoExtraccion,
    ConfigCompania
)


class EstrategiaAdjunto(EstrategiaExtraccion):
    """
    Extrae PDFs directamente de los adjuntos del correo.
    Usado por la mayoría de compañías aseguradoras.
    """

    def __init__(self, config: ConfigCompania):
        super().__init__(config)
        self.config_adj = config.config_especifica or {}

    def extraer_pdfs(self, mensaje_email, html_content: Optional[str] = None) -> List[ResultadoExtraccion]:
        """Extrae PDFs de los adjuntos del mensaje."""
        resultados = []

        # Configuración
        max_adjuntos = self.config.limites.get('max_adjuntos_por_correo', 10)
        extensiones = self.config_adj.get('extensiones_permitidas', ['.pdf'])
        excluir_nombres = self.config_adj.get('excluir_nombres', [])
        patron_nombre = self.config_adj.get('nombre_patron')
        tamano_max_mb = self.config.limites.get('tamano_max_pdf_mb', 25)

        adjuntos_procesados = 0

        for parte in mensaje_email.walk():
            if adjuntos_procesados >= max_adjuntos:
                break

            # Obtener nombre del archivo
            nombre_archivo = parte.get_filename()
            if not nombre_archivo:
                continue

            # Decodificar nombre si es necesario (puede venir en base64 o quoted-printable)
            nombre_archivo = self._decodificar_nombre(nombre_archivo)
            nombre_lower = nombre_archivo.lower()

            # Verificar extensión
            if not any(nombre_lower.endswith(ext.lower()) for ext in extensiones):
                continue

            # Verificar exclusiones por nombre
            if any(excl.lower() in nombre_lower for excl in excluir_nombres):
                resultados.append(ResultadoExtraccion(
                    exito=False,
                    error=f"Nombre excluido: {nombre_archivo}",
                    metadata={'nombre': nombre_archivo, 'motivo': 'nombre_excluido'}
                ))
                continue

            # Verificar patrón si existe
            if patron_nombre and not re.match(patron_nombre, nombre_archivo, re.IGNORECASE):
                continue

            # Extraer contenido
            try:
                contenido = parte.get_payload(decode=True)
            except Exception as e:
                resultados.append(ResultadoExtraccion(
                    exito=False,
                    error=f"Error extrayendo contenido: {str(e)}",
                    metadata={'nombre': nombre_archivo}
                ))
                continue

            if not contenido:
                continue

            # Verificar que sea PDF (magic bytes)
            if contenido[:4] != b'%PDF':
                resultados.append(ResultadoExtraccion(
                    exito=False,
                    error="No es un PDF válido (magic bytes)",
                    metadata={'nombre': nombre_archivo}
                ))
                continue

            # Verificar tamaño
            tamano_mb = len(contenido) / (1024 * 1024)
            if tamano_mb > tamano_max_mb:
                resultados.append(ResultadoExtraccion(
                    exito=False,
                    error=f"PDF muy grande: {tamano_mb:.1f}MB > {tamano_max_mb}MB",
                    metadata={'nombre': nombre_archivo, 'tamano_mb': tamano_mb}
                ))
                continue

            # Éxito
            resultados.append(ResultadoExtraccion(
                exito=True,
                contenido=contenido,
                nombre_sugerido=nombre_archivo,
                metadata={
                    'tamano_bytes': len(contenido),
                    'fuente': 'adjunto',
                    'compania': self.nombre_compania
                }
            ))
            adjuntos_procesados += 1

        return resultados

    def _decodificar_nombre(self, nombre: str) -> str:
        """Decodifica el nombre del archivo si viene codificado."""
        try:
            partes = decode_header(nombre)
            nombre_decodificado = ''
            for parte, encoding in partes:
                if isinstance(parte, bytes):
                    nombre_decodificado += parte.decode(encoding or 'utf-8', errors='replace')
                else:
                    nombre_decodificado += parte
            return nombre_decodificado
        except Exception:
            return nombre
