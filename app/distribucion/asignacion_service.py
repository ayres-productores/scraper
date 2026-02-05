"""
Servicio de Asignacion Inteligente con Extraccion Predictiva Mejorable.

Este servicio orquesta:
1. Extraccion de datos de PDFs con aprendizaje aplicado
2. Busqueda de clientes similares por documento/nombre
3. Creacion unificada de Cliente + Poliza
4. Registro de correcciones para entrenamiento del algoritmo
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

from flask import current_app
from flask_login import current_user

from app import db
from app.models import (
    Cliente, PolizaCliente, ArchivoDescargado, Compania,
    LogCorreccionExtraccion, Escaneo
)
from app.extractor.pdf_parser import ExtractorDatosPoliza
from app.extractor.aprendizaje import obtener_motor, registrar_lote_correcciones


class AsignacionInteligenteService:
    """
    Servicio que orquesta la asignacion inteligente de polizas.

    Proporciona metodos para:
    - Extraer datos de PDFs con formato estructurado
    - Buscar clientes similares existentes
    - Crear cliente y poliza en una sola operacion
    - Registrar correcciones para aprendizaje
    """

    def __init__(self, usuario_id: int):
        """
        Inicializa el servicio para un usuario especifico.

        Args:
            usuario_id: ID del usuario (broker) que realiza la asignacion
        """
        self.usuario_id = usuario_id
        self.motor = obtener_motor()
        self.extractor = ExtractorDatosPoliza()

    def extraer_datos_pdf(self, archivo_id: int) -> Dict:
        """
        Extrae datos del PDF aplicando aprendizaje previo.

        Args:
            archivo_id: ID del archivo en la base de datos

        Returns:
            Dict con datos estructurados o error
        """
        # Obtener archivo verificando pertenencia al usuario
        archivo = ArchivoDescargado.query.join(Escaneo).filter(
            ArchivoDescargado.id == archivo_id,
            Escaneo.usuario_id == self.usuario_id
        ).first()

        if not archivo:
            return {'error': 'Archivo no encontrado o sin permisos'}

        if not os.path.exists(archivo.ruta_archivo):
            return {'error': f'Archivo fisico no encontrado: {archivo.ruta_archivo}'}

        # Preparar info del archivo para metadata
        archivo_info = {
            'id': archivo.id,
            'nombre': archivo.nombre_archivo,
            'fecha': archivo.fecha_correo.isoformat() if archivo.fecha_correo else None,
            'remitente': archivo.remitente,
            'asunto': archivo.asunto
        }

        # Extraer con formato estructurado
        datos = self.extractor.extraer_datos_estructurado(archivo.ruta_archivo, archivo_info)

        if 'error' in datos:
            return datos

        # Agregar ID de compania sugerida si hay
        if archivo.compania_id:
            datos['compania']['id_sugerida'] = archivo.compania_id
        elif datos['compania']['detectada']:
            # Buscar compania por nombre
            compania = Compania.query.filter(
                Compania.clave == datos['compania']['detectada']
            ).first()
            if compania:
                datos['compania']['id_sugerida'] = compania.id

        # Buscar clientes similares
        datos['clientes_sugeridos'] = self._buscar_clientes_similares(datos.get('cliente', {}))

        # Marcar si hay cliente auto-seleccionable (documento coincide 100%)
        if datos['clientes_sugeridos']:
            mejor = datos['clientes_sugeridos'][0]
            if mejor.get('razon') == 'documento_coincide' and mejor.get('score', 0) >= 0.95:
                datos['cliente_autoseleccionado'] = mejor

        return datos

    def _buscar_clientes_similares(self, datos_cliente: Dict, limite: int = 5) -> List[Dict]:
        """
        Busca clientes existentes que coincidan con los datos extraidos.

        Args:
            datos_cliente: Diccionario con datos del cliente extraidos
            limite: Maximo de sugerencias a retornar

        Returns:
            Lista de clientes sugeridos ordenados por score
        """
        sugeridos = []

        # Obtener valores de los campos
        documento = datos_cliente.get('documento', {}).get('valor')
        nombre = datos_cliente.get('nombre', {}).get('valor')

        if documento:
            # Limpiar documento para busqueda
            doc_limpio = ''.join(c for c in str(documento) if c.isdigit())

            if len(doc_limpio) >= 7:  # DNI minimo
                # Buscar por documento exacto o similar
                clientes = Cliente.query.filter(
                    Cliente.usuario_id == self.usuario_id,
                    Cliente.activo == True
                ).all()

                for c in clientes:
                    if c.documento_identidad:
                        doc_cliente = ''.join(x for x in c.documento_identidad if x.isdigit())
                        if doc_limpio == doc_cliente:
                            sugeridos.append({
                                'id': c.id,
                                'nombre': c.nombre_completo,
                                'documento': c.documento_identidad,
                                'telefono': c.telefono_whatsapp,
                                'email': c.email,
                                'score': 1.0,
                                'razon': 'documento_coincide'
                            })

        # Buscar por nombre similar si no hay coincidencia por documento
        if not sugeridos and nombre:
            clientes = Cliente.query.filter(
                Cliente.usuario_id == self.usuario_id,
                Cliente.activo == True
            ).limit(200).all()  # Limitar para performance

            for c in clientes:
                ratio = SequenceMatcher(
                    None,
                    str(nombre).upper(),
                    c.nombre_completo.upper()
                ).ratio()

                if ratio > 0.75:
                    sugeridos.append({
                        'id': c.id,
                        'nombre': c.nombre_completo,
                        'documento': c.documento_identidad,
                        'telefono': c.telefono_whatsapp,
                        'email': c.email,
                        'score': ratio,
                        'razon': 'nombre_similar'
                    })

        # Ordenar por score y limitar
        return sorted(sugeridos, key=lambda x: x['score'], reverse=True)[:limite]

    def guardar_asignacion(self, datos: Dict) -> Dict:
        """
        Guarda cliente y poliza, registra correcciones.

        Este es el metodo principal que se llama al hacer submit del formulario.

        Args:
            datos: Diccionario con:
                - archivo_id: int
                - crear_cliente: bool
                - cliente_id: int (si no crear_cliente)
                - datos_cliente: dict (si crear_cliente)
                - datos_poliza: dict
                - correcciones: list
                - tiempo_edicion: int (segundos)

        Returns:
            Dict con resultado de la operacion
        """
        try:
            cliente = None
            cliente_creado = False

            # 1. Crear o seleccionar cliente
            if datos.get('crear_cliente'):
                cliente = self._crear_cliente(datos.get('datos_cliente', {}))
                cliente_creado = True
            else:
                cliente_id = datos.get('cliente_id')
                if cliente_id:
                    cliente = Cliente.query.filter_by(
                        id=cliente_id,
                        usuario_id=self.usuario_id
                    ).first()

                if not cliente:
                    return {'exito': False, 'error': 'Cliente no encontrado o sin permisos'}

            db.session.flush()  # Para obtener cliente.id si es nuevo

            # 2. Crear poliza
            poliza = self._crear_poliza(
                cliente.id,
                datos.get('datos_poliza', {}),
                datos.get('archivo_id')
            )

            db.session.flush()  # Para obtener poliza.id

            # 3. Registrar correcciones si las hay
            correcciones_registradas = 0
            correcciones = datos.get('correcciones', [])

            if correcciones:
                contexto = {
                    'archivo_id': datos.get('archivo_id'),
                    'usuario_id': self.usuario_id,
                    'poliza_id': poliza.id,
                    'cliente_id': cliente.id,
                    'compania': datos.get('datos_poliza', {}).get('compania_nombre'),
                    'tipo_seguro': datos.get('datos_poliza', {}).get('tipo_seguro'),
                    'tiempo_edicion': datos.get('tiempo_edicion', 0)
                }

                correcciones_registradas, _ = registrar_lote_correcciones(
                    correcciones,
                    contexto
                )

            # 4. Crear backup del PDF si existe
            archivo = ArchivoDescargado.query.get(datos.get('archivo_id'))
            if archivo and os.path.exists(archivo.ruta_archivo):
                self._crear_backup_pdf(archivo, poliza)

            # 5. Commit de todo
            db.session.commit()

            return {
                'exito': True,
                'cliente_id': cliente.id,
                'poliza_id': poliza.id,
                'cliente_creado': cliente_creado,
                'cliente_nombre': cliente.nombre_completo,
                'correcciones_registradas': correcciones_registradas,
                'mensaje': f'Poliza asignada correctamente a {cliente.nombre_completo}'
            }

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error en guardar_asignacion: {str(e)}")
            return {'exito': False, 'error': str(e)}

    def _crear_cliente(self, datos: Dict) -> Cliente:
        """
        Crea un nuevo cliente con los datos proporcionados.

        Args:
            datos: Diccionario con campos del cliente

        Returns:
            Instancia de Cliente creada
        """
        # Parsear nombre si viene junto
        nombre_completo = datos.get('nombre', '')
        nombre = nombre_completo
        apellido = ''

        if ',' in nombre_completo:
            # Formato: "Apellido, Nombre"
            partes = nombre_completo.split(',', 1)
            apellido = partes[0].strip()
            nombre = partes[1].strip() if len(partes) > 1 else ''
        elif ' ' in nombre_completo:
            # Formato: "Nombre Apellido"
            partes = nombre_completo.split(' ', 1)
            nombre = partes[0].strip()
            apellido = partes[1].strip() if len(partes) > 1 else ''

        cliente = Cliente(
            usuario_id=self.usuario_id,
            nombre=nombre,
            apellido=apellido,
            telefono_whatsapp=datos.get('telefono_whatsapp', ''),
            email=datos.get('email'),
            documento_identidad=datos.get('documento_identidad'),
            notas=datos.get('notas')
        )

        db.session.add(cliente)
        return cliente

    def _crear_poliza(self, cliente_id: int, datos: Dict, archivo_id: int) -> PolizaCliente:
        """
        Crea una nueva poliza con los datos proporcionados.

        Args:
            cliente_id: ID del cliente
            datos: Diccionario con campos de la poliza
            archivo_id: ID del archivo PDF origen

        Returns:
            Instancia de PolizaCliente creada
        """
        # Parsear fechas si vienen como string
        fecha_desde = datos.get('fecha_vigencia_desde')
        fecha_hasta = datos.get('fecha_vigencia_hasta')

        if isinstance(fecha_desde, str) and fecha_desde:
            try:
                fecha_desde = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            except ValueError:
                fecha_desde = None

        if isinstance(fecha_hasta, str) and fecha_hasta:
            try:
                fecha_hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            except ValueError:
                fecha_hasta = None

        poliza = PolizaCliente(
            cliente_id=cliente_id,
            archivo_id=archivo_id,
            compania_id=datos.get('compania_id'),
            numero_poliza=datos.get('numero_poliza'),
            tipo_seguro=datos.get('tipo_seguro'),
            fecha_vigencia_desde=fecha_desde,
            fecha_vigencia_hasta=fecha_hasta,
            prima_anual=datos.get('prima_anual'),
            suma_asegurada=datos.get('suma_asegurada'),
            deducible=datos.get('deducible'),

            # Datos del asegurado
            asegurado_nombre=datos.get('asegurado_nombre'),
            asegurado_documento=datos.get('asegurado_documento'),
            asegurado_direccion=datos.get('asegurado_direccion'),
            asegurado_telefono=datos.get('asegurado_telefono'),
            asegurado_email=datos.get('asegurado_email'),

            # Bien asegurado
            bien_asegurado_tipo=datos.get('bien_asegurado_tipo'),
            bien_asegurado_descripcion=datos.get('bien_asegurado_descripcion'),

            # Vehiculo
            vehiculo_marca=datos.get('vehiculo_marca'),
            vehiculo_modelo=datos.get('vehiculo_modelo'),
            vehiculo_anio=datos.get('vehiculo_anio'),
            vehiculo_patente=datos.get('vehiculo_patente'),
            vehiculo_chasis=datos.get('vehiculo_chasis'),
            vehiculo_motor=datos.get('vehiculo_motor'),
            vehiculo_color=datos.get('vehiculo_color'),
            vehiculo_uso=datos.get('vehiculo_uso'),

            # Inmueble
            inmueble_direccion=datos.get('inmueble_direccion'),
            inmueble_tipo=datos.get('inmueble_tipo'),
            inmueble_superficie=datos.get('inmueble_superficie'),

            # Inmobiliaria
            inmobiliaria_id=datos.get('inmobiliaria_id'),

            # Forma de pago
            forma_pago=datos.get('forma_pago'),
            cantidad_cuotas=datos.get('cantidad_cuotas'),

            # Productor
            productor_nombre=datos.get('productor_nombre'),
            productor_telefono=datos.get('productor_telefono'),
            productor_email=datos.get('productor_email'),

            # Notas
            notas=datos.get('notas'),

            # Metadatos de extraccion
            datos_extraidos=datos.get('datos_extraidos_json'),
            confianza_extraccion=datos.get('confianza_extraccion'),
            requiere_revision=datos.get('requiere_revision', False),
            fecha_extraccion=datetime.utcnow(),

            # Estado inicial
            estado='activa',
            estado_confirmacion='pendiente'
        )

        db.session.add(poliza)
        return poliza

    def _crear_backup_pdf(self, archivo: ArchivoDescargado, poliza: PolizaCliente) -> bool:
        """
        Crea una copia de respaldo del PDF en la carpeta de backups.

        Args:
            archivo: Archivo original
            poliza: Poliza creada

        Returns:
            True si el backup fue exitoso
        """
        try:
            import shutil

            # Directorio de backups
            backup_dir = os.path.join(
                current_app.config.get('UPLOAD_FOLDER', 'uploads'),
                'backups',
                str(self.usuario_id)
            )
            os.makedirs(backup_dir, exist_ok=True)

            # Nombre del backup
            fecha_str = datetime.now().strftime('%Y%m%d')
            nombre_backup = f"poliza_{poliza.id}_{fecha_str}_{archivo.nombre_archivo}"
            ruta_backup = os.path.join(backup_dir, nombre_backup)

            # Copiar archivo
            shutil.copy2(archivo.ruta_archivo, ruta_backup)

            # Actualizar poliza con ruta del backup
            poliza.ruta_pdf_backup = ruta_backup
            poliza.fecha_backup = datetime.utcnow()

            return True

        except Exception as e:
            current_app.logger.warning(f"Error creando backup de PDF: {e}")
            return False


def obtener_servicio_asignacion(usuario_id: int = None) -> AsignacionInteligenteService:
    """
    Factory para obtener una instancia del servicio.

    Args:
        usuario_id: ID del usuario. Si no se proporciona, usa current_user.

    Returns:
        Instancia de AsignacionInteligenteService
    """
    if usuario_id is None:
        usuario_id = current_user.id
    return AsignacionInteligenteService(usuario_id)
