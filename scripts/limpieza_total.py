"""
Limpieza total para testing.
Borra TODOS los datos de escaneos del sistema.
"""

import os
import sys
import shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    print("=" * 70)
    print("LIMPIEZA TOTAL DEL SISTEMA")
    print("=" * 70)

    from app import create_app, db
    from app.models import (
        ArchivoDescargado, ArchivoRepositorio, CorreoProcesado,
        Escaneo, LogEscaneo, HistorialEscaneoCarpeta, RangoCobertura,
        RegistroAnalisisPDF, DominioRemitente, PolizaCliente, Cliente
    )

    app = create_app()

    with app.app_context():
        print("\n[1] BORRANDO REGISTROS DE BASE DE DATOS...")

        # Orden correcto para respetar FK
        tablas = [
            ('RegistroAnalisisPDF', RegistroAnalisisPDF),
            ('PolizaCliente', PolizaCliente),
            ('LogEscaneo', LogEscaneo),
            ('HistorialEscaneoCarpeta', HistorialEscaneoCarpeta),
            ('RangoCobertura', RangoCobertura),
            ('ArchivoDescargado', ArchivoDescargado),
            ('CorreoProcesado', CorreoProcesado),
            ('DominioRemitente', DominioRemitente),
            ('ArchivoRepositorio', ArchivoRepositorio),
            ('Escaneo', Escaneo),
            ('Cliente', Cliente),
        ]

        for nombre, modelo in tablas:
            try:
                count = modelo.query.delete()
                db.session.commit()
                print(f"    {nombre}: {count} registros eliminados")
            except Exception as e:
                db.session.rollback()
                print(f"    {nombre}: ERROR - {e}")

        print("\n[2] BORRANDO ARCHIVOS FISICOS...")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # repositorio_archivos
        repo_dir = os.path.join(base_dir, 'repositorio_archivos')
        if os.path.exists(repo_dir):
            count = 0
            for item in os.listdir(repo_dir):
                item_path = os.path.join(repo_dir, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                    count += 1
                except Exception as e:
                    print(f"    Error borrando {item}: {e}")
            print(f"    repositorio_archivos/: {count} items eliminados")
        else:
            print(f"    repositorio_archivos/: no existe")

        # scan_buffers
        buffers_dir = os.path.join(base_dir, 'logs', 'scan_buffers')
        if os.path.exists(buffers_dir):
            count = 0
            for item in os.listdir(buffers_dir):
                try:
                    os.remove(os.path.join(buffers_dir, item))
                    count += 1
                except Exception as e:
                    print(f"    Error borrando {item}: {e}")
            print(f"    logs/scan_buffers/: {count} archivos eliminados")
        else:
            print(f"    logs/scan_buffers/: no existe")

        # scan_states
        states_dir = os.path.join(base_dir, 'logs', 'scan_states')
        if os.path.exists(states_dir):
            count = 0
            for item in os.listdir(states_dir):
                try:
                    os.remove(os.path.join(states_dir, item))
                    count += 1
                except Exception as e:
                    print(f"    Error borrando {item}: {e}")
            print(f"    logs/scan_states/: {count} archivos eliminados")
        else:
            print(f"    logs/scan_states/: no existe")

        print("\n[3] VERIFICACION FINAL...")

        # Verificar que todo esta limpio
        print(f"    ArchivoDescargado: {ArchivoDescargado.query.count()}")
        print(f"    ArchivoRepositorio: {ArchivoRepositorio.query.count()}")
        print(f"    CorreoProcesado: {CorreoProcesado.query.count()}")
        print(f"    RangoCobertura: {RangoCobertura.query.count()}")
        print(f"    Escaneo: {Escaneo.query.count()}")
        print(f"    LogEscaneo: {LogEscaneo.query.count()}")

        # Verificar archivos fisicos
        if os.path.exists(repo_dir):
            total = sum(len(files) for _, _, files in os.walk(repo_dir))
            print(f"    Archivos en disco: {total}")
        else:
            print(f"    Archivos en disco: 0")

        print("\n" + "=" * 70)
        print("LIMPIEZA COMPLETADA")
        print("=" * 70)


if __name__ == '__main__':
    confirmacion = input("ATENCION: Esto borrara TODOS los datos. Escriba 'SI' para continuar: ")
    if confirmacion.strip().upper() == 'SI':
        main()
    else:
        print("Operacion cancelada.")
