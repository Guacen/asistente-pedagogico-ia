// ============================================
// AUTH.JS - GESTIÓN DE AUTENTICACIÓN
// ============================================

/**
 * Objeto principal de autenticación
 * Maneja login, logout, verificación de sesión, etc.
 */
const Auth = {
    
    // ==========================================
    // VERIFICACIÓN DE AUTENTICACIÓN
    // ==========================================
    
    /**
     * Verifica si el usuario está autenticado
     * @returns {boolean} true si hay token válido
     */
    isAuthenticated() {
        const token = this.getToken();
        
        if (!token) {
            return false;
        }
        
        // Verificar si el token ha expirado (opcional)
        const tokenData = this.parseToken(token);
        if (tokenData && tokenData.exp) {
            const now = Math.floor(Date.now() / 1000);
            if (now > tokenData.exp) {
                // Token expirado
                this.logout();
                return false;
            }
        }
        
        return true;
    },
    
    /**
     * Protege una página requiriendo autenticación
     * Si no está autenticado, redirige a login
     * @param {string} redirectTo - URL de redirección (default: login.html)
     */
    requireAuth(redirectTo = 'login.html') {
        if (!this.isAuthenticated()) {
            // Guardar URL actual para volver después del login
            const currentUrl = window.location.pathname + window.location.search;
            localStorage.setItem('redirect_after_login', currentUrl);
            
            // Redirigir a login
            window.location.href = redirectTo;
        }
    },
    
    /**
     * Protege una página evitando que usuarios autenticados accedan
     * Útil para páginas de login/registro
     * @param {string} redirectTo - URL de redirección (default: dashboard.html)
     */
    requireGuest(redirectTo = 'dashboard.html') {
        if (this.isAuthenticated()) {
            window.location.href = redirectTo;
        }
    },
    
    // ==========================================
    // MANEJO DE TOKENS
    // ==========================================
    
    /**
     * Obtiene el token de autenticación
     * @returns {string|null} Token JWT o null
     */
    getToken() {
        return localStorage.getItem('token');
    },
    
    /**
     * Guarda el token de autenticación
     * @param {string} token - Token JWT
     */
    setToken(token) {
        localStorage.setItem('token', token);
    },
    
    /**
     * Elimina el token de autenticación
     */
    removeToken() {
        localStorage.removeItem('token');
    },
    
    /**
     * Parsea un token JWT (sin verificar firma)
     * @param {string} token - Token JWT
     * @returns {object|null} Payload del token o null
     */
    parseToken(token) {
        try {
            const base64Url = token.split('.')[1];
            const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
            const jsonPayload = decodeURIComponent(
                atob(base64)
                    .split('')
                    .map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
                    .join('')
            );
            return JSON.parse(jsonPayload);
        } catch (error) {
            console.error('Error parseando token:', error);
            return null;
        }
    },
    
    // ==========================================
    // USUARIO ACTUAL
    // ==========================================
    
    /**
     * Obtiene el usuario actual desde localStorage
     * @returns {object|null} Objeto de usuario o null
     */
    getUser() {
        const userStr = localStorage.getItem('user');
        if (!userStr) return null;
        
        try {
            return JSON.parse(userStr);
        } catch (error) {
            console.error('Error parseando usuario:', error);
            return null;
        }
    },
    
    /**
     * Guarda el usuario en localStorage
     * @param {object} user - Objeto de usuario
     */
    setUser(user) {
        localStorage.setItem('user', JSON.stringify(user));
    },
    
    /**
     * Elimina el usuario de localStorage
     */
    removeUser() {
        localStorage.removeItem('user');
    },
    
    /**
     * Obtiene el usuario actual desde la API (fresco)
     * @returns {Promise<object>} Usuario actualizado
     */
    async fetchUser() {
        try {
            const user = await api.getMe();
            this.setUser(user);
            return user;
        } catch (error) {
            console.error('Error obteniendo usuario:', error);
            throw error;
        }
    },
    
    /**
     * Obtiene el ID del usuario actual
     * @returns {string|null} ID del usuario o null
     */
    getUserId() {
        const user = this.getUser();
        return user ? user.id_docente : null;
    },
    
    /**
     * Obtiene el nombre del usuario actual
     * @returns {string} Nombre del usuario o 'Usuario'
     */
    getUserName() {
        const user = this.getUser();
        return user ? user.nombre_completo : 'Usuario';
    },
    
    /**
     * Obtiene el email del usuario actual
     * @returns {string|null} Email del usuario o null
     */
    getUserEmail() {
        const user = this.getUser();
        return user ? user.email : null;
    },
    
    /**
     * Obtiene la inicial del nombre para avatares
     * @returns {string} Primera letra del nombre
     */
    getUserInitial() {
        const name = this.getUserName();
        return name.charAt(0).toUpperCase();
    },
    
    // ==========================================
    // LOGIN / LOGOUT
    // ==========================================
    
    /**
     * Realiza el login del usuario
     * @param {string} email - Email del usuario
     * @param {string} password - Contraseña
     * @returns {Promise<object>} Datos de respuesta del login
     */
    async login(email, password) {
        try {
            // Llamar a API de login
            const response = await api.login(email, password);
            
            // Guardar token
            this.setToken(response.access_token);
            
            // Obtener y guardar usuario
            const user = await api.getMe();
            this.setUser(user);
            
            // Disparar evento personalizado
            this.dispatchAuthEvent('login', { user });
            
            return { success: true, user };
            
        } catch (error) {
            console.error('Error en login:', error);
            throw error;
        }
    },
    
    /**
     * Cierra la sesión del usuario
     * @param {string} redirectTo - URL de redirección (default: login.html)
     */
    logout(redirectTo = 'login.html') {
        // Obtener usuario antes de eliminar
        const user = this.getUser();
        
        // Limpiar datos
        this.removeToken();
        this.removeUser();
        localStorage.removeItem('redirect_after_login');
        
        // Disparar evento personalizado
        this.dispatchAuthEvent('logout', { user });
        
        // Redirigir
        if (redirectTo) {
            window.location.href = redirectTo;
        }
    },
    
    /**
     * Cierra sesión silenciosamente (sin redirección)
     * Útil para logout desde API cuando detecta token inválido
     */
    logoutSilent() {
        this.removeToken();
        this.removeUser();
        localStorage.removeItem('redirect_after_login');
    },
    
    // ==========================================
    // REGISTRO
    // ==========================================
    
    /**
     * Registra un nuevo usuario
     * @param {object} data - Datos del usuario (nombre, email, password)
     * @returns {Promise<object>} Datos de respuesta
     */
    async register(data) {
        try {
            // Registrar
            await api.register(data.nombre, data.email, data.password);
            
            // Auto-login
            return await this.login(data.email, data.password);
            
        } catch (error) {
            console.error('Error en registro:', error);
            throw error;
        }
    },
    
    // ==========================================
    // REDIRECCIÓN POST-LOGIN
    // ==========================================
    
    /**
     * Redirige a la URL guardada después del login
     * Si no hay URL guardada, va a dashboard
     * @param {string} defaultUrl - URL por defecto (default: dashboard.html)
     */
    redirectAfterLogin(defaultUrl = 'dashboard.html') {
        const redirectUrl = localStorage.getItem('redirect_after_login');
        
        if (redirectUrl && redirectUrl !== '/login.html') {
            localStorage.removeItem('redirect_after_login');
            window.location.href = redirectUrl;
        } else {
            window.location.href = defaultUrl;
        }
    },
    
    // ==========================================
    // SUSCRIPCIÓN
    // ==========================================
    
    /**
     * Obtiene la suscripción del usuario
     * @returns {Promise<object>} Datos de suscripción
     */
    async getSubscription() {
        try {
            return await api.getSubscription();
        } catch (error) {
            console.error('Error obteniendo suscripción:', error);
            return null;
        }
    },
    
    /**
     * Verifica si el usuario tiene plan Pro
     * @returns {Promise<boolean>} true si es Pro
     */
    async isPro() {
        const subscription = await this.getSubscription();
        return subscription && subscription.plan === 'pro';
    },
    
    /**
     * Verifica si el usuario tiene plan Free
     * @returns {Promise<boolean>} true si es Free
     */
    async isFree() {
        const subscription = await this.getSubscription();
        return !subscription || subscription.plan === 'free';
    },
    
    /**
     * Verifica si el usuario puede usar una función (por límites de plan)
     * @param {string} feature - Nombre de la función (ej: 'create_group')
     * @returns {Promise<boolean>} true si puede usar la función
     */
    async canUseFeature(feature) {
        const subscription = await this.getSubscription();
        
        if (!subscription) return false;
        
        switch (feature) {
            case 'create_group':
                const gruposCreados = subscription.uso_actual?.grupos_creados || 0;
                const gruposLimite = subscription.limites?.grupos_maximos || 1;
                return gruposLimite === Infinity || gruposCreados < gruposLimite;
                
            case 'send_message':
                const mensajesUsados = subscription.uso_actual?.mensajes_ia_este_mes || 0;
                const mensajesLimite = subscription.limites?.mensajes_ia_mes || 10;
                return mensajesLimite === Infinity || mensajesUsados < mensajesLimite;
                
            case 'advanced_analytics':
                return subscription.limites?.funciones_avanzadas === true;
                
            default:
                return true;
        }
    },
    
    // ==========================================
    // EVENTOS PERSONALIZADOS
    // ==========================================
    
    /**
     * Dispara un evento personalizado de autenticación
     * @param {string} eventName - Nombre del evento (login, logout)
     * @param {object} detail - Datos adicionales del evento
     */
    dispatchAuthEvent(eventName, detail = {}) {
        const event = new CustomEvent(`auth:${eventName}`, {
            detail,
            bubbles: true,
            cancelable: true
        });
        
        window.dispatchEvent(event);
    },
    
    /**
     * Escucha eventos de autenticación
     * @param {string} eventName - Nombre del evento (login, logout)
     * @param {function} callback - Función a ejecutar
     */
    onAuthEvent(eventName, callback) {
        window.addEventListener(`auth:${eventName}`, (e) => {
            callback(e.detail);
        });
    },
    
    // ==========================================
    // HELPERS DE UI
    // ==========================================
    
    /**
     * Actualiza el UI con información del usuario
     * Busca elementos con data-auth-* y los actualiza
     */
    updateAuthUI() {
        const user = this.getUser();
        
        if (!user) return;
        
        // Actualizar nombre
        document.querySelectorAll('[data-auth-name]').forEach(el => {
            el.textContent = user.nombre_completo || 'Usuario';
        });
        
        // Actualizar email
        document.querySelectorAll('[data-auth-email]').forEach(el => {
            el.textContent = user.email || '';
        });
        
        // Actualizar inicial (avatar)
        document.querySelectorAll('[data-auth-initial]').forEach(el => {
            el.textContent = this.getUserInitial();
        });
        
        // Mostrar/ocultar elementos según autenticación
        document.querySelectorAll('[data-auth-show]').forEach(el => {
            el.classList.remove('hidden');
        });
        
        document.querySelectorAll('[data-auth-hide]').forEach(el => {
            el.classList.add('hidden');
        });
    },
    
    /**
     * Agrega event listener al botón de logout
     * @param {string} selector - Selector CSS del botón (default: '#logout-btn, .logout-btn')
     */
    initLogoutButtons(selector = '#logout-btn, .logout-btn') {
        document.querySelectorAll(selector).forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                
                if (confirm('¿Cerrar sesión?')) {
                    this.logout();
                }
            });
        });
    },
    
    // ==========================================
    // VALIDACIONES
    // ==========================================
    
    /**
     * Valida formato de email
     * @param {string} email - Email a validar
     * @returns {boolean} true si es válido
     */
    isValidEmail(email) {
        const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return regex.test(email);
    },
    
    /**
     * Valida fortaleza de contraseña
     * @param {string} password - Contraseña a validar
     * @returns {object} Resultado de validación
     */
    validatePassword(password) {
        return {
            length: password.length >= 8,
            hasNumber: /\d/.test(password),
            hasLower: /[a-z]/.test(password),
            hasUpper: /[A-Z]/.test(password),
            hasSpecial: /[!@#$%^&*(),.?":{}|<>]/.test(password),
            isValid: password.length >= 8
        };
    },
    
    // ==========================================
    // UTILIDADES
    // ==========================================
    
    /**
     * Obtiene tiempo restante del token
     * @returns {number|null} Segundos restantes o null
     */
    getTokenTimeRemaining() {
        const token = this.getToken();
        if (!token) return null;
        
        const tokenData = this.parseToken(token);
        if (!tokenData || !tokenData.exp) return null;
        
        const now = Math.floor(Date.now() / 1000);
        const remaining = tokenData.exp - now;
        
        return remaining > 0 ? remaining : 0;
    },
    
    /**
     * Verifica si el token está próximo a expirar
     * @param {number} threshold - Umbral en segundos (default: 300 = 5 min)
     * @returns {boolean} true si está próximo a expirar
     */
    isTokenExpiringSoon(threshold = 300) {
        const remaining = this.getTokenTimeRemaining();
        return remaining !== null && remaining < threshold;
    },
    
    /**
     * Refresca el token (si el backend lo soporta)
     * @returns {Promise<boolean>} true si se refrescó correctamente
     */
    async refreshToken() {
        try {
            // TODO: Implementar endpoint de refresh token
            // const response = await api.refreshToken();
            // this.setToken(response.access_token);
            // return true;
            
            console.warn('Refresh token no implementado');
            return false;
            
        } catch (error) {
            console.error('Error refrescando token:', error);
            return false;
        }
    },
    
    /**
     * Inicia un timer para refrescar token automáticamente
     */
    startAutoRefresh() {
        // Verificar cada minuto
        setInterval(async () => {
            if (this.isTokenExpiringSoon()) {
                console.log('Token próximo a expirar, refrescando...');
                await this.refreshToken();
            }
        }, 60000); // 1 minuto
    }
};

// ==========================================
// EXPORTAR GLOBALMENTE
// ==========================================

window.Auth = Auth;

// ==========================================
// INICIALIZACIÓN AUTOMÁTICA
// ==========================================

// Actualizar UI cuando carga la página
document.addEventListener('DOMContentLoaded', () => {
    if (Auth.isAuthenticated()) {
        Auth.updateAuthUI();
        Auth.initLogoutButtons();
    }
});

// Interceptar errores 401 de la API para logout automático
window.addEventListener('unhandledrejection', (event) => {
    if (event.reason?.status === 401 || event.reason?.message?.includes('401')) {
        console.warn('Token inválido detectado, cerrando sesión...');
        Auth.logoutSilent();
        window.location.href = 'login.html';
    }
});

// ==========================================
// HELPERS RÁPIDOS (aliases)
// ==========================================

/**
 * Verifica autenticación (alias corto)
 */
function requireAuth() {
    Auth.requireAuth();
}

/**
 * Requiere que NO esté autenticado (alias corto)
 */
function requireGuest() {
    Auth.requireGuest();
}

/**
 * Obtiene usuario actual (alias corto)
 */
function getUser() {
    return Auth.getUser();
}

/**
 * Cierra sesión (alias corto)
 */
function logout() {
    Auth.logout();
}

// ==========================================
// CONSOLE LOG DE DESARROLLO
// ==========================================

if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    console.log('🔐 Auth.js cargado');
    console.log('Usuario autenticado:', Auth.isAuthenticated());
    
    if (Auth.isAuthenticated()) {
        console.log('Usuario:', Auth.getUser());
        console.log('Token expira en:', Auth.getTokenTimeRemaining(), 'segundos');
    }
}