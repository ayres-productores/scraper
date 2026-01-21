"""Script para crear usuario"""
from app import create_app, db
from app.models import Usuario

app = create_app()

with app.app_context():
    # Verificar si existe
    existente = Usuario.query.filter_by(correo='user').first()
    if existente:
        print('Usuario ya existe, actualizando contraseña...')
        existente.establecer_contrasena('PASSWORD')
        existente.debe_cambiar_contrasena = False
        db.session.commit()
        print('Contraseña actualizada.')
    else:
        # Crear nuevo usuario
        usuario = Usuario(
            correo='user',
            nombre='Usuario de Prueba',
            rol='usuario',
            debe_cambiar_contrasena=False,
            activo=True
        )
        usuario.establecer_contrasena('PASSWORD')
        db.session.add(usuario)
        db.session.commit()
        print('Usuario creado exitosamente.')

    print()
    print('Credenciales:')
    print('  Usuario: user')
    print('  Contraseña: PASSWORD')
