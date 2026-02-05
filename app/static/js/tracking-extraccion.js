/**
 * TrackingExtraccion - Modulo para rastrear cambios en campos extraidos de PDFs
 *
 * Este modulo permite detectar cuando el usuario modifica campos pre-rellenados
 * por el algoritmo de extraccion, para luego registrar las correcciones y
 * mejorar el sistema de extraccion predictiva.
 *
 * Uso:
 *   TrackingExtraccion.inicializar(datosExtraccion);
 *   // ... usuario edita el formulario ...
 *   const correcciones = TrackingExtraccion.generarCorrecciones();
 */

const TrackingExtraccion = (function() {
    'use strict';

    // Estado interno del modulo
    let estado = {
        inicializado: false,
        valoresOriginales: {},
        camposModificados: new Set(),
        tiempoInicio: null,
        formularioSelector: '#formulario-poliza'
    };

    // Mapeo de nombres de campos del formulario a rutas del JSON estructurado
    const MAPEO_CAMPOS = {
        // Cliente
        'cliente_nombre': 'cliente.nombre',
        'asegurado_nombre': 'cliente.nombre',
        'cliente_documento': 'cliente.documento',
        'asegurado_documento': 'cliente.documento',
        'cliente_telefono': 'cliente.telefono',
        'asegurado_telefono': 'cliente.telefono',
        'telefono_whatsapp': 'cliente.telefono',
        'cliente_email': 'cliente.email',
        'asegurado_email': 'cliente.email',
        'cliente_direccion': 'cliente.direccion',
        'asegurado_direccion': 'cliente.direccion',

        // Poliza
        'numero_poliza': 'poliza.numero_poliza',
        'tipo_seguro': 'poliza.tipo_seguro',
        'fecha_vigencia_desde': 'poliza.fecha_vigencia_desde',
        'fecha_vigencia_hasta': 'poliza.fecha_vigencia_hasta',
        'prima_anual': 'poliza.prima_anual',
        'suma_asegurada': 'poliza.suma_asegurada',
        'deducible': 'poliza.deducible',
        'forma_pago': 'poliza.forma_pago',
        'cantidad_cuotas': 'poliza.cantidad_cuotas',
        'bien_asegurado_tipo': 'poliza.bien_asegurado_tipo',

        // Vehiculo
        'vehiculo_marca': 'vehiculo.marca',
        'vehiculo_modelo': 'vehiculo.modelo',
        'vehiculo_anio': 'vehiculo.anio',
        'vehiculo_patente': 'vehiculo.patente',
        'vehiculo_chasis': 'vehiculo.chasis',
        'vehiculo_motor': 'vehiculo.motor',
        'vehiculo_color': 'vehiculo.color',
        'vehiculo_uso': 'vehiculo.uso',

        // Inmueble
        'inmueble_direccion': 'inmueble.direccion',
        'inmueble_tipo': 'inmueble.tipo',
        'inmueble_superficie': 'inmueble.superficie',

        // Productor
        'productor_nombre': 'productor.nombre',
        'productor_telefono': 'productor.telefono',
        'productor_email': 'productor.email',
        'productor_matricula': 'productor.matricula'
    };

    // Mapeo inverso (ruta JSON -> name del campo)
    const MAPEO_INVERSO = {};
    Object.entries(MAPEO_CAMPOS).forEach(([name, ruta]) => {
        if (!MAPEO_INVERSO[ruta]) {
            MAPEO_INVERSO[ruta] = [];
        }
        MAPEO_INVERSO[ruta].push(name);
    });

    /**
     * Aplana los datos estructurados del JSON a un objeto plano
     * con rutas como claves (ej: "cliente.nombre")
     */
    function aplanarDatos(datos) {
        const plano = {};

        function procesar(obj, prefijo = '') {
            if (!obj || typeof obj !== 'object') return;

            Object.entries(obj).forEach(([key, val]) => {
                const ruta = prefijo ? `${prefijo}.${key}` : key;

                // Si tiene estructura de campo con metadata
                if (val && typeof val === 'object' && 'valor' in val) {
                    plano[ruta] = {
                        valor: val.valor,
                        texto_original: val.texto_original || val.valor,
                        confianza: val.confianza || 0,
                        fuente: val.fuente || null
                    };
                } else if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
                    // Recursivamente procesar objetos anidados
                    procesar(val, ruta);
                }
            });
        }

        // Procesar cada seccion
        if (datos.cliente) procesar(datos.cliente, 'cliente');
        if (datos.poliza) procesar(datos.poliza, 'poliza');
        if (datos.vehiculo) procesar(datos.vehiculo, 'vehiculo');
        if (datos.inmueble) procesar(datos.inmueble, 'inmueble');
        if (datos.productor) procesar(datos.productor, 'productor');

        return plano;
    }

    /**
     * Obtiene el valor actual de un campo del formulario por su ruta JSON
     */
    function obtenerValorFormulario(rutaCampo) {
        const names = MAPEO_INVERSO[rutaCampo] || [];

        for (const name of names) {
            const elemento = document.querySelector(`[name="${name}"]`);
            if (elemento) {
                return elemento.value || null;
            }
        }

        return null;
    }

    /**
     * Obtiene el elemento del formulario por ruta JSON
     */
    function obtenerElementoPorRuta(rutaCampo) {
        const names = MAPEO_INVERSO[rutaCampo] || [];

        for (const name of names) {
            const elemento = document.querySelector(`[name="${name}"]`);
            if (elemento) {
                return elemento;
            }
        }

        return null;
    }

    /**
     * Configura event listeners en todos los campos del formulario
     */
    function configurarListeners() {
        const formulario = document.querySelector(estado.formularioSelector);
        if (!formulario) {
            console.warn('TrackingExtraccion: Formulario no encontrado:', estado.formularioSelector);
            return;
        }

        const campos = formulario.querySelectorAll('input, select, textarea');

        campos.forEach(campo => {
            // Listener para detectar cambios
            campo.addEventListener('change', function(e) {
                registrarCambio(e.target);
            });

            // Listener para marcar como modificado mientras escribe
            campo.addEventListener('input', function(e) {
                marcarModificado(e.target);
            });
        });
    }

    /**
     * Registra un cambio definitivo en un campo
     */
    function registrarCambio(elemento) {
        const name = elemento.name;
        const rutaCampo = MAPEO_CAMPOS[name];

        if (rutaCampo) {
            estado.camposModificados.add(rutaCampo);
            elemento.classList.add('campo-modificado');
            elemento.classList.remove('campo-extraido');
        }
    }

    /**
     * Marca visualmente un campo como modificado
     */
    function marcarModificado(elemento) {
        const name = elemento.name;
        const rutaCampo = MAPEO_CAMPOS[name];

        if (rutaCampo && estado.valoresOriginales[rutaCampo]) {
            const original = estado.valoresOriginales[rutaCampo];
            const valorActual = elemento.value || '';
            const valorOriginal = String(original.valor || '');

            // Solo marcar si realmente cambio
            if (valorActual.trim() !== valorOriginal.trim()) {
                elemento.classList.add('campo-modificando');
            } else {
                elemento.classList.remove('campo-modificando');
            }
        }
    }

    /**
     * Marca visualmente los campos que fueron extraidos del PDF
     */
    function marcarCamposExtraidos() {
        Object.entries(estado.valoresOriginales).forEach(([ruta, datos]) => {
            if (datos.valor !== null && datos.valor !== undefined && datos.valor !== '') {
                const elemento = obtenerElementoPorRuta(ruta);
                if (elemento) {
                    elemento.classList.add('campo-extraido');

                    // Agregar tooltip con info de confianza
                    const confianza = Math.round((datos.confianza || 0) * 100);
                    elemento.title = `Extraido automaticamente (${confianza}% confianza)`;
                }
            }
        });
    }

    // API Publica del modulo
    return {
        /**
         * Inicializa el tracking con los datos extraidos del PDF
         *
         * @param {Object} datosExtraccion - JSON estructurado de la extraccion
         * @param {string} formularioSelector - Selector CSS del formulario (opcional)
         */
        inicializar: function(datosExtraccion, formularioSelector = '#formulario-poliza') {
            estado.tiempoInicio = Date.now();
            estado.formularioSelector = formularioSelector;
            estado.valoresOriginales = aplanarDatos(datosExtraccion);
            estado.camposModificados.clear();
            estado.inicializado = true;

            // Configurar listeners despues de un pequeno delay
            // para asegurar que el DOM este listo
            setTimeout(() => {
                configurarListeners();
                marcarCamposExtraidos();
            }, 100);

            console.log('TrackingExtraccion inicializado con',
                Object.keys(estado.valoresOriginales).length, 'campos');
        },

        /**
         * Genera el array de correcciones para enviar al backend
         *
         * @returns {Object} Objeto con correcciones y tiempo de edicion
         */
        generarCorrecciones: function() {
            if (!estado.inicializado) {
                console.warn('TrackingExtraccion no inicializado');
                return { correcciones: [], tiempo_edicion_segundos: 0 };
            }

            const correcciones = [];
            const tiempoEdicion = Math.round((Date.now() - estado.tiempoInicio) / 1000);

            // Revisar todos los campos originales
            Object.entries(estado.valoresOriginales).forEach(([ruta, original]) => {
                const valorActual = obtenerValorFormulario(ruta);
                const valorOriginal = original.valor;

                // Determinar tipo de cambio
                let tipoCambio = null;

                if (valorOriginal === null || valorOriginal === undefined || valorOriginal === '') {
                    // Campo estaba vacio
                    if (valorActual && valorActual.trim() !== '') {
                        tipoCambio = 'agregado_manual';
                    }
                } else {
                    // Campo tenia valor
                    if (valorActual === null || valorActual === undefined || valorActual.trim() === '') {
                        tipoCambio = 'eliminacion';
                    } else if (String(valorActual).trim() !== String(valorOriginal).trim()) {
                        tipoCambio = 'edicion';
                    }
                }

                // Solo registrar si hubo cambio
                if (tipoCambio) {
                    correcciones.push({
                        campo_sugerido: ruta,
                        campo_correcto: ruta,
                        texto_original: original.texto_original,
                        valor_extraido: valorOriginal,
                        valor_corregido: valorActual,
                        tipo_cambio: tipoCambio,
                        confianza_original: original.confianza || 0
                    });
                }
            });

            // Buscar campos nuevos que no estaban en los originales
            const formulario = document.querySelector(estado.formularioSelector);
            if (formulario) {
                const campos = formulario.querySelectorAll('input, select, textarea');
                campos.forEach(campo => {
                    const name = campo.name;
                    const ruta = MAPEO_CAMPOS[name];

                    if (ruta && !estado.valoresOriginales[ruta]) {
                        const valor = campo.value;
                        if (valor && valor.trim() !== '') {
                            correcciones.push({
                                campo_sugerido: null,
                                campo_correcto: ruta,
                                texto_original: null,
                                valor_extraido: null,
                                valor_corregido: valor,
                                tipo_cambio: 'agregado_manual',
                                confianza_original: 0
                            });
                        }
                    }
                });
            }

            return {
                correcciones: correcciones,
                tiempo_edicion_segundos: tiempoEdicion
            };
        },

        /**
         * Resetea el estado del tracking
         */
        reset: function() {
            estado.inicializado = false;
            estado.valoresOriginales = {};
            estado.camposModificados.clear();
            estado.tiempoInicio = null;

            // Quitar clases visuales
            document.querySelectorAll('.campo-extraido, .campo-modificado, .campo-modificando')
                .forEach(el => {
                    el.classList.remove('campo-extraido', 'campo-modificado', 'campo-modificando');
                    el.title = '';
                });
        },

        /**
         * Obtiene estadisticas del estado actual
         */
        obtenerEstadisticas: function() {
            return {
                inicializado: estado.inicializado,
                campos_originales: Object.keys(estado.valoresOriginales).length,
                campos_modificados: estado.camposModificados.size,
                tiempo_transcurrido: estado.tiempoInicio ?
                    Math.round((Date.now() - estado.tiempoInicio) / 1000) : 0
            };
        },

        /**
         * Verifica si el tracking esta inicializado
         */
        estaInicializado: function() {
            return estado.inicializado;
        },

        /**
         * Obtiene los valores originales
         */
        obtenerValoresOriginales: function() {
            return { ...estado.valoresOriginales };
        }
    };
})();

// Exportar para uso en modulos si es necesario
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TrackingExtraccion;
}
