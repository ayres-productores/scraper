# Manual de Usuario - Sistema CRM de Polizas

## Indice

1. [Introduccion](#1-introduccion)
2. [Acceso al Sistema](#2-acceso-al-sistema)
3. [Panel CRM (Dashboard)](#3-panel-crm-dashboard)
4. [Gestion de Polizas](#4-gestion-de-polizas)
5. [Gestion de Pagos](#5-gestion-de-pagos)
6. [Historial de Interacciones](#6-historial-de-interacciones)
7. [Sistema de Alertas](#7-sistema-de-alertas)
8. [Gestion de Siniestros](#8-gestion-de-siniestros)
9. [Extraccion Automatica de PDFs](#9-extraccion-automatica-de-pdfs)
10. [Tareas de Mantenimiento](#10-tareas-de-mantenimiento)

---

## 1. Introduccion

El Sistema CRM de Polizas es una herramienta integral para la gestion de seguros que permite:

- Administrar polizas con datos completos (asegurado, vehiculo, inmueble, coberturas)
- Controlar pagos y cuotas de primas
- Registrar interacciones con clientes (llamadas, emails, reuniones)
- Recibir alertas automaticas de vencimientos
- Gestionar siniestros desde la denuncia hasta el pago
- Extraer datos automaticamente de PDFs de polizas

---

## 2. Acceso al Sistema

### Iniciar la Aplicacion

```bash
cd portal_seguros
python run.py
```

### URL de Acceso

Abrir el navegador en: `http://127.0.0.1:5000`

### Credenciales por Defecto

- **Usuario:** admin@empresa.com
- **Contrasena:** CambiarEnPrimerLogin123!

### Menu de Navegacion

Una vez autenticado, acceder al CRM desde:
- Menu principal > **Distribucion** > **CRM**
- O directamente: `http://127.0.0.1:5000/distribucion/crm`

---

## 3. Panel CRM (Dashboard)

**Ruta:** `/distribucion/crm`

El panel principal muestra un resumen de toda la actividad:

### Tarjetas de Estadisticas

| Tarjeta | Descripcion |
|---------|-------------|
| Clientes Activos | Total de clientes en cartera |
| Polizas Activas | Polizas vigentes actualmente |
| Por Vencer (30 dias) | Polizas que vencen proximamente |
| Alertas Pendientes | Alertas que requieren atencion |

### Acciones Rapidas

- **Nuevo Cliente:** Crear un cliente nuevo
- **Nueva Poliza:** Asignar poliza a cliente existente
- **Ver Alertas:** Ir al centro de alertas
- **Pagos Pendientes:** Ver todos los pagos por cobrar

### Secciones del Dashboard

1. **Proximos Vencimientos:** Lista de polizas que vencen en los proximos 30 dias
2. **Ultimas Interacciones:** Historial reciente de contactos con clientes
3. **Seguimientos Pendientes:** Recordatorios de seguimiento programados

---

## 4. Gestion de Polizas

### 4.1 Ver/Editar Poliza Completa

**Ruta:** `/distribucion/poliza/<id>/completa`

La vista de poliza completa tiene pestanas organizadas:

#### Pestana: Datos Basicos
- Numero de poliza
- Compania aseguradora
- Tipo de seguro (auto, hogar, vida, etc.)
- Fechas de vigencia (desde/hasta)
- Prima anual
- Estado (activa, vencida, en renovacion, cancelada)

#### Pestana: Asegurado
- Nombre completo
- Documento de identidad
- Direccion
- Telefono y email de contacto

#### Pestana: Bien Asegurado
Segun el tipo de bien:

**Para Vehiculos:**
- Marca y modelo
- Ano de fabricacion
- Patente/Matricula
- Numero de chasis y motor
- Color
- Uso (particular, comercial)

**Para Inmuebles:**
- Direccion completa
- Tipo (casa, departamento, local)
- Superficie (m2)
- Tipo de construccion

#### Pestana: Coberturas
- Lista de coberturas incluidas
- Suma asegurada total
- Deducible
- Franquicia

#### Pestana: Pago
- Forma de pago (anual, semestral, mensual)
- Cantidad de cuotas
- Dia de vencimiento de cuota
- Medio de pago preferido

#### Pestana: Productor
- Nombre del productor/agente
- Telefono de contacto
- Email
- Sucursal

### 4.2 Estados de Poliza

| Estado | Descripcion | Color |
|--------|-------------|-------|
| Activa | Poliza vigente | Verde |
| En Renovacion | Vence en menos de 15 dias | Amarillo |
| Vencida | Fecha de vigencia pasada | Rojo |
| Cancelada | Dada de baja | Gris |
| Suspendida | Temporalmente inactiva | Naranja |

### 4.3 Renovacion de Polizas

Cuando una poliza esta "En Renovacion":
1. Ir a la poliza desde el dashboard
2. Click en "Renovar Poliza"
3. Se crea una nueva poliza vinculada a la anterior
4. Actualizar datos y fechas de vigencia

---

## 5. Gestion de Pagos

### 5.1 Ver Pagos de una Poliza

**Ruta:** `/distribucion/poliza/<id>/pagos`

Muestra todos los pagos/cuotas de una poliza con:
- Numero de cuota
- Monto
- Fecha de vencimiento
- Estado (pendiente, pagado, vencido)
- Fecha de pago (si aplica)

### 5.2 Generar Cuotas Automaticamente

**Ruta:** `/distribucion/poliza/<id>/pagos/generar`

1. Seleccionar forma de pago (mensual, trimestral, etc.)
2. Ingresar monto de la prima total
3. Seleccionar fecha de inicio
4. Click en "Generar Cuotas"

El sistema calculara automaticamente:
- Cantidad de cuotas segun la forma de pago
- Monto de cada cuota
- Fechas de vencimiento

### 5.3 Registrar un Pago

**Ruta:** `/distribucion/poliza/<id>/pagos/nuevo`

Campos a completar:
- Numero de cuota
- Monto pagado
- Fecha de pago
- Metodo de pago (efectivo, transferencia, tarjeta, debito automatico)
- Numero de comprobante (opcional)
- Notas (opcional)

### 5.4 Marcar Pago como Pagado (Rapido)

En la lista de pagos, cada cuota pendiente tiene un boton de check (✓) para marcarla como pagada rapidamente con la fecha actual.

### 5.5 Ver Todos los Pagos Pendientes

**Ruta:** `/distribucion/pagos/pendientes`

Vista global de todos los pagos pendientes y vencidos de todos los clientes:

**Filtros disponibles:**
- Solo pendientes
- Solo vencidos
- Pagados (historico)

**Estadisticas mostradas:**
- Total de pagos
- Cantidad vencidos
- Monto total pendiente

---

## 6. Historial de Interacciones

### 6.1 Ver Interacciones de un Cliente

**Ruta:** `/distribucion/clientes/<id>/interacciones`

Muestra una linea de tiempo con todas las interacciones:
- Fecha y hora
- Tipo de interaccion
- Asunto
- Descripcion
- Estado de seguimiento

### 6.2 Registrar Nueva Interaccion

**Ruta:** `/distribucion/clientes/<id>/interacciones/nueva`

#### Tipos de Interaccion

| Tipo | Uso |
|------|-----|
| Llamada | Conversacion telefonica |
| Email | Correo electronico |
| WhatsApp | Mensaje de WhatsApp |
| Reunion | Encuentro presencial |
| Visita | Visita al cliente o del cliente |
| Nota | Recordatorio interno |

#### Campos del Formulario

- **Tipo:** Seleccionar tipo de interaccion
- **Direccion:** Entrante (el cliente contacto) o Saliente (contactaste al cliente)
- **Poliza relacionada:** Opcional, vincular a una poliza especifica
- **Asunto:** Breve descripcion del motivo
- **Descripcion:** Detalle completo de la conversacion
- **Duracion:** Tiempo en minutos (para llamadas/reuniones)

#### Programar Seguimiento

- Marcar "Requiere seguimiento"
- Seleccionar fecha de seguimiento
- El sistema creara una alerta automatica

---

## 7. Sistema de Alertas

### 7.1 Centro de Alertas

**Ruta:** `/distribucion/alertas`

Panel centralizado de todas las alertas con filtros:

**Por Estado:**
- Pendientes (requieren atencion)
- Notificadas (ya vistas)
- Resueltas
- Descartadas

**Por Tipo:**
- Vencimiento de poliza
- Vencimiento de pago
- Seguimiento pendiente

**Por Prioridad:**
- Alta (rojo) - Vence en 7 dias o menos
- Media (amarillo) - Vence en 8-15 dias
- Baja (verde) - Vence en mas de 15 dias

### 7.2 Tipos de Alertas

| Tipo | Se genera cuando... |
|------|---------------------|
| Vencimiento Poliza | Poliza vence en 30, 15 o 7 dias |
| Vencimiento Pago | Cuota vence en los proximos 5 dias |
| Seguimiento | Fecha de seguimiento llego o paso |

### 7.3 Acciones sobre Alertas

- **Ver Detalle:** Ir a la poliza/pago relacionado
- **Marcar Resuelta:** Cuando se tomo accion
- **Descartar:** Ignorar la alerta

### 7.4 Generar Alertas Manualmente

Click en "Generar Alertas" en el panel de alertas para ejecutar el proceso de generacion inmediatamente.

---

## 8. Gestion de Siniestros

### 8.1 Ver Siniestros de una Poliza

**Ruta:** `/distribucion/poliza/<id>/siniestros`

Lista de siniestros vinculados a una poliza.

### 8.2 Ver Todos los Siniestros

**Ruta:** `/distribucion/siniestros`

Vista global con filtros por estado.

### 8.3 Registrar Nuevo Siniestro

**Ruta:** `/distribucion/poliza/<id>/siniestros/nuevo`

#### Datos del Siniestro

- **Numero de siniestro:** Interno (se genera automaticamente)
- **Numero compania:** El que asigna la aseguradora
- **Fecha de ocurrencia:** Cuando sucedio
- **Hora:** Opcional
- **Fecha de denuncia:** Cuando se reporto a la aseguradora

#### Tipo de Siniestro

| Tipo | Descripcion |
|------|-------------|
| Choque/Colision | Accidente vehicular |
| Robo Total | Perdida total por robo |
| Robo Parcial | Robo de partes |
| Incendio | Dano por fuego |
| Granizo | Dano por granizo |
| Inundacion | Dano por agua |
| Vandalismo | Dano intencional |
| Responsabilidad Civil | Dano a terceros |
| Accidente Personal | Lesion del asegurado |

#### Descripcion y Ubicacion

- **Descripcion:** Relato detallado de lo ocurrido
- **Ubicacion:** Donde sucedio el siniestro

#### Terceros Involucrados

- Marcar si hay terceros
- Marcar si hay lesionados
- Descripcion de lesiones

#### Montos

- **Monto reclamado:** Lo que solicita el asegurado
- **Monto aprobado:** Lo que aprueba la compania
- **Monto pagado:** Lo efectivamente pagado
- **Deducible aplicado:** Monto del deducible

### 8.4 Estados del Siniestro

| Estado | Descripcion |
|--------|-------------|
| Denunciado | Recien reportado |
| En Proceso | Bajo revision |
| Documentacion | Esperando documentos |
| Peritaje | En evaluacion tecnica |
| Aprobado | Indemnizacion aprobada |
| Rechazado | Reclamo denegado |
| Pagado | Indemnizacion depositada |
| Cerrado | Caso finalizado |

### 8.5 Actualizar Estado de Siniestro

1. Ir a Editar Siniestro
2. Cambiar el estado
3. Si es rechazado, completar motivo
4. Si es pagado, ingresar monto pagado
5. Guardar cambios

---

## 9. Extraccion Automatica de PDFs

### 9.1 Como Funciona

Cuando se carga un PDF de poliza, el sistema intenta extraer automaticamente:
- Numero de poliza
- Fechas de vigencia
- Prima
- Datos del asegurado
- Datos del vehiculo (si aplica)
- Compania aseguradora

### 9.2 Nivel de Confianza

El sistema calcula un porcentaje de confianza (0-100%):

| Confianza | Significado |
|-----------|-------------|
| 80-100% | Datos muy confiables |
| 50-79% | Revisar datos extraidos |
| 0-49% | Requiere correccion manual |

### 9.3 Companias Soportadas

El extractor tiene patrones optimizados para:
- Mapfre
- La Caja
- Federacion Patronal
- Sancor
- Allianz
- Zurich
- SURA
- La Segunda

Otras companias funcionan con patrones genericos.

### 9.4 Correccion Manual

Si la extraccion no es correcta:
1. Ir a la poliza
2. Click en "Editar"
3. Corregir los campos necesarios
4. Guardar

---

## 10. Tareas de Mantenimiento

### 10.1 Tareas Diarias Automaticas

Se recomienda ejecutar diariamente:

```python
from app.tasks.alertas import ejecutar_tareas_diarias

# Ejecutar para todos los usuarios
ejecutar_tareas_diarias()

# O para un usuario especifico
ejecutar_tareas_diarias(usuario_id=1)
```

Esto realiza:
- Marcar pagos vencidos
- Actualizar estados de polizas
- Generar alertas de vencimiento
- Generar alertas de pagos
- Generar alertas de seguimientos

### 10.2 Limpiar Alertas Antiguas

Para eliminar alertas resueltas/descartadas de mas de 90 dias:

```python
from app.tasks.alertas import limpiar_alertas_antiguas

limpiar_alertas_antiguas(dias=90)
```

### 10.3 Configurar Tarea Programada (Opcional)

Para automatizar las tareas diarias, agregar a `run.py`:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from app.tasks.alertas import ejecutar_tareas_diarias

scheduler = BackgroundScheduler()
scheduler.add_job(ejecutar_tareas_diarias, 'cron', hour=8, minute=0)
scheduler.start()
```

Esto ejecutara las tareas todos los dias a las 8:00 AM.

---

## Atajos y Tips

### Navegacion Rapida

| Desde | Accion | Lleva a |
|-------|--------|---------|
| Dashboard | Click en cliente | Detalle del cliente |
| Dashboard | Click en poliza | Poliza completa |
| Poliza | Tab "Pagos" | Lista de pagos |
| Cliente | Tab "Interacciones" | Historial |

### Colores de Estado

| Color | Significado |
|-------|-------------|
| Verde | OK / Pagado / Activo |
| Amarillo | Advertencia / Pendiente |
| Rojo | Urgente / Vencido |
| Gris | Inactivo / Cerrado |

### Buenas Practicas

1. **Revisar alertas diariamente** - Atender primero las de prioridad alta
2. **Registrar todas las interacciones** - Mantener historial completo
3. **Programar seguimientos** - No olvidar contactar clientes
4. **Verificar datos extraidos** - Especialmente con confianza < 80%
5. **Actualizar estados de siniestros** - Mantener al cliente informado

---

## Soporte

Para reportar problemas o sugerencias:
- Crear issue en el repositorio del proyecto
- Contactar al administrador del sistema

---

*Manual version 1.0 - Sistema CRM de Polizas*
