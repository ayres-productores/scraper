# -*- coding: utf-8 -*-
"""
Verificador de Duplicados de Pólizas
====================================
Verifica duplicados en:
1. Carpeta de descargas (archivos_usuarios/)
2. Base de datos (archivos_descargados, polizas_cliente)
3. Carpeta de backup (polizas_backup/)

Se ejecuta automáticamente al finalizar cada escaneo.
"""

import os
import hashlib
from collections import defaultdict
from datetime import datetime
from flask import current_app
from sqlalchemy import func


class VerificadorDuplicados:
    """Verifica y reporta duplicados de pólizas en el sistema."""

    def __init__(self, db_session=None, logger=None):
        """
        Inicializa el verificador.

        Args:
            db_session: Sesión de SQLAlchemy (opcional, usa db.session si no se provee)
            logger: Función de logging (opcional)
        """
        self.db_session = db_session
        self.logger = logger or print
        self.resultados = {
            'duplicados_descargas': [],
            'duplicados_bd': [],
            'duplicados_backup': [],
            'duplicados_cruzados': [],
            'total_duplicados': 0,
            'fecha_verificacion': None
        }

    def log(self, mensaje, nivel='info'):
        """Registra un mensaje."""
        if callable(self.logger):
            self.logger(f"[Verificador] {mensaje}")

    def calcular_hash(self, ruta_archivo):
        """Calcula el hash SHA-256 de un archivo."""
        try:
            with open(ruta_archivo, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            self.log(f"Error calculando hash de {ruta_archivo}: {e}", 'error')
            return None

    def verificar_duplicados_descargas(self, carpeta_descargas=None):
        """
        Verifica duplicados en la carpeta de descargas.

        Detecta:
        - Archivos con mismo hash (contenido idéntico)
        - Archivos con nombre similar (posibles duplicados)
        """
        if carpeta_descargas is None:
            carpeta_descargas = current_app.config.get('UPLOAD_FOLDER', 'archivos_usuarios')

        if not os.path.exists(carpeta_descargas):
            self.log(f"Carpeta de descargas no existe: {carpeta_descargas}")
            return []

        duplicados = []
        archivos_por_hash = defaultdict(list)

        # Recorrer todos los archivos PDF
        for root, dirs, files in os.walk(carpeta_descargas):
            for archivo in files:
                if archivo.lower().endswith('.pdf'):
                    ruta = os.path.join(root, archivo)
                    hash_archivo = self.calcular_hash(ruta)
                    if hash_archivo:
                        archivos_por_hash[hash_archivo].append({
                            'ruta': ruta,
                            'nombre': archivo,
                            'tamaño': os.path.getsize(ruta)
                        })

        # Identificar duplicados (más de un archivo con mismo hash)
        for hash_val, archivos in archivos_por_hash.items():
            if len(archivos) > 1:
                duplicados.append({
                    'tipo': 'hash_identico',
                    'hash': hash_val[:16] + '...',
                    'cantidad': len(archivos),
                    'archivos': archivos,
                    'ubicacion': 'descargas'
                })

        self.resultados['duplicados_descargas'] = duplicados
        return duplicados

    def verificar_duplicados_bd(self):
        """
        Verifica duplicados en la base de datos.

        Detecta:
        - Archivos con mismo hash en archivos_descargados
        - Pólizas con mismo número en polizas_cliente
        - Archivos huérfanos (sin póliza asignada)
        """
        from app.models import ArchivoDescargado, PolizaCliente

        duplicados = []

        # 1. Verificar hashes duplicados en archivos_descargados
        try:
            hashes_duplicados = self.db_session.query(
                ArchivoDescargado.hash_archivo,
                func.count(ArchivoDescargado.id).label('cantidad')
            ).filter(
                ArchivoDescargado.hash_archivo.isnot(None)
            ).group_by(
                ArchivoDescargado.hash_archivo
            ).having(
                func.count(ArchivoDescargado.id) > 1
            ).all()

            for hash_val, cantidad in hashes_duplicados:
                archivos = ArchivoDescargado.query.filter_by(hash_archivo=hash_val).all()
                duplicados.append({
                    'tipo': 'hash_duplicado_bd',
                    'hash': hash_val[:16] + '...' if hash_val else 'N/A',
                    'cantidad': cantidad,
                    'archivos': [{
                        'id': a.id,
                        'id_documento': a.id_documento,
                        'nombre': a.nombre_archivo,
                        'fecha': a.fecha_descarga.isoformat() if a.fecha_descarga else None
                    } for a in archivos],
                    'ubicacion': 'base_datos'
                })
        except Exception as e:
            self.log(f"Error verificando hashes en BD: {e}", 'error')

        # 2. Verificar números de póliza duplicados en polizas_cliente
        try:
            polizas_duplicadas = self.db_session.query(
                PolizaCliente.numero_poliza,
                func.count(PolizaCliente.id).label('cantidad')
            ).filter(
                PolizaCliente.numero_poliza.isnot(None),
                PolizaCliente.numero_poliza != ''
            ).group_by(
                PolizaCliente.numero_poliza
            ).having(
                func.count(PolizaCliente.id) > 1
            ).all()

            for numero, cantidad in polizas_duplicadas:
                polizas = PolizaCliente.query.filter_by(numero_poliza=numero).all()
                duplicados.append({
                    'tipo': 'numero_poliza_duplicado',
                    'numero_poliza': numero,
                    'cantidad': cantidad,
                    'polizas': [{
                        'id': p.id,
                        'cliente_id': p.cliente_id,
                        'compania': p.compania,
                        'tipo_seguro': p.tipo_seguro,
                        'vigencia_hasta': p.fecha_vigencia_hasta.isoformat() if p.fecha_vigencia_hasta else None
                    } for p in polizas],
                    'ubicacion': 'base_datos'
                })
        except Exception as e:
            self.log(f"Error verificando pólizas en BD: {e}", 'error')

        self.resultados['duplicados_bd'] = duplicados
        return duplicados

    def verificar_duplicados_backup(self, carpeta_backup=None):
        """
        Verifica duplicados en la carpeta de backup.

        Detecta:
        - Archivos con mismo hash en diferentes carpetas de cliente
        - Posibles pólizas duplicadas asignadas a diferentes clientes
        """
        if carpeta_backup is None:
            carpeta_backup = current_app.config.get('POLIZAS_BACKUP_FOLDER', 'polizas_backup')

        if not os.path.exists(carpeta_backup):
            self.log(f"Carpeta de backup no existe: {carpeta_backup}")
            return []

        duplicados = []
        archivos_por_hash = defaultdict(list)

        # Recorrer todos los archivos en backup
        for root, dirs, files in os.walk(carpeta_backup):
            for archivo in files:
                if archivo.lower().endswith('.pdf'):
                    ruta = os.path.join(root, archivo)
                    hash_archivo = self.calcular_hash(ruta)

                    # Extraer ID de cliente de la ruta
                    partes = root.replace(carpeta_backup, '').strip(os.sep).split(os.sep)
                    cliente_id = partes[0] if partes else 'desconocido'

                    if hash_archivo:
                        archivos_por_hash[hash_archivo].append({
                            'ruta': ruta,
                            'nombre': archivo,
                            'cliente_id': cliente_id,
                            'tamaño': os.path.getsize(ruta)
                        })

        # Identificar duplicados en backup
        for hash_val, archivos in archivos_por_hash.items():
            if len(archivos) > 1:
                # Verificar si están en diferentes clientes
                clientes = set(a['cliente_id'] for a in archivos)
                duplicados.append({
                    'tipo': 'hash_identico_backup',
                    'hash': hash_val[:16] + '...',
                    'cantidad': len(archivos),
                    'clientes_afectados': len(clientes),
                    'archivos': archivos,
                    'ubicacion': 'backup',
                    'alerta': 'alta' if len(clientes) > 1 else 'media'
                })

        self.resultados['duplicados_backup'] = duplicados
        return duplicados

    def verificar_duplicados_cruzados(self, carpeta_descargas=None, carpeta_backup=None):
        """
        Verifica duplicados entre descargas, backup y BD.

        Detecta:
        - Mismo archivo en descargas y backup
        - Archivos en disco sin registro en BD
        - Registros en BD sin archivo en disco
        """
        from app.models import ArchivoDescargado

        if carpeta_descargas is None:
            carpeta_descargas = current_app.config.get('UPLOAD_FOLDER', 'archivos_usuarios')
        if carpeta_backup is None:
            carpeta_backup = current_app.config.get('POLIZAS_BACKUP_FOLDER', 'polizas_backup')

        duplicados = []

        # Obtener hashes de BD
        hashes_bd = set()
        try:
            registros = ArchivoDescargado.query.filter(
                ArchivoDescargado.hash_archivo.isnot(None)
            ).with_entities(ArchivoDescargado.hash_archivo).all()
            hashes_bd = set(r[0] for r in registros)
        except Exception as e:
            self.log(f"Error obteniendo hashes de BD: {e}", 'error')

        # Obtener hashes de descargas
        hashes_descargas = {}
        if os.path.exists(carpeta_descargas):
            for root, dirs, files in os.walk(carpeta_descargas):
                for archivo in files:
                    if archivo.lower().endswith('.pdf'):
                        ruta = os.path.join(root, archivo)
                        hash_val = self.calcular_hash(ruta)
                        if hash_val:
                            hashes_descargas[hash_val] = ruta

        # Obtener hashes de backup
        hashes_backup = {}
        if os.path.exists(carpeta_backup):
            for root, dirs, files in os.walk(carpeta_backup):
                for archivo in files:
                    if archivo.lower().endswith('.pdf'):
                        ruta = os.path.join(root, archivo)
                        hash_val = self.calcular_hash(ruta)
                        if hash_val:
                            hashes_backup[hash_val] = ruta

        # Encontrar archivos en descargas que también están en backup
        comunes = set(hashes_descargas.keys()) & set(hashes_backup.keys())
        for hash_val in comunes:
            duplicados.append({
                'tipo': 'duplicado_descarga_backup',
                'hash': hash_val[:16] + '...',
                'ruta_descarga': hashes_descargas[hash_val],
                'ruta_backup': hashes_backup[hash_val],
                'accion_sugerida': 'Eliminar de descargas (ya está en backup)'
            })

        # Encontrar archivos en disco sin registro en BD
        hashes_disco = set(hashes_descargas.keys()) | set(hashes_backup.keys())
        sin_registro = hashes_disco - hashes_bd
        if sin_registro:
            archivos_sin_registro = []
            for hash_val in list(sin_registro)[:10]:  # Limitar a 10
                if hash_val in hashes_descargas:
                    archivos_sin_registro.append(hashes_descargas[hash_val])
                elif hash_val in hashes_backup:
                    archivos_sin_registro.append(hashes_backup[hash_val])

            if archivos_sin_registro:
                duplicados.append({
                    'tipo': 'archivos_sin_registro_bd',
                    'cantidad': len(sin_registro),
                    'ejemplos': archivos_sin_registro,
                    'accion_sugerida': 'Revisar y registrar o eliminar'
                })

        self.resultados['duplicados_cruzados'] = duplicados
        return duplicados

    def ejecutar_verificacion_completa(self, carpeta_descargas=None, carpeta_backup=None):
        """
        Ejecuta verificación completa de duplicados.

        Returns:
            dict: Resultados de la verificación
        """
        self.log("Iniciando verificación de duplicados...")
        self.resultados['fecha_verificacion'] = datetime.now().isoformat()

        # 1. Verificar descargas
        self.log("Verificando carpeta de descargas...")
        dup_descargas = self.verificar_duplicados_descargas(carpeta_descargas)
        self.log(f"  → {len(dup_descargas)} grupos de duplicados en descargas")

        # 2. Verificar BD
        self.log("Verificando base de datos...")
        dup_bd = self.verificar_duplicados_bd()
        self.log(f"  → {len(dup_bd)} grupos de duplicados en BD")

        # 3. Verificar backup
        self.log("Verificando carpeta de backup...")
        dup_backup = self.verificar_duplicados_backup(carpeta_backup)
        self.log(f"  → {len(dup_backup)} grupos de duplicados en backup")

        # 4. Verificar cruzados
        self.log("Verificando duplicados cruzados...")
        dup_cruzados = self.verificar_duplicados_cruzados(carpeta_descargas, carpeta_backup)
        self.log(f"  → {len(dup_cruzados)} problemas cruzados detectados")

        # Calcular total
        self.resultados['total_duplicados'] = (
            len(dup_descargas) + len(dup_bd) + len(dup_backup) + len(dup_cruzados)
        )

        self.log(f"Verificación completada. Total: {self.resultados['total_duplicados']} problemas")

        return self.resultados

    def generar_reporte(self):
        """Genera un reporte legible de los duplicados encontrados."""
        lineas = []
        lineas.append("=" * 60)
        lineas.append("REPORTE DE DUPLICADOS DE PÓLIZAS")
        lineas.append(f"Fecha: {self.resultados.get('fecha_verificacion', 'N/A')}")
        lineas.append("=" * 60)

        # Resumen
        lineas.append(f"\nTOTAL DE PROBLEMAS: {self.resultados['total_duplicados']}")
        lineas.append(f"  - En descargas: {len(self.resultados['duplicados_descargas'])}")
        lineas.append(f"  - En base de datos: {len(self.resultados['duplicados_bd'])}")
        lineas.append(f"  - En backup: {len(self.resultados['duplicados_backup'])}")
        lineas.append(f"  - Cruzados: {len(self.resultados['duplicados_cruzados'])}")

        # Detalle de duplicados en descargas
        if self.resultados['duplicados_descargas']:
            lineas.append("\n--- DUPLICADOS EN DESCARGAS ---")
            for dup in self.resultados['duplicados_descargas']:
                lineas.append(f"\n  Hash: {dup['hash']}")
                lineas.append(f"  Cantidad: {dup['cantidad']} archivos")
                for arch in dup['archivos'][:3]:
                    lineas.append(f"    - {arch['nombre']}")

        # Detalle de duplicados en BD
        if self.resultados['duplicados_bd']:
            lineas.append("\n--- DUPLICADOS EN BASE DE DATOS ---")
            for dup in self.resultados['duplicados_bd']:
                if dup['tipo'] == 'numero_poliza_duplicado':
                    lineas.append(f"\n  Póliza #{dup['numero_poliza']}: {dup['cantidad']} registros")
                    for pol in dup.get('polizas', [])[:3]:
                        lineas.append(f"    - ID:{pol['id']} Cliente:{pol['cliente_id']} ({pol.get('compania', 'N/A')})")
                else:
                    lineas.append(f"\n  Hash duplicado: {dup['hash']}")
                    lineas.append(f"  Cantidad: {dup['cantidad']} archivos")

        # Detalle de duplicados en backup
        if self.resultados['duplicados_backup']:
            lineas.append("\n--- DUPLICADOS EN BACKUP ---")
            for dup in self.resultados['duplicados_backup']:
                lineas.append(f"\n  Hash: {dup['hash']}")
                lineas.append(f"  Cantidad: {dup['cantidad']} archivos en {dup['clientes_afectados']} clientes")
                lineas.append(f"  Alerta: {dup.get('alerta', 'N/A')}")

        # Detalle de problemas cruzados
        if self.resultados['duplicados_cruzados']:
            lineas.append("\n--- PROBLEMAS CRUZADOS ---")
            for dup in self.resultados['duplicados_cruzados']:
                lineas.append(f"\n  Tipo: {dup['tipo']}")
                if 'accion_sugerida' in dup:
                    lineas.append(f"  Acción sugerida: {dup['accion_sugerida']}")
                if 'cantidad' in dup:
                    lineas.append(f"  Cantidad: {dup['cantidad']}")

        lineas.append("\n" + "=" * 60)

        return "\n".join(lineas)


def verificar_duplicados_post_escaneo(escaneo_id=None, db_session=None, logger=None):
    """
    Función de conveniencia para ejecutar verificación después de un escaneo.

    Args:
        escaneo_id: ID del escaneo (para log)
        db_session: Sesión de SQLAlchemy
        logger: Función de logging

    Returns:
        dict: Resultados de la verificación
    """
    from flask import current_app
    from app import db

    session = db_session or db.session

    verificador = VerificadorDuplicados(db_session=session, logger=logger)
    resultados = verificador.ejecutar_verificacion_completa()

    # Generar reporte si hay duplicados
    if resultados['total_duplicados'] > 0:
        reporte = verificador.generar_reporte()
        if logger:
            logger(reporte)

        # Guardar reporte en log de escaneo si se proporciona ID
        if escaneo_id:
            from app.models import LogEscaneo
            try:
                log = LogEscaneo(
                    escaneo_id=escaneo_id,
                    mensaje=f"Verificación de duplicados: {resultados['total_duplicados']} problemas encontrados",
                    tipo='warning' if resultados['total_duplicados'] > 0 else 'info',
                    datos_extra=resultados
                )
                session.add(log)
                session.commit()
            except Exception as e:
                if logger:
                    logger(f"Error guardando log de verificación: {e}")

    return resultados
