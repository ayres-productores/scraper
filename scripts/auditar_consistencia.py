#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de Auditoría de Consistencia - Portal de Seguros

Detecta y opcionalmente repara inconsistencias entre la base de datos
y el filesystem (archivos PDF).

Uso:
    python scripts/auditar_consistencia.py          # Solo reportar
    python scripts/auditar_consistencia.py --fix    # Reportar y reparar
    python scripts/auditar_consistencia.py --verbose  # Más detalles

Auditorías realizadas:
    1. ArchivoRepositorio vs disco: detecta registros huérfanos en BD y archivos huérfanos en disco
    2. ArchivoDescargado vs ArchivoRepositorio: detecta referencias rotas
    3. Hashes duplicados: detecta el mismo PDF registrado múltiples veces
    4. Correos procesados vs archivos: detecta inconsistencias en contadores
"""

import argparse
import json
import os
import sys
from datetime import datetime
from collections import defaultdict

# Agregar el directorio raíz al path para importar la app
script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(script_dir)
sys.path.insert(0, root_dir)


def crear_app_contexto():
    """Crea el contexto de la aplicación Flask."""
    from app import create_app, db
    app = create_app()
    return app, db


def auditar_repositorio_vs_disco(db, config, verbose=False):
    """
    Audita ArchivoRepositorio vs archivos en disco.

    Detecta:
    - Registros en BD cuyo archivo no existe en disco (huérfanos BD)
    - Archivos en disco sin registro en BD (huérfanos disco)

    Returns:
        dict con resultados de la auditoría
    """
    from app.models import ArchivoRepositorio

    print("\n" + "="*60)
    print("AUDITORÍA 1: ArchivoRepositorio vs Disco")
    print("="*60)

    repositorio_dir = config.get('REPOSITORIO_ARCHIVOS', 'repositorio_archivos')

    resultados = {
        'huerfanos_bd': [],      # Registros sin archivo en disco
        'huerfanos_disco': [],   # Archivos sin registro en BD
        'ok': 0                  # Registros válidos
    }

    # Obtener todos los registros del repositorio
    registros = ArchivoRepositorio.query.all()
    rutas_en_bd = {}

    for reg in registros:
        ruta_completa = reg.obtener_ruta_fisica()
        rutas_en_bd[ruta_completa] = reg

        if os.path.exists(ruta_completa):
            resultados['ok'] += 1
        else:
            resultados['huerfanos_bd'].append({
                'id': reg.id,
                'hash': reg.hash_sha256,
                'ruta': ruta_completa,
                'nombre': reg.nombre_original,
                'referencias': reg.cantidad_referencias
            })

    # Buscar archivos en disco que no están en BD
    if os.path.exists(repositorio_dir):
        for root, dirs, files in os.walk(repositorio_dir):
            for filename in files:
                if filename.lower().endswith('.pdf'):
                    ruta_completa = os.path.join(root, filename)
                    if ruta_completa not in rutas_en_bd:
                        resultados['huerfanos_disco'].append({
                            'ruta': ruta_completa,
                            'nombre': filename,
                            'tamano': os.path.getsize(ruta_completa)
                        })

    # Mostrar resultados
    print(f"\n  Registros válidos: {resultados['ok']}")
    print(f"  Huérfanos en BD (archivo no existe): {len(resultados['huerfanos_bd'])}")
    print(f"  Huérfanos en disco (sin registro): {len(resultados['huerfanos_disco'])}")

    if verbose and resultados['huerfanos_bd']:
        print("\n  Huérfanos BD (primeros 10):")
        for item in resultados['huerfanos_bd'][:10]:
            print(f"    - ID:{item['id']} Hash:{item['hash'][:12]}... Refs:{item['referencias']}")

    if verbose and resultados['huerfanos_disco']:
        print("\n  Huérfanos disco (primeros 10):")
        for item in resultados['huerfanos_disco'][:10]:
            print(f"    - {item['nombre']} ({item['tamano']} bytes)")

    return resultados


def auditar_archivos_vs_repositorio(db, verbose=False):
    """
    Audita ArchivoDescargado vs ArchivoRepositorio.

    Detecta:
    - Archivos descargados que referencian un repositorio inexistente
    - Archivos con archivo_repo_id NULL (migración incompleta)

    Returns:
        dict con resultados
    """
    from app.models import ArchivoDescargado, ArchivoRepositorio

    print("\n" + "="*60)
    print("AUDITORÍA 2: ArchivoDescargado vs ArchivoRepositorio")
    print("="*60)

    resultados = {
        'referencias_rotas': [],    # archivo_repo_id apunta a registro inexistente
        'sin_referencia': [],       # archivo_repo_id es NULL
        'ok': 0
    }

    archivos = ArchivoDescargado.query.all()

    for archivo in archivos:
        if archivo.archivo_repo_id is None:
            resultados['sin_referencia'].append({
                'id': archivo.id,
                'id_documento': archivo.id_documento,
                'nombre': archivo.nombre_archivo,
                'hash': archivo.hash_archivo
            })
        else:
            repo = ArchivoRepositorio.query.get(archivo.archivo_repo_id)
            if repo is None:
                resultados['referencias_rotas'].append({
                    'id': archivo.id,
                    'id_documento': archivo.id_documento,
                    'nombre': archivo.nombre_archivo,
                    'archivo_repo_id': archivo.archivo_repo_id
                })
            else:
                resultados['ok'] += 1

    print(f"\n  Referencias válidas: {resultados['ok']}")
    print(f"  Referencias rotas (repo no existe): {len(resultados['referencias_rotas'])}")
    print(f"  Sin referencia (archivo_repo_id NULL): {len(resultados['sin_referencia'])}")

    if verbose and resultados['referencias_rotas']:
        print("\n  Referencias rotas (primeros 10):")
        for item in resultados['referencias_rotas'][:10]:
            print(f"    - {item['id_documento']}: repo_id={item['archivo_repo_id']} no existe")

    return resultados


def auditar_hashes_duplicados(db, verbose=False):
    """
    Detecta archivos con el mismo hash registrados múltiples veces.

    Esto puede indicar:
    - PDFs que llegaron por diferentes canales
    - Problemas en la deduplicación

    Returns:
        dict con resultados
    """
    from app.models import ArchivoDescargado
    from sqlalchemy import func

    print("\n" + "="*60)
    print("AUDITORÍA 3: Hashes Duplicados")
    print("="*60)

    resultados = {
        'duplicados': [],
        'total_archivos': 0,
        'hashes_unicos': 0
    }

    # Contar archivos por hash
    duplicados = db.session.query(
        ArchivoDescargado.hash_archivo,
        func.count(ArchivoDescargado.id).label('cantidad')
    ).group_by(
        ArchivoDescargado.hash_archivo
    ).having(
        func.count(ArchivoDescargado.id) > 1
    ).all()

    resultados['total_archivos'] = ArchivoDescargado.query.count()
    resultados['hashes_unicos'] = db.session.query(
        func.count(func.distinct(ArchivoDescargado.hash_archivo))
    ).scalar()

    for hash_archivo, cantidad in duplicados:
        archivos = ArchivoDescargado.query.filter_by(hash_archivo=hash_archivo).all()
        resultados['duplicados'].append({
            'hash': hash_archivo,
            'cantidad': cantidad,
            'archivos': [{
                'id': a.id,
                'id_documento': a.id_documento,
                'nombre': a.nombre_archivo,
                'fecha': a.fecha_descarga.isoformat() if a.fecha_descarga else None
            } for a in archivos]
        })

    print(f"\n  Total archivos: {resultados['total_archivos']}")
    print(f"  Hashes únicos: {resultados['hashes_unicos']}")
    print(f"  Grupos con duplicados: {len(resultados['duplicados'])}")

    if verbose and resultados['duplicados']:
        print("\n  Duplicados (primeros 5 grupos):")
        for grupo in resultados['duplicados'][:5]:
            print(f"    Hash {grupo['hash'][:12]}... ({grupo['cantidad']} copias):")
            for arch in grupo['archivos'][:3]:
                print(f"      - {arch['id_documento']}: {arch['nombre'][:40]}")

    return resultados


def auditar_correos_vs_archivos(db, verbose=False):
    """
    Audita consistencia entre correos procesados y archivos descargados.

    Detecta:
    - Correos marcados con tiene_pdfs=True pero sin archivos asociados
    - Contadores de pdfs_descargados inconsistentes

    Returns:
        dict con resultados
    """
    from app.models import CorreoProcesado, ArchivoDescargado

    print("\n" + "="*60)
    print("AUDITORÍA 4: Correos Procesados vs Archivos")
    print("="*60)

    resultados = {
        'correos_sin_archivos': [],  # tiene_pdfs=True pero no hay archivos
        'contadores_inconsistentes': [],
        'ok': 0
    }

    # Obtener correos que dicen tener PDFs
    correos_con_pdfs = CorreoProcesado.query.filter_by(tiene_pdfs=True).all()

    for correo in correos_con_pdfs:
        # Buscar archivos de este correo (por message_id en el asunto o remitente similar)
        # Nota: La relación no es directa, usamos heurísticas
        archivos_relacionados = ArchivoDescargado.query.filter(
            ArchivoDescargado.fecha_correo == correo.fecha_correo,
            ArchivoDescargado.remitente.like(f"%{correo.remitente[:20] if correo.remitente else ''}%")
        ).count() if correo.remitente else 0

        if archivos_relacionados == 0 and correo.pdfs_descargados > 0:
            resultados['correos_sin_archivos'].append({
                'id': correo.id,
                'message_id': correo.message_id[:50] if correo.message_id else None,
                'remitente': correo.remitente[:50] if correo.remitente else None,
                'pdfs_reportados': correo.pdfs_descargados,
                'fecha': correo.fecha_correo.isoformat() if correo.fecha_correo else None
            })
        else:
            resultados['ok'] += 1

    print(f"\n  Correos con PDFs verificados: {resultados['ok']}")
    print(f"  Correos sin archivos encontrados: {len(resultados['correos_sin_archivos'])}")

    if verbose and resultados['correos_sin_archivos']:
        print("\n  Correos sin archivos (primeros 10):")
        for item in resultados['correos_sin_archivos'][:10]:
            print(f"    - {item['remitente']}: {item['pdfs_reportados']} PDFs reportados")

    return resultados


def reparar_huerfanos_bd(db, huerfanos, verbose=False):
    """
    Repara huérfanos en BD eliminando los registros sin archivo.
    """
    from app.models import ArchivoRepositorio, ArchivoDescargado

    print("\n  Reparando huérfanos BD...")
    eliminados = 0

    for item in huerfanos:
        try:
            repo = ArchivoRepositorio.query.get(item['id'])
            if repo:
                # Primero eliminar archivos descargados que referencian este repo
                ArchivoDescargado.query.filter_by(archivo_repo_id=repo.id).delete()
                db.session.delete(repo)
                eliminados += 1
                if verbose:
                    print(f"    Eliminado: {item['hash'][:12]}...")
        except Exception as e:
            print(f"    Error eliminando {item['id']}: {e}")

    db.session.commit()
    print(f"  Eliminados {eliminados} registros huérfanos de BD")
    return eliminados


def reparar_huerfanos_disco(huerfanos, verbose=False):
    """
    Mueve archivos huérfanos a carpeta de revisión (no elimina).
    """
    import shutil

    print("\n  Moviendo huérfanos de disco a carpeta de revisión...")

    carpeta_revision = os.path.join(root_dir, 'huerfanos_para_revisar')
    os.makedirs(carpeta_revision, exist_ok=True)

    movidos = 0
    for item in huerfanos:
        try:
            origen = item['ruta']
            destino = os.path.join(carpeta_revision, item['nombre'])

            # Evitar sobrescribir
            contador = 1
            while os.path.exists(destino):
                nombre_base, ext = os.path.splitext(item['nombre'])
                destino = os.path.join(carpeta_revision, f"{nombre_base}_{contador}{ext}")
                contador += 1

            shutil.move(origen, destino)
            movidos += 1
            if verbose:
                print(f"    Movido: {item['nombre']}")
        except Exception as e:
            print(f"    Error moviendo {item['nombre']}: {e}")

    print(f"  Movidos {movidos} archivos a {carpeta_revision}")
    return movidos


def generar_reporte_json(resultados, output_path):
    """Genera un archivo JSON con el reporte completo."""
    reporte = {
        'timestamp': datetime.now().isoformat(),
        'version': '1.0',
        'resultados': resultados,
        'resumen': {
            'huerfanos_bd': len(resultados.get('repositorio_vs_disco', {}).get('huerfanos_bd', [])),
            'huerfanos_disco': len(resultados.get('repositorio_vs_disco', {}).get('huerfanos_disco', [])),
            'referencias_rotas': len(resultados.get('archivos_vs_repositorio', {}).get('referencias_rotas', [])),
            'hashes_duplicados': len(resultados.get('hashes_duplicados', {}).get('duplicados', [])),
        }
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nReporte guardado en: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Auditoría de consistencia BD <-> Filesystem',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/auditar_consistencia.py              # Solo auditar
  python scripts/auditar_consistencia.py --fix        # Auditar y reparar
  python scripts/auditar_consistencia.py -v           # Modo verbose
  python scripts/auditar_consistencia.py --fix -v     # Reparar con detalles
        """
    )
    parser.add_argument('--fix', action='store_true',
                        help='Reparar inconsistencias encontradas')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Mostrar detalles de cada inconsistencia')
    parser.add_argument('--json', type=str, metavar='FILE',
                        help='Guardar reporte en archivo JSON')

    args = parser.parse_args()

    print("="*60)
    print("AUDITORÍA DE CONSISTENCIA - PORTAL DE SEGUROS")
    print("="*60)
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Modo: {'REPARACIÓN' if args.fix else 'SOLO LECTURA'}")

    # Crear contexto de la aplicación
    app, db = crear_app_contexto()

    with app.app_context():
        resultados = {}

        # Auditoría 1: Repositorio vs Disco
        resultados['repositorio_vs_disco'] = auditar_repositorio_vs_disco(
            db, app.config, verbose=args.verbose
        )

        # Auditoría 2: Archivos vs Repositorio
        resultados['archivos_vs_repositorio'] = auditar_archivos_vs_repositorio(
            db, verbose=args.verbose
        )

        # Auditoría 3: Hashes duplicados
        resultados['hashes_duplicados'] = auditar_hashes_duplicados(
            db, verbose=args.verbose
        )

        # Auditoría 4: Correos vs Archivos
        resultados['correos_vs_archivos'] = auditar_correos_vs_archivos(
            db, verbose=args.verbose
        )

        # Reparaciones (si --fix)
        if args.fix:
            print("\n" + "="*60)
            print("REPARACIONES")
            print("="*60)

            huerfanos_bd = resultados['repositorio_vs_disco']['huerfanos_bd']
            huerfanos_disco = resultados['repositorio_vs_disco']['huerfanos_disco']

            if huerfanos_bd:
                respuesta = input(f"\n¿Eliminar {len(huerfanos_bd)} registros huérfanos de BD? [s/N]: ")
                if respuesta.lower() == 's':
                    reparar_huerfanos_bd(db, huerfanos_bd, verbose=args.verbose)

            if huerfanos_disco:
                respuesta = input(f"\n¿Mover {len(huerfanos_disco)} archivos huérfanos a carpeta de revisión? [s/N]: ")
                if respuesta.lower() == 's':
                    reparar_huerfanos_disco(huerfanos_disco, verbose=args.verbose)

        # Generar reporte JSON si se solicitó
        if args.json:
            generar_reporte_json(resultados, args.json)
        else:
            # Guardar reporte por defecto
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            json_path = os.path.join(root_dir, 'logs', f'auditoria_{timestamp}.json')
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            generar_reporte_json(resultados, json_path)

        # Resumen final
        print("\n" + "="*60)
        print("RESUMEN FINAL")
        print("="*60)

        total_problemas = (
            len(resultados['repositorio_vs_disco']['huerfanos_bd']) +
            len(resultados['repositorio_vs_disco']['huerfanos_disco']) +
            len(resultados['archivos_vs_repositorio']['referencias_rotas']) +
            len(resultados['archivos_vs_repositorio']['sin_referencia'])
        )

        if total_problemas == 0:
            print("\n  [OK] No se encontraron inconsistencias criticas")
        else:
            print(f"\n  [!] Se encontraron {total_problemas} inconsistencias")
            if not args.fix:
                print("    Ejecute con --fix para reparar")

        print()


if __name__ == '__main__':
    main()
