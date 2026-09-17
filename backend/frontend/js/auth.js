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
     * Verifica si el usuario tiene credenciales guardadas.
     *
     * Sprint auto-refresh-jwt-frontend: YA NO decide acá si el access
     * token está vencido según su propio `exp`. Antes, si había pasado,
     * esta función llamaba a logoutSilent() (que borra TAMBIÉN el
     * refresh token) sin intentar refrescar primero — eso es
     * literalmente lo que le hacía perder la sesión a un docente que
     * volvía a una pestaña vieja con el access token ya vencido (60 min)
     * pero el refresh token (30 días) todavía perfectamente vivo. La
     * validez real, y si vale la pena intentar un refresh, la decide
     * requireAuth() — acá sólo se confirma que HAY algo guardado.
     * @returns {boolean} true si hay un access token guardado
     */
    isAuthenticated() {
        return !!this.getToken();
    },

    /**
     * Protege una página requiriendo autenticación.
     *
     * Sprint auto-refresh-jwt-frontend: si el access token está vencido
     * pero HAY uno guardado, ya NO desloguea de inmediato — intenta
     * refrescarlo en background primero. La página sigue cargando y
     * renderizando normal mientras tanto (sin bloquear, sin esperar):
     * cualquier llamada a la API que dispare mientras el refresh está en
     * vuelo recibe su propio 401 y el retry reactivo de api.js la
     * reintenta sola, compartiendo el MISMO refresh en curso
     * (_refreshInFlight) — nunca dispara un segundo POST /api/auth/refresh.
     * Sólo si el refresh falla de verdad (token también inválido o
     * revocado) manda recién a login.
     * @param {string} redirectTo - URL de redirección (default: login.html)
     */
    requireAuth(redirectTo = 'login.html') {
        const token = this.getToken();
        if (!token) {
            this._irALogin(redirectTo);
            return;
        }

        const tokenData = this.parseToken(token);
        const vencido = tokenData && tokenData.exp &&
            Math.floor(Date.now() / 1000) > tokenData.exp;
        if (!vencido) {
            return; // token vigente — nada que hacer, comportamiento de siempre.
        }

        this.refreshToken().then((ok) => {
            if (!ok) {
                this.logoutSilent();
                this._irALogin(redirectTo);
            }
            // Si ok: el token ya quedó renovado en localStorage (mismas
            // keys que usa el resto de la app) — no hace falta hacer
            // nada más, la página sigue su curso normal.
        });
    },

    /**
     * Guarda la URL actual para volver después del login y redirige.
     * Extraído de requireAuth() porque ahora tiene dos puntos de salida
     * (sin token, y refresh fallido).
     * @param {string} redirectTo
     */
    _irALogin(redirectTo) {
        const currentUrl = window.location.pathname + window.location.search;
        localStorage.setItem('redirect_after_login', currentUrl);
        // replace() — no queremos que la página protegida quede en el
        // historial cuando la sesión no existe.
        window.location.replace(redirectTo);
    },
    
    /**
     * Protege una página evitando que usuarios autenticados accedan
     * Útil para páginas de login/registro
     * @param {string} redirectTo - URL de redirección (default: dashboard.html)
     */
    requireGuest(redirectTo = 'dashboard.html') {
        if (this.isAuthenticated()) {
            window.location.replace(redirectTo);
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
     * Obtiene el refresh token (sprint seguridad-avanzada — vida larga,
     * 30 días; sólo sirve para pedir un access_token nuevo).
     * @returns {string|null} Refresh token o null
     */
    getRefreshToken() {
        return localStorage.getItem('refresh_token');
    },

    /**
     * Guarda el refresh token
     * @param {string} token - Refresh token
     */
    setRefreshToken(token) {
        if (token) localStorage.setItem('refresh_token', token);
    },

    /**
     * Elimina el refresh token
     */
    removeRefreshToken() {
        localStorage.removeItem('refresh_token');
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

            // Guardar tokens — api.login() ya los guarda en localStorage
            // (mismas keys 'token'/'refresh_token' que usa Auth), pero se
            // repite acá explícitamente por claridad y porque Auth es la
            // interfaz pública que usan las páginas.
            this.setToken(response.access_token);
            this.setRefreshToken(response.refresh_token);

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
     * Cierra la sesión del usuario.
     *
     * Sprint auto-refresh-jwt-frontend: ahora SÍ avisa al backend
     * (api.logout) para blacklistear access + refresh token — antes
     * esta función sólo limpiaba localStorage, así que un token filtrado
     * seguía sirviendo hasta su expiración natural aunque el docente
     * hubiera "cerrado sesión". Best-effort y no bloqueante: no espera
     * la respuesta antes de limpiar/redirigir, así que la experiencia
     * del docente no depende de la red en ese instante.
     * @param {string} redirectTo - URL de redirección (default: login.html)
     */
    logout(redirectTo = 'login.html') {
        // Obtener usuario y refresh token ANTES de eliminarlos.
        const user = this.getUser();
        const refreshToken = this.getRefreshToken();

        if (typeof api !== 'undefined' && api.logout) {
            api.logout(refreshToken).catch((err) => {
                console.warn('No se pudo notificar el logout al backend:', err);
            });
        }

        // Limpiar datos
        this.removeToken();
        this.removeRefreshToken();
        this.removeUser();
        localStorage.removeItem('redirect_after_login');

        // Disparar evento personalizado
        this.dispatchAuthEvent('logout', { user });

        // Redirigir — replace() para no dejar la sesión anterior en historial
        if (redirectTo) {
            window.location.replace(redirectTo);
        }
    },
    
    /**
     * Cierra sesión silenciosamente (sin redirección)
     * Útil para logout desde API cuando detecta token inválido
     */
    logoutSilent() {
        this.removeToken();
        this.removeRefreshToken();
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
            window.location.replace(redirectUrl);
        } else {
            window.location.replace(defaultUrl);
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
     * Refresca el access token usando el refresh token guardado.
     * api.refreshToken() ya actualiza localStorage['token'] /
     * ['refresh_token'] internamente (misma key que usa Auth), así que
     * no hace falta sincronizar nada acá aparte de devolver el resultado.
     * @returns {Promise<boolean>} true si se refrescó correctamente
     */
    async refreshToken() {
        try {
            return await api.refreshToken();
        } catch (error) {
            console.error('Error refrescando token:', error);
            return false;
        }
    },

    /**
     * Inicia un timer para refrescar token automáticamente. Complementa
     * el refresh reactivo de api.js (que dispara ante un 401): esto
     * refresca de forma PROACTIVA antes de que el access token expire,
     * para que la mayoría de los docentes nunca lleguen a ver un 401.
     * Si el refresh falla (refresh token también vencido/inválido), no
     * fuerza logout acá — el próximo request real que reciba 401 lo hará
     * a través de api.js (que sí sabe distinguir email_no_verificado y
     * evita loops de redirección en páginas de guest).
     */
    startAutoRefresh() {
        // Verificar cada minuto
        setInterval(async () => {
            if (this.isTokenExpiringSoon()) {
                console.log('Token próximo a expirar, refrescando...');
                const ok = await this.refreshToken();
                if (!ok) {
                    console.warn('Auto-refresh falló — el próximo request forzará re-login.');
                }
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
        Auth.startAutoRefresh();
    }
});

// Interceptar errores 401 no manejados para logout automático — red de
// seguridad para llamadas que golpean al backend SIN pasar por
// api.request() (p.ej. los fetch() directos de descarga de archivos),
// que por lo tanto no pasaron por el refresh-y-reintento de
// _retryWithRefresh. Antes de este sprint esto desloguéaba directo con
// sólo ver un 401 — ahora, igual que requireAuth(), le da a la sesión la
// misma oportunidad de refrescarse antes de rendirse (si no hay refresh
// token guardado, Auth.refreshToken() resuelve a false casi al toque,
// sin red de por medio, así que el caso "login con contraseña
// incorrecta" no queda más lento).
// No re-navega si ya estamos en una página de guest (login/registro) —
// un POST /login fallido con 401 dispararía redirect a login.html →
// recarga → potencial loop si el usuario reintenta con credenciales
// inválidas.
window.addEventListener('unhandledrejection', (event) => {
    if (event.reason?.status === 401 || event.reason?.message?.includes('401')) {
        console.warn('401 no manejado detectado — intentando refrescar antes de cerrar sesión...');
        Auth.refreshToken().then((ok) => {
            if (ok) return;
            Auth.logoutSilent();
            const path = window.location.pathname;
            const enPaginaGuest = path.endsWith('/login.html') || path.endsWith('/registro.html');
            if (!enPaginaGuest) {
                window.location.replace('login.html');
            }
        });
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