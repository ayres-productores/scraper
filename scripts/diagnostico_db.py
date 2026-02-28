"""
Diagnostico completo del estado de la base de datos.
Verifica integridad de datos y relaciones.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    print("=" * 70)
    print("DIAGNOSTICO COMPLETO DE BASE DE DATOS")
    print("=" * 70)

    from app import create_app, db
    from app.models import (
        Usuario, Escaneo, ArchivoDescargado, ArchivoRepositorio,
        CorreoProcesado, CuentaGmail, Compania
    )

    app = create_app()

    with app.app_context():
        # 1. Usuarios
        print("\n[1] USUARIOS")
        usuarios = Usuario.query.all()
        for u in usuarios:
            print(f"    ID: {u.id}, Correo: {u.correo}, Nombre: {u.nombre}")

        # 2. Cuentas Gmail
        print("\n[2] CUENTAS GMAIL")
        cuentas = CuentaGmail.query.all()
        for c in cuentas:
            print(f"    ID: {c.id}, Email: {c.correo_gmail}, Usuario: {c.usuario_id}, Activa: {c.activa}")

        # 3. Escaneos
        print("\n[3] ESCANEOS")
        escaneos = Escaneo.query.all()
        if not escaneos:
            print("    [!] NO HAY ESCANEOS EN LA BD")
        for e in escaneos:
            print(f"    ID: {e.id}, Usuario: {e.usuario_id}, Estado: {e.estado}, PDFs: {e.pdfs_descargados}")

        # 4. ArchivoDescargado
        print("\n[4] ARCHIVOS DESCARGADOS")
        archivos = ArchivoDescargado.query.all()
        print(f"    Total registros: {len(archivos)}")
        if archivos:
            print(f"    Primeros 5:")
            for a in archivos[:5]:
                print(f"      - ID: {a.id}, Doc: {a.id_documento}, Escaneo: {a.escaneo_id}")
                print(f"        Nombre: {a.nombre_archivo[:50]}...")

            # Verificar integridad con Escaneo
            escaneo_ids_validos = set(e.id for e in escaneos)
            huerfanos = [a for a in archivos if a.escaneo_id not in escaneo_ids_validos]
            if huerfanos:
                print(f"\n    [ERROR] {len(huerfanos)} archivos con escaneo_id invalido!")
                for h in huerfanos[:3]:
                    print(f"      - Archivo {h.id} tiene escaneo_id={h.escaneo_id} (no existe)")
            else:
                print(f"\n    [OK] Todos los archivos tienen escaneo_id valido")

            # Verificar que el usuario del escaneo coincida
            for a in archivos[:10]:
                escaneo = Escaneo.query.get(a.escaneo_id)
                if escaneo:
                    print(f"    Archivo {a.id_documento} -> Escaneo {escaneo.id} -> Usuario {escaneo.usuario_id}")

        # 5. ArchivoRepositorio
        print("\n[5] ARCHIVO REPOSITORIO")
        repos = ArchivoRepositorio.query.all()
        print(f"    Total registros: {len(repos)}")
        if repos:
            print(f"    Primeros 3:")
            for r in repos[:3]:
                print(f"      - Hash: {r.hash_sha256[:16]}..., Ruta: {r.ruta_relativa}")

        # 6. CorreoProcesado
        print("\n[6] CORREOS PROCESADOS")
        correos = CorreoProcesado.query.count()
        print(f"    Total registros: {correos}")

        # 7. Verificar archivos fisicos
        print("\n[7] ARCHIVOS FISICOS")
        repo_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'repositorio_archivos')
        if os.path.exists(repo_dir):
            total_fisicos = 0
            for root, dirs, files in os.walk(repo_dir):
                total_fisicos += len(files)
            print(f"    Archivos en repositorio_archivos/: {total_fisicos}")
        else:
            print(f"    [!] Directorio repositorio_archivos/ no existe")

        # 8. Verificar buffers pendientes
        print("\n[8] BUFFERS PENDIENTES")
        from app.utils.scan_buffer import obtener_buffers_pendientes
        pendientes = obtener_buffers_pendientes()
        print(f"    Buffers pendientes: {pendientes}")

        # 9. Companias
        print("\n[9] COMPANIAS")
        companias = Compania.query.all()
        print(f"    Total: {len(companias)}")
        for c in companias[:5]:
            count = ArchivoDescargado.query.filter_by(compania_id=c.id).count()
            print(f"    - {c.nombre}: {count} archivos")

        # 10. Simulacion de query de la UI
        print("\n[10] SIMULACION QUERY UI (archivos.html)")
        if usuarios:
            usuario = usuarios[0]
            query = ArchivoDescargado.query.join(Escaneo).filter(
                Escaneo.usuario_id == usuario.id
            )
            resultado = query.all()
            print(f"    Para usuario {usuario.id} ({usuario.correo}):")
            print(f"    - Archivos encontrados: {len(resultado)}")
            if resultado:
                print(f"    - Ejemplo: {resultado[0].nombre_archivo[:50]}...")
            else:
                print("    [!] La query no retorna archivos para este usuario")

                # Verificar por que
                todos_archivos = ArchivoDescargado.query.all()
                if todos_archivos:
                    print(f"\n    Diagnostico adicional:")
                    for a in todos_archivos[:5]:
                        escaneo = Escaneo.query.get(a.escaneo_id)
                        if escaneo:
                            print(f"    - Archivo escaneo_id={a.escaneo_id} -> usuario_id={escaneo.usuario_id} (esperado: {usuario.id})")
                        else:
                            print(f"    - Archivo escaneo_id={a.escaneo_id} -> ESCANEO NO EXISTE")

        print("\n" + "=" * 70)
        print("DIAGNOSTICO COMPLETADO")
        print("=" * 70)


if __name__ == '__main__':
    main()
