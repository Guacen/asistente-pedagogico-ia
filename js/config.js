// ============================================
// CONFIGURACIÓN GLOBAL
// ============================================

const CONFIG = {
    // URL de tu backend FastAPI
    // Cambiar según tu servidor (Railway, Render, VPS, etc.)
    API_URL: 'https://tu-backend.railway.app',  // CAMBIAR ESTO
    WS_URL: 'wss://tu-backend.railway.app',     // CAMBIAR ESTO
    
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
