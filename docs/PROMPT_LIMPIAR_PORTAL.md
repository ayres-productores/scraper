# Prompt: Eliminar Extractor de Portal Seguros

## Objetivo

Eliminar completamente el módulo de extracción de portal_seguros. La extracción ahora la hace un servidor separado.

## Qué Eliminar

### 1. Directorio completo
```
app/extractor/          # TODO - eliminar
```

### 2. Archivos de utilidades relacionados
```
app/utils/scan_buffer.py
app/utils/scan_logger.py
app/utils/scan_state.py  (si existe)
```

### 3. En `app/__init__.py`
- Quitar import de `extractor_bp`
- Quitar `register_blueprint(extractor_bp)`
- Quitar funciones `_consolidar_buffers_pendientes` y relacionadas

### 4. En `app/main/routes.py`
- Eliminar rutas que empiecen con `/extractor/`
- Eliminar imports de `app.extractor.*`
- Las rutas de `/archivos/*` se mantienen (leen de BD)

### 5. En `app/distribucion/`
- Eliminar imports de `app.extractor.*`
- Si algo depende de `ExtractorDatosPoliza`, evaluar si se necesita

### 6. Templates
```
app/templates/extractor/    # TODO - eliminar
```

## Qué Mantener

- **Modelos de BD** (`app/models.py`) - los usa el extractor server
- **Rutas de archivos** (`/archivos/*`) - solo leen de BD
- **Todo lo demás** (distribucion, clientes, whatsapp, admin, auth)

## Verificación

Después de eliminar:
1. `python -m py_compile app/__init__.py` debe pasar
2. `python run.py` debe iniciar sin errores
3. Dashboard debe cargar
4. `/archivos` debe mostrar PDFs existentes

## Notas

- Los PDFs existentes en disco siguen accesibles
- Los datos en BD siguen accesibles
- Solo se elimina la capacidad de ESCANEAR desde este servidor
