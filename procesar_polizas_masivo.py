"""
Script para procesar masivamente todos los PDFs y crear registros de clientes y pólizas.
Ejecutar: python procesar_polizas_masivo.py
"""

import os
import sys
import json
from datetime import datetime, date

# Agregar el directorio al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import (
    ArchivoDescargado, RegistroAnalisisPDF, Cliente, PolizaCliente, Usuario
)
from app.extractor.pdf_parser import ExtractorDatosPoliza


def re_analizar_todos():
    """Re-analiza todos los PDFs para actualizar campos de vigencia."""
    print("\n" + "=" * 60)
    print("  PASO 1: RE-ANALIZAR PDFs PARA ACTUALIZAR VIGENCIA")
    print("=" * 60 + "\n")

    registros = RegistroAnalisisPDF.query.filter(
        RegistroAnalisisPDF.estado.in_(['analizado', 'pendiente'])
    ).all()

    actualizados = 0
    errores = 0

    for i, reg in enumerate(registros, 1):
        archivo = reg.archivo
        if not archivo or not os.path.exists(archivo.ruta_archivo):
            print(f"  [{i}/{len(registros)}] ERROR: Archivo no encontrado - ID {reg.archivo_id}")
            errores += 1
            continue

        try:
            extractor = ExtractorDatosPoliza()
            datos = extractor.extraer_datos(archivo.ruta_archivo)
            resumen = extractor.resumen_extraccion()

            # Actualizar registro con todos los datos
            reg.marcar_analizado(
                datos_json=json.dumps(datos, default=str, ensure_ascii=False),
                confianza=resumen.get('confianza', 0),
                compania=resumen.get('compania'),
                tipo_seguro=resumen.get('tipo_seguro'),
                numero_poliza=datos.get('numero_poliza'),
                fecha_vigencia_desde=datos.get('fecha_vigencia_desde'),
                fecha_vigencia_hasta=datos.get('fecha_vigencia_hasta'),
                asegurado=datos.get('asegurado_nombre')
            )

            vigencia = datos.get('fecha_vigencia_hasta')
            asegurado = datos.get('asegurado_nombre', '-')[:30]
            print(f"  [{i}/{len(registros)}] OK: {asegurado} | Vigencia: {vigencia}")
            actualizados += 1

        except Exception as e:
            print(f"  [{i}/{len(registros)}] ERROR: {str(e)[:50]}")
            errores += 1

    db.session.commit()
    print(f"\n  Actualizados: {actualizados} | Errores: {errores}")
    return actualizados


def obtener_o_crear_cliente(datos, usuario_id):
    """Busca un cliente existente por documento o crea uno nuevo."""
    documento = datos.get('asegurado_documento', '').strip()
    nombre = datos.get('asegurado_nombre', '').strip()

    if not nombre:
        return None, False

    # Buscar por documento si existe
    if documento:
        cliente = Cliente.query.filter_by(
            documento_identidad=documento,
            usuario_id=usuario_id
        ).first()
        if cliente:
            return cliente, False

    # Buscar por nombre exacto
    cliente = Cliente.query.filter_by(
        usuario_id=usuario_id
    ).filter(
        db.func.lower(db.func.concat(Cliente.nombre, ' ', Cliente.apellido)) == nombre.lower()
    ).first()

    if cliente:
        return cliente, False

    # Crear nuevo cliente
    # Separar nombre y apellido
    partes = nombre.split()
    if len(partes) >= 2:
        # Asumir formato "APELLIDO NOMBRE" o "APELLIDO, NOMBRE"
        if ',' in nombre:
            partes_coma = nombre.split(',')
            apellido = partes_coma[0].strip()
            nombre_pila = partes_coma[1].strip() if len(partes_coma) > 1 else ''
        else:
            # Primer palabra es apellido, resto es nombre
            apellido = partes[0]
            nombre_pila = ' '.join(partes[1:])
    else:
        apellido = nombre
        nombre_pila = ''

    cliente = Cliente(
        usuario_id=usuario_id,
        nombre=nombre_pila.title() if nombre_pila else apellido.title(),
        apellido=apellido.title() if nombre_pila else '',
        documento_identidad=documento or None,
        telefono_whatsapp=datos.get('asegurado_telefono', ''),
        email=datos.get('asegurado_email', ''),
        activo=True
    )

    db.session.add(cliente)
    db.session.flush()

    return cliente, True


def parsear_fecha(fecha_valor):
    """Convierte un valor de fecha (string o date) a objeto date."""
    if fecha_valor is None:
        return None
    if isinstance(fecha_valor, date):
        return fecha_valor
    if isinstance(fecha_valor, str):
        # Intentar parsear varios formatos
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']:
            try:
                return datetime.strptime(fecha_valor, fmt).date()
            except ValueError:
                continue
    return None


def crear_poliza(datos, cliente_id, archivo_id, registro):
    """Crea una póliza a partir de los datos extraídos."""

    # Verificar si ya existe una póliza para este archivo
    existente = PolizaCliente.query.filter_by(archivo_id=archivo_id).first()
    if existente:
        return existente, False

    # Parsear fechas
    fecha_desde = parsear_fecha(datos.get('fecha_vigencia_desde'))
    fecha_hasta = parsear_fecha(datos.get('fecha_vigencia_hasta'))

    # Determinar estado
    if fecha_hasta:
        estado = 'vigente' if fecha_hasta >= date.today() else 'vencida'
    else:
        estado = 'vigente'

    poliza = PolizaCliente(
        cliente_id=cliente_id,
        archivo_id=archivo_id,
        numero_poliza=datos.get('numero_poliza', ''),
        tipo_seguro=datos.get('tipo_seguro', 'otro'),
        fecha_vigencia_desde=fecha_desde,
        fecha_vigencia_hasta=fecha_hasta,
        prima_anual=datos.get('prima_anual'),
        suma_asegurada=datos.get('suma_asegurada'),

        # Datos del asegurado
        asegurado_nombre=datos.get('asegurado_nombre', ''),
        asegurado_documento=datos.get('asegurado_documento', ''),
        asegurado_direccion=datos.get('asegurado_direccion', ''),
        asegurado_telefono=datos.get('asegurado_telefono', ''),
        asegurado_email=datos.get('asegurado_email', ''),

        # Datos del vehículo (si aplica)
        vehiculo_marca=datos.get('vehiculo_marca', ''),
        vehiculo_modelo=datos.get('vehiculo_modelo', ''),
        vehiculo_anio=datos.get('vehiculo_anio'),
        vehiculo_patente=datos.get('vehiculo_patente', ''),
        vehiculo_chasis=datos.get('vehiculo_chasis', ''),
        vehiculo_motor=datos.get('vehiculo_motor', ''),
        vehiculo_uso=datos.get('vehiculo_uso', ''),

        # Metadatos de extracción
        datos_extraidos=registro.datos_extraidos,
        confianza_extraccion=registro.confianza_extraccion,
        fecha_extraccion=datetime.now(),

        estado=estado
    )

    db.session.add(poliza)
    db.session.flush()

    return poliza, True


def procesar_todos():
    """Procesa todos los PDFs analizados y crea clientes/pólizas."""
    print("\n" + "=" * 60)
    print("  PASO 2: CREAR CLIENTES Y PÓLIZAS")
    print("=" * 60 + "\n")

    # Obtener usuario para asignar clientes (usar el primer usuario no-admin)
    usuario = Usuario.query.filter(Usuario.correo != 'admin@empresa.com').first()
    if not usuario:
        usuario = Usuario.query.first()

    print(f"  Usuario asignado: {usuario.correo}\n")

    registros = RegistroAnalisisPDF.query.filter_by(estado='analizado').all()

    clientes_creados = 0
    clientes_existentes = 0
    polizas_creadas = 0
    polizas_existentes = 0
    errores = 0
    sin_asegurado = 0

    for i, reg in enumerate(registros, 1):
        try:
            # Cargar datos extraídos
            if not reg.datos_extraidos:
                print(f"  [{i}/{len(registros)}] SIN DATOS: Archivo {reg.archivo_id}")
                errores += 1
                continue

            datos = json.loads(reg.datos_extraidos)

            # Verificar que tenga asegurado
            if not datos.get('asegurado_nombre'):
                print(f"  [{i}/{len(registros)}] SIN ASEGURADO: {reg.numero_poliza_detectado}")
                sin_asegurado += 1
                continue

            # Obtener o crear cliente
            cliente, es_nuevo_cliente = obtener_o_crear_cliente(datos, usuario.id)

            if not cliente:
                print(f"  [{i}/{len(registros)}] ERROR CLIENTE: {datos.get('asegurado_nombre')}")
                errores += 1
                continue

            if es_nuevo_cliente:
                clientes_creados += 1
            else:
                clientes_existentes += 1

            # Crear póliza
            poliza, es_nueva_poliza = crear_poliza(datos, cliente.id, reg.archivo_id, reg)

            if es_nueva_poliza:
                polizas_creadas += 1
            else:
                polizas_existentes += 1

            # Actualizar registro
            reg.estado = 'procesado'
            reg.fecha_procesamiento = datetime.now()
            reg.cliente_id = cliente.id
            reg.poliza_id = poliza.id
            reg.cliente_creado = es_nuevo_cliente
            reg.poliza_creada = es_nueva_poliza
            reg.usuario_id = usuario.id

            estado_cli = "NUEVO" if es_nuevo_cliente else "existe"
            estado_pol = "NUEVA" if es_nueva_poliza else "existe"
            vigencia = datos.get('fecha_vigencia_hasta', '-')
            print(f"  [{i}/{len(registros)}] {datos.get('asegurado_nombre', '-')[:25]:25} | Cliente:{estado_cli:6} | Poliza:{estado_pol:6} | Vig:{vigencia}")

        except Exception as e:
            print(f"  [{i}/{len(registros)}] ERROR: {str(e)[:60]}")
            errores += 1

    db.session.commit()

    print("\n" + "-" * 60)
    print(f"  RESUMEN:")
    print(f"    Clientes creados: {clientes_creados}")
    print(f"    Clientes existentes: {clientes_existentes}")
    print(f"    Pólizas creadas: {polizas_creadas}")
    print(f"    Pólizas existentes: {polizas_existentes}")
    print(f"    Sin asegurado: {sin_asegurado}")
    print(f"    Errores: {errores}")
    print("-" * 60)


def mostrar_resumen_final():
    """Muestra el resumen final de la base de datos."""
    print("\n" + "=" * 60)
    print("  RESUMEN FINAL DE LA BASE DE DATOS")
    print("=" * 60 + "\n")

    total_clientes = Cliente.query.count()
    total_polizas = PolizaCliente.query.count()

    polizas_vigentes = PolizaCliente.query.filter(
        PolizaCliente.fecha_vigencia_hasta >= date.today()
    ).count()

    polizas_vencidas = PolizaCliente.query.filter(
        PolizaCliente.fecha_vigencia_hasta < date.today()
    ).count()

    polizas_sin_fecha = PolizaCliente.query.filter(
        PolizaCliente.fecha_vigencia_hasta.is_(None)
    ).count()

    print(f"  Total Clientes: {total_clientes}")
    print(f"  Total Pólizas:  {total_polizas}")
    print(f"    - Vigentes:   {polizas_vigentes}")
    print(f"    - Vencidas:   {polizas_vencidas}")
    print(f"    - Sin fecha:  {polizas_sin_fecha}")

    # Top compañías
    print("\n  Por Compañía:")
    from sqlalchemy import func
    companias = db.session.query(
        RegistroAnalisisPDF.compania_detectada,
        func.count(RegistroAnalisisPDF.id)
    ).filter(
        RegistroAnalisisPDF.estado == 'procesado'
    ).group_by(RegistroAnalisisPDF.compania_detectada).all()

    for comp, count in companias:
        print(f"    - {comp or 'Desconocida'}: {count}")


def main():
    print("\n" + "=" * 60)
    print("  PROCESAMIENTO MASIVO DE PÓLIZAS")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    app = create_app()
    with app.app_context():
        # Paso 1: Re-analizar para obtener vigencias
        re_analizar_todos()

        # Paso 2: Crear clientes y pólizas
        procesar_todos()

        # Resumen final
        mostrar_resumen_final()

    print("\n" + "=" * 60)
    print("  PROCESAMIENTO COMPLETADO")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    main()
