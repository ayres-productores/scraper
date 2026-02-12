"""
Estrategia para compañías que envían enlaces de descarga en el HTML del correo.
Ejemplo: Mercantil Andina envía emails con botones/enlaces para descargar la póliza.
"""

import re
import requests
from typing import List, Optional, Tuple

from app.extractor.companias.estrategia_base import (
    EstrategiaExtraccion,
    ResultadoExtraccion,
    ConfigCompania
)


class EstrategiaEnlaceHTML(EstrategiaExtraccion):
    """
    Extrae PDFs descargándolos desde enlaces en el cuerpo HTML del correo.
    """

    def __init__(self, config: ConfigCompania):
        super().__init__(config)
        self.config_enl = config.config_especifica or {}

    def extraer_pdfs(self, mensaje_email, html_content: Optional[str] = None) -> List[ResultadoExtraccion]:
        """Extrae PDFs desde enlaces en el HTML."""
        resultados = []

        # Si no viene el HTML, buscarlo en el mensaje
        if not html_content:
            html_content = self._extraer_html_del_mensaje(mensaje_email)

        if not html_content:
            return [ResultadoExtraccion(
                exito=False,
                error="No hay contenido HTML en el correo",
                metadata={'compania': self.nombre_compania}
            )]

        # Extraer enlaces de descarga
        enlaces = self._extraer_enlaces(html_content)

        if not enlaces:
            return [ResultadoExtraccion(
                exito=False,
                error="No se encontraron enlaces de descarga",
                metadata={'compania': self.nombre_compania}
            )]

        # Configuración
        max_enlaces = self.config_enl.get('max_enlaces_por_correo', 3)
        timeout = self.config_enl.get('timeout_descarga_segundos', 30)
        tamano_max_mb = self.config.limites.get('tamano_max_pdf_mb', 25)

        for idx, url in enumerate(enlaces[:max_enlaces]):
            contenido, error = self._descargar_pdf(url, timeout)

            if contenido:
                # Verificar tamaño
                tamano_mb = len(contenido) / (1024 * 1024)
                if tamano_mb > tamano_max_mb:
                    resultados.append(ResultadoExtraccion(
                        exito=False,
                        error=f"PDF muy grande: {tamano_mb:.1f}MB > {tamano_max_mb}MB",
                        metadata={'url': url, 'tamano_mb': tamano_mb}
                    ))
                    continue

                resultados.append(ResultadoExtraccion(
                    exito=True,
                    contenido=contenido,
                    nombre_sugerido=f"poliza_{self.id_compania}_{idx + 1}.pdf",
                    metadata={
                        'url': url,
                        'fuente': 'enlace_html',
                        'tamano_bytes': len(contenido),
                        'compania': self.nombre_compania
                    }
                ))
            else:
                resultados.append(ResultadoExtraccion(
                    exito=False,
                    error=error,
                    metadata={'url': url, 'compania': self.nombre_compania}
                ))

        return resultados

    def _extraer_html_del_mensaje(self, mensaje_email) -> Optional[str]:
        """Busca el contenido HTML en las partes del mensaje."""
        for parte in mensaje_email.walk():
            if parte.get_content_type() == 'text/html':
                payload = parte.get_payload(decode=True)
                if payload:
                    # Intentar detectar encoding
                    charset = parte.get_content_charset() or 'utf-8'
                    try:
                        return payload.decode(charset, errors='replace')
                    except (LookupError, UnicodeDecodeError):
                        return payload.decode('utf-8', errors='replace')
        return None

    def _extraer_enlaces(self, html_content: str) -> List[str]:
        """Extrae URLs de descarga del HTML."""
        enlaces_prioritarios = []  # Coinciden con patrón específico
        enlaces_secundarios = []   # Coinciden con palabras clave

        patron_url = self.config_enl.get('patron_url')
        texto_boton = self.config_enl.get('texto_boton', ['descarga', 'download'])
        excluir_urls = self.config_enl.get('excluir_urls', [])

        # Buscar todos los <a href="...">contenido</a>
        patron_href = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
        matches = re.findall(patron_href, html_content, re.IGNORECASE | re.DOTALL)

        for url, contenido_interno in matches:
            url_lower = url.lower()

            # Excluir URLs no deseadas
            if any(excl.lower() in url_lower for excl in excluir_urls):
                continue

            # Solo URLs HTTP/HTTPS
            if not url.startswith('http'):
                continue

            # Extraer texto del enlace (puede incluir <img alt="...">)
            texto_alt = re.search(r'alt=["\']([^"\']+)["\']', contenido_interno)
            texto = texto_alt.group(1) if texto_alt else contenido_interno
            texto_limpio = re.sub(r'<[^>]+>', '', texto).strip().lower()

            # Prioridad 1: Coincide con patrón específico de la compañía
            if patron_url and re.search(patron_url, url, re.IGNORECASE):
                enlaces_prioritarios.append(url)
                continue

            # Prioridad 2: Texto del enlace contiene palabras clave
            if any(palabra.lower() in texto_limpio or palabra.lower() in url_lower
                   for palabra in texto_boton):
                enlaces_secundarios.append(url)

        # Retornar prioritarios primero, luego secundarios
        return enlaces_prioritarios + enlaces_secundarios

    def _descargar_pdf(self, url: str, timeout: int) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Descarga un PDF desde una URL.

        Returns:
            Tuple (contenido_bytes, error_mensaje)
        """
        try:
            # Headers para simular navegador
            headers_base = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/pdf,*/*',
                'Accept-Language': 'es-AR,es;q=0.9,en;q=0.8',
            }
            headers_extra = self.config_enl.get('headers_adicionales', {})
            headers = {**headers_base, **headers_extra}

            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                verify=True
            )

            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '').lower()

                # Verificar que sea PDF por Content-Type O magic bytes
                if 'pdf' in content_type or response.content[:4] == b'%PDF':
                    return response.content, None
                else:
                    return None, f"No es PDF (Content-Type: {content_type})"

            elif response.status_code == 404:
                return None, "Enlace expirado o no encontrado (404)"
            elif response.status_code == 403:
                return None, "Acceso denegado (403)"
            else:
                return None, f"Error HTTP {response.status_code}"

        except requests.exceptions.Timeout:
            return None, f"Timeout al descargar ({timeout}s)"
        except requests.exceptions.SSLError as e:
            return None, f"Error SSL: {str(e)}"
        except requests.exceptions.ConnectionError as e:
            return None, f"Error de conexión: {str(e)}"
        except requests.exceptions.RequestException as e:
            return None, f"Error de request: {str(e)}"
        except Exception as e:
            return None, f"Error inesperado: {str(e)}"
