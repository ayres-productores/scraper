/**
 * Portal de Seguros - JavaScript Principal
 */

document.addEventListener('DOMContentLoaded', function() {
    // Auto-cerrar alertas después de 5 segundos
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            alert.style.opacity = '0';
            alert.style.transition = 'opacity 0.5s ease';
            setTimeout(function() {
                alert.remove();
            }, 500);
        }, 5000);
    });

    // Confirmación para acciones peligrosas
    const dangerForms = document.querySelectorAll('form[data-confirm]');
    dangerForms.forEach(function(form) {
        form.addEventListener('submit', function(e) {
            const message = form.getAttribute('data-confirm') || '¿Estás seguro?';
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // Mostrar/ocultar contraseña
    const passwordToggles = document.querySelectorAll('.password-toggle');
    passwordToggles.forEach(function(toggle) {
        toggle.addEventListener('click', function() {
            const input = this.previousElementSibling;
            if (input.type === 'password') {
                input.type = 'text';
                this.textContent = '🙈';
            } else {
                input.type = 'password';
                this.textContent = '👁';
            }
        });
    });

    // Validación de formularios en tiempo real
    const forms = document.querySelectorAll('form');
    forms.forEach(function(form) {
        const inputs = form.querySelectorAll('input[required], select[required], textarea[required]');
        inputs.forEach(function(input) {
            input.addEventListener('blur', function() {
                validateInput(this);
            });

            input.addEventListener('input', function() {
                if (this.classList.contains('invalid')) {
                    validateInput(this);
                }
            });
        });
    });

    // Función de validación de input
    function validateInput(input) {
        if (!input.value.trim()) {
            input.classList.add('invalid');
            input.classList.remove('valid');
        } else {
            input.classList.remove('invalid');
            input.classList.add('valid');
        }
    }

    // Copiar al portapapeles
    const copyButtons = document.querySelectorAll('[data-copy]');
    copyButtons.forEach(function(button) {
        button.addEventListener('click', function() {
            const text = this.getAttribute('data-copy');
            navigator.clipboard.writeText(text).then(function() {
                const originalText = button.textContent;
                button.textContent = '¡Copiado!';
                setTimeout(function() {
                    button.textContent = originalText;
                }, 2000);
            });
        });
    });

    // Manejo de dropdowns en móvil
    const userDropdown = document.querySelector('.user-dropdown');
    if (userDropdown) {
        userDropdown.addEventListener('click', function(e) {
            if (window.innerWidth <= 768) {
                e.stopPropagation();
                this.querySelector('.dropdown-menu').classList.toggle('show');
            }
        });

        document.addEventListener('click', function() {
            const menu = document.querySelector('.dropdown-menu');
            if (menu) {
                menu.classList.remove('show');
            }
        });
    }

    // Auto-resize de textareas
    const textareas = document.querySelectorAll('textarea');
    textareas.forEach(function(textarea) {
        textarea.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
    });

    // Formateo de fechas
    const dateInputs = document.querySelectorAll('input[type="date"]');
    dateInputs.forEach(function(input) {
        if (!input.value) {
            // No establecer fecha por defecto, dejar que el servidor lo maneje
        }
    });

    // Loading state para botones de formulario
    const submitButtons = document.querySelectorAll('form button[type="submit"]');
    submitButtons.forEach(function(button) {
        const form = button.closest('form');
        if (form) {
            form.addEventListener('submit', function() {
                button.disabled = true;
                const originalText = button.innerHTML;
                button.setAttribute('data-original-text', originalText);
                button.innerHTML = '<span class="loading-spinner"></span> Procesando...';

                // Re-habilitar después de 10 segundos por si hay error
                setTimeout(function() {
                    button.disabled = false;
                    button.innerHTML = originalText;
                }, 10000);
            });
        }
    });

    // Búsqueda en tablas
    const searchInputs = document.querySelectorAll('[data-table-search]');
    searchInputs.forEach(function(input) {
        const tableId = input.getAttribute('data-table-search');
        const table = document.getElementById(tableId);

        if (table) {
            input.addEventListener('input', function() {
                const searchTerm = this.value.toLowerCase();
                const rows = table.querySelectorAll('tbody tr');

                rows.forEach(function(row) {
                    const text = row.textContent.toLowerCase();
                    row.style.display = text.includes(searchTerm) ? '' : 'none';
                });
            });
        }
    });

    // Tooltips
    const tooltipElements = document.querySelectorAll('[data-tooltip]');
    tooltipElements.forEach(function(element) {
        element.addEventListener('mouseenter', function() {
            const tooltip = document.createElement('div');
            tooltip.className = 'tooltip';
            tooltip.textContent = this.getAttribute('data-tooltip');
            document.body.appendChild(tooltip);

            const rect = this.getBoundingClientRect();
            tooltip.style.top = (rect.top - tooltip.offsetHeight - 5) + 'px';
            tooltip.style.left = (rect.left + rect.width / 2 - tooltip.offsetWidth / 2) + 'px';
        });

        element.addEventListener('mouseleave', function() {
            const tooltip = document.querySelector('.tooltip');
            if (tooltip) {
                tooltip.remove();
            }
        });
    });

    // Contador de caracteres para textareas
    const charCountTextareas = document.querySelectorAll('[data-char-count]');
    charCountTextareas.forEach(function(textarea) {
        const maxChars = parseInt(textarea.getAttribute('data-char-count'));
        const counter = document.createElement('small');
        counter.className = 'char-counter text-muted';
        textarea.parentNode.appendChild(counter);

        function updateCounter() {
            const remaining = maxChars - textarea.value.length;
            counter.textContent = remaining + ' caracteres restantes';
            counter.style.color = remaining < 20 ? 'var(--danger)' : 'var(--gray)';
        }

        textarea.addEventListener('input', updateCounter);
        updateCounter();
    });

    console.log('Portal de Seguros - JavaScript cargado');
});

/**
 * Función para hacer peticiones AJAX con CSRF token
 */
function fetchWithCSRF(url, options = {}) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]');

    if (!options.headers) {
        options.headers = {};
    }

    if (csrfToken) {
        options.headers['X-CSRFToken'] = csrfToken.content;
    }

    return fetch(url, options);
}

/**
 * Función para mostrar notificaciones
 */
function showNotification(message, type = 'info') {
    const container = document.querySelector('.flash-messages') || createFlashContainer();

    const alert = document.createElement('div');
    alert.className = 'alert alert-' + type;
    alert.innerHTML = `
        <span class="alert-message">${message}</span>
        <button class="alert-close" onclick="this.parentElement.remove()">&times;</button>
    `;

    container.appendChild(alert);

    setTimeout(function() {
        alert.style.opacity = '0';
        alert.style.transition = 'opacity 0.5s ease';
        setTimeout(function() {
            alert.remove();
        }, 500);
    }, 5000);
}

function createFlashContainer() {
    const container = document.createElement('div');
    container.className = 'flash-messages';
    const mainContent = document.querySelector('.main-content');
    mainContent.insertBefore(container, mainContent.firstChild);
    return container;
}

/**
 * Función para formatear fechas
 */
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('es-ES', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Función para formatear tamaños de archivo
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}
