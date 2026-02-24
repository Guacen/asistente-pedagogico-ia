// ============================================
// CONFIGURACIÓN GLOBAL
// ============================================

const CONFIG = {
    // URL del backend FastAPI
    // Se detecta automáticamente desde el origen de la página.
    // Funciona en desarrollo (localhost:8000) y producción (Railway/Hostinger) sin cambios.
    API_URL: window.location.origin,
    WS_URL: window.location.origin.replace(/^http/, 'ws'),
    
    // Stripe Public Key (para pagos)
    STRIPE_PUBLIC_KEY: 'pk_test_...', // CAMBIAR ESTO
    
    // Límites de planes
    PLANES: {
        free: {
            nombre: 'Gratis',
            mensajes_mes: 10,
            grupos_maximos: 1,
            precio: 0
        },
        pro: {
            nombre: 'Pro',
            mensajes_mes: Infinity,
            grupos_maximos: Infinity,
            precio: 9.99
        }
    },
    
    // Configuración de la app
    APP_NAME: 'Asistente Pedagógico IA',
    VERSION: '1.0.0'
};

// Hacer CONFIG global
window.APP_CONFIG = CONFIG;
