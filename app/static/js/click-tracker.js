/**
 * Click Tracker - Sistema de tracking de uso para Flask
 *
 * Módulo reutilizable que registra clics en elementos interactivos
 * y los envía en batch al servidor para análisis de uso.
 *
 * Uso:
 *   ClickTracker.init(config);  // Inicializar con config opcional
 *   ClickTracker.track(eventData);  // Trackear evento manualmente
 *
 * Configuración (via window.USAGE_TRACKER_CONFIG o parámetro):
 *   endpoint: '/api/analytics/track'
 *   batchSize: 10
 *   batchTimeout: 5000
 *   trackElements: 'a, button, .btn, ...'
 *   excludePaths: ['/static/', '/api/analytics/']
 *   enabled: true
 */
const ClickTracker = (function() {
    'use strict';

    // Configuración por defecto
    const defaultConfig = {
        endpoint: '/api/analytics/track',
        batchSize: 10,
        batchTimeout: 5000,
        trackElements: 'a, button, .btn, .nav-link, [data-track], input[type="submit"]',
        excludePaths: ['/static/', '/api/analytics/', '/favicon'],
        excludeElements: ['.alert-close', '.modal-close', '[data-no-track]'],
        enabled: true,
        debug: false
    };

    let config = { ...defaultConfig };
    let queue = [];
    let timer = null;
    let initialized = false;

    /**
     * Log de debug (solo si debug está habilitado)
     */
    function log(...args) {
        if (config.debug) {
            console.log('[ClickTracker]', ...args);
        }
    }

    /**
     * Verifica si la página actual debe ser excluida del tracking
     */
    function isExcludedPath() {
        const path = window.location.pathname;
        return config.excludePaths.some(excluded => path.startsWith(excluded));
    }

    /**
     * Verifica si un elemento debe ser excluido del tracking
     */
    function isExcludedElement(element) {
        return config.excludeElements.some(selector => {
            try {
                return element.matches(selector);
            } catch (e) {
                return false;
            }
        });
    }

    /**
     * Obtiene información del elemento clickeado
     */
    function getElementInfo(element, event) {
        // Obtener texto visible, limpiando espacios
        let texto = '';
        if (element.textContent) {
            texto = element.textContent.trim().replace(/\s+/g, ' ').substring(0, 100);
        }
        // Si no hay texto, usar title, aria-label o value
        if (!texto) {
            texto = element.title || element.getAttribute('aria-label') ||
                    element.value || element.placeholder || '';
        }

        return {
            pagina: window.location.pathname,
            elemento: element.tagName.toLowerCase(),
            elemento_id: element.id || null,
            elemento_texto: texto.substring(0, 100),
            accion: 'click',
            posicion_x: Math.round(event.clientX),
            posicion_y: Math.round(event.clientY),
            viewport_width: window.innerWidth,
            viewport_height: window.innerHeight,
            timestamp: Date.now()
        };
    }

    /**
     * Maneja el evento de clic
     */
    function handleClick(event) {
        if (!config.enabled || isExcludedPath()) return;

        // Buscar el elemento trackeable más cercano
        const target = event.target.closest(config.trackElements);
        if (!target) return;

        // Verificar si está excluido
        if (isExcludedElement(target)) return;

        const eventData = getElementInfo(target, event);
        queue.push(eventData);

        log('Evento capturado:', eventData);

        // Flush si alcanzamos el tamaño del batch
        if (queue.length >= config.batchSize) {
            flush();
        } else if (!timer) {
            // Programar flush después del timeout
            timer = setTimeout(flush, config.batchTimeout);
        }
    }

    /**
     * Envía los eventos acumulados al servidor
     */
    function flush() {
        if (queue.length === 0) return;

        const batch = [...queue];
        queue = [];

        if (timer) {
            clearTimeout(timer);
            timer = null;
        }

        log('Enviando batch de', batch.length, 'eventos');

        // Usar sendBeacon para envío no bloqueante
        const payload = JSON.stringify({ events: batch });

        if (navigator.sendBeacon) {
            const sent = navigator.sendBeacon(config.endpoint, payload);
            if (!sent) {
                // Fallback a fetch si sendBeacon falla
                fetchFallback(payload);
            }
        } else {
            fetchFallback(payload);
        }
    }

    /**
     * Fallback usando fetch para navegadores sin sendBeacon
     */
    function fetchFallback(payload) {
        fetch(config.endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: payload,
            keepalive: true
        }).catch(err => {
            log('Error enviando eventos:', err);
        });
    }

    /**
     * API pública
     */
    return {
        /**
         * Inicializa el tracker con configuración opcional
         * @param {Object} userConfig - Configuración personalizada
         */
        init: function(userConfig = {}) {
            if (initialized) {
                log('Ya inicializado, ignorando');
                return;
            }

            // Merge con config del servidor (si existe)
            const serverConfig = window.USAGE_TRACKER_CONFIG || {};
            config = { ...defaultConfig, ...serverConfig, ...userConfig };

            if (!config.enabled) {
                log('Tracking deshabilitado');
                return;
            }

            // Registrar listener de clics
            document.addEventListener('click', handleClick, { capture: true });

            // Enviar eventos pendientes antes de cerrar la página
            window.addEventListener('beforeunload', flush);

            // Enviar eventos pendientes cuando la página pierde el foco
            document.addEventListener('visibilitychange', function() {
                if (document.visibilityState === 'hidden') {
                    flush();
                }
            });

            initialized = true;
            log('Inicializado con config:', config);
        },

        /**
         * Trackea un evento manualmente
         * @param {Object} eventData - Datos del evento
         */
        track: function(eventData) {
            if (!config.enabled) return;

            const data = {
                pagina: eventData.pagina || window.location.pathname,
                elemento: eventData.elemento || 'custom',
                elemento_id: eventData.elemento_id || null,
                elemento_texto: (eventData.elemento_texto || '').substring(0, 100),
                accion: eventData.accion || 'custom',
                posicion_x: eventData.posicion_x || null,
                posicion_y: eventData.posicion_y || null,
                viewport_width: window.innerWidth,
                viewport_height: window.innerHeight,
                timestamp: Date.now()
            };

            queue.push(data);
            log('Evento manual:', data);

            if (queue.length >= config.batchSize) {
                flush();
            }
        },

        /**
         * Fuerza el envío de eventos pendientes
         */
        flush: flush,

        /**
         * Habilita o deshabilita el tracking
         * @param {boolean} enabled
         */
        setEnabled: function(enabled) {
            config.enabled = enabled;
            log('Tracking', enabled ? 'habilitado' : 'deshabilitado');
        },

        /**
         * Obtiene la configuración actual
         * @returns {Object}
         */
        getConfig: function() {
            return { ...config };
        },

        /**
         * Obtiene cantidad de eventos en cola
         * @returns {number}
         */
        getPendingCount: function() {
            return queue.length;
        }
    };
})();

// Auto-inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', function() {
    ClickTracker.init();
});
