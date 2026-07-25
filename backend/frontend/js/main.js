// ============================================
// FUNCIONES COMUNES Y UTILIDADES
// ============================================

// Formatear fecha
function formatearFecha(fecha) {
    const date = new Date(fecha);
    return date.toLocaleDateString('es-CO', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

// Formatear hora
function formatearHora(fecha) {
    const date = new Date(fecha);
    return date.toLocaleTimeString('es-CO', {
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Mostrar alerta
function mostrarAlerta(mensaje, tipo = 'info') {
    const alertContainer = document.getElementById('alert-container');
    if (!alertContainer) {
        console.warn('No se encontró contenedor de alertas');
        return;
    }
    
    const colores = {
        'success': 'bg-green-100 border-green-400 text-green-700',
        'error': 'bg-red-100 border-red-400 text-red-700',
        'warning': 'bg-yellow-100 border-yellow-400 text-yellow-700',
        'info': 'bg-blue-100 border-blue-400 text-blue-700'
    };
    
    const alert = document.createElement('div');
    alert.className = `${colores[tipo]} border px-4 py-3 rounded mb-4 fade-in`;
    alert.innerHTML = `
        <p>${mensaje}</p>
        <button onclick="this.parentElement.remove()" class="absolute top-0 right-0 px-4 py-3">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    alertContainer.appendChild(alert);
    
    // Auto-cerrar después de 5 segundos
    setTimeout(() => {
        alert.remove();
    }, 5000);
}

// Confirmar acción
function confirmar(mensaje) {
    return confirm(mensaje);
}

// Modal simple
function mostrarModal(titulo, contenido, opciones = {}) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h3 class="modal-title">${titulo}</h3>
                <button class="modal-close" onclick="cerrarModal(this)">×</button>
            </div>
            <div class="modal-body">
                ${contenido}
            </div>
            ${opciones.botones ? `
            <div class="modal-footer mt-4 flex justify-end space-x-2">
                ${opciones.botones.map(btn => `
                    <button class="btn ${btn.clase || 'btn-primary'}" onclick="${btn.onclick}">
                        ${btn.texto}
                    </button>
                `).join('')}
            </div>
            ` : ''}
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Cerrar al hacer click fuera
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

function cerrarModal(btn) {
    btn.closest('.modal-overlay').remove();
}

// Loading overlay
function mostrarLoading(mensaje = 'Cargando...') {
    const loading = document.createElement('div');
    loading.id = 'loading-overlay';
    loading.className = 'loading-overlay';
    loading.innerHTML = `
        <div class="text-center">
            <div class="spinner mx-auto mb-4"></div>
            <p class="text-white">${mensaje}</p>
        </div>
    `;
    document.body.appendChild(loading);
}

function ocultarLoading() {
    const loading = document.getElementById('loading-overlay');
    if (loading) {
        loading.remove();
    }
}

// Validar email
function esEmailValido(email) {
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return regex.test(email);
}

// Validar contraseña (mínimo 8 caracteres)
function esPasswordValida(password) {
    return password.length >= 8;
}

// Copiar al portapapeles
async function copiarAlPortapapeles(texto) {
    try {
        await navigator.clipboard.writeText(texto);
        mostrarAlerta('Copiado al portapapeles', 'success');
    } catch (error) {
        // Fallback para navegadores antiguos
        const textarea = document.createElement('textarea');
        textarea.value = texto;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        mostrarAlerta('Copiado al portapapeles', 'success');
    }
}

// Descargar archivo
function descargarArchivo(url, nombreArchivo) {
    const a = document.createElement('a');
    a.href = url;
    a.download = nombreArchivo;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

// Leer archivo como base64
function leerArchivoComoBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

// Formatear número con separador de miles
function formatearNumero(numero) {
    return new Intl.NumberFormat('es-CO').format(numero);
}

// Truncar texto
function truncarTexto(texto, longitud = 100) {
    if (texto.length <= longitud) return texto;
    return texto.substring(0, longitud) + '...';
}

// Debounce (útil para búsquedas)
function debounce(func, wait = 300) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Throttle (útil para scroll events)
function throttle(func, limit = 100) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Obtener parámetro de URL
function obtenerParametroURL(nombre) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(nombre);
}

// Redirigir con parámetros
function redirigirConParams(url, params) {
    const searchParams = new URLSearchParams(params);
    window.location.href = `${url}?${searchParams.toString()}`;
}

// Capitalizar primera letra
function capitalizar(texto) {
    return texto.charAt(0).toUpperCase() + texto.slice(1).toLowerCase();
}

// Generar ID único
function generarId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

// Escapar HTML (prevenir XSS)
function escaparHTML(texto) {
    const div = document.createElement('div');
    div.textContent = texto;
    return div.innerHTML;
}

// Verificar si está en móvil
function esMobil() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
}

// Scroll suave a elemento
function scrollA(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// Formatear tamaño de archivo
function formatearTamañoArchivo(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Manejo de errores global
window.addEventListener('error', (event) => {
    console.error('Error global:', event.error);
    // Enviar a Sentry si está configurado
    if (window.Sentry) {
        Sentry.captureException(event.error);
    }
});

// Manejo de promesas rechazadas no manejadas
window.addEventListener('unhandledrejection', (event) => {
    console.error('Promesa rechazada no manejada:', event.reason);
    // Enviar a Sentry si está configurado
    if (window.Sentry) {
        Sentry.captureException(event.reason);
    }
});

// Detectar cuando el usuario pierde conexión
window.addEventListener('offline', () => {
    mostrarAlerta('Se perdió la conexión a internet', 'warning');
});

window.addEventListener('online', () => {
    mostrarAlerta('Conexión restaurada', 'success');
});

// Exportar funciones globalmente
window.Utils = {
    formatearFecha,
    formatearHora,
    mostrarAlerta,
    confirmar,
    mostrarModal,
    cerrarModal,
    mostrarLoading,
    ocultarLoading,
    esEmailValido,
    esPasswordValida,
    copiarAlPortapapeles,
    descargarArchivo,
    leerArchivoComoBase64,
    formatearNumero,
    truncarTexto,
    debounce,
    throttle,
    obtenerParametroURL,
    redirigirConParams,
    capitalizar,
    generarId,
    escaparHTML,
    esMobil,
    scrollA,
    formatearTamañoArchivo
};
