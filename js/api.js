// ============================================
// CLIENTE API
// Maneja todas las llamadas al backend
// ============================================

class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }
    
    // Obtener token del localStorage
    getToken() {
        return localStorage.getItem('token');
    }
    
    // Guardar token
    setToken(token) {
        localStorage.setItem('token', token);
    }
    
    // Eliminar token
    removeToken() {
        localStorage.removeItem('token');
    }
    
    // Método genérico para hacer requests
    async request(endpoint, options = {}) {
        const token = this.getToken();
        
        const config = {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(token && { Authorization: `Bearer ${token}` }),
                ...options.headers
            }
        };
        
        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, config);
            
            if (!response.ok) {
                const error = await response.text();
                throw new Error(error || `Error ${response.status}`);
            }

            // 204 No Content (DELETE) — no body to parse
            if (response.status === 204) return null;

            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }
    
    // ==========================================
    // AUTENTICACIÓN
    // ==========================================
    
    async login(email, password) {
        const formData = new URLSearchParams();
        formData.append('username', email);
        formData.append('password', password);
        
        const response = await fetch(`${this.baseUrl}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Credenciales inválidas');
        }
        
        const data = await response.json();
        this.setToken(data.access_token);
        return data;
    }
    
    async register(nombre, email, password) {
        return this.request('/api/auth/register', {
            method: 'POST',
            body: JSON.stringify({
                nombre_completo: nombre,
                email,
                password
            })
        });
    }
    
    async getMe() {
        return this.request('/api/auth/me');
    }

    async updatePerfil(data) {
        return this.request('/api/auth/perfil', {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    async changePassword(passwordActual, passwordNuevo) {
        return this.request('/api/auth/cambiar-password', {
            method: 'POST',
            body: JSON.stringify({ password_actual: passwordActual, password_nuevo: passwordNuevo })
        });
    }

    async deleteAccount() {
        return this.request('/api/auth/cuenta', {
            method: 'DELETE'
        });
    }

    // ==========================================
    // GRUPOS
    // ==========================================
    
    async getGrupos() {
        return this.request('/api/grupos');
    }
    
    async getGrupo(id) {
        return this.request(`/api/grupos/${id}`);
    }
    
    async createGrupo(data) {
        return this.request('/api/grupos', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    
    async updateGrupo(id, data) {
        return this.request(`/api/grupos/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }
    
    async deleteGrupo(id) {
        return this.request(`/api/grupos/${id}`, {
            method: 'DELETE'
        });
    }
    
    // ==========================================
    // CHAT
    // ==========================================
    
    async getChatHistorial(grupoId, limit = 50) {
        return this.request(`/api/grupos/${grupoId}/chat/historial?limit=${limit}`);
    }
    
    // ==========================================
    // ESTUDIANTES
    // ==========================================
    
    async getEstudiantes(grupoId) {
        return this.request(`/api/grupos/${grupoId}/estudiantes`);
    }
    
    async createEstudiante(grupoId, data) {
        return this.request(`/api/grupos/${grupoId}/estudiantes`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    
    async updateEstudiante(grupoId, estudianteId, data) {
        return this.request(`/api/grupos/${grupoId}/estudiantes/${estudianteId}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }
    
    async deleteEstudiante(grupoId, estudianteId) {
        return this.request(`/api/grupos/${grupoId}/estudiantes/${estudianteId}`, {
            method: 'DELETE'
        });
    }
    
    // ==========================================
    // NOTAS
    // ==========================================
    
    async getNotas(grupoId) {
        return this.request(`/api/grupos/${grupoId}/notas`);
    }
    
    async createNota(grupoId, contenido) {
        return this.request(`/api/grupos/${grupoId}/notas`, {
            method: 'POST',
            body: JSON.stringify({ contenido })
        });
    }
    
    // ==========================================
    // ARCHIVOS
    // ==========================================
    
    async uploadArchivo(grupoId, file) {
        const formData = new FormData();
        formData.append('file', file);
        
        const token = this.getToken();
        
        const response = await fetch(`${this.baseUrl}/api/grupos/${grupoId}/archivos`, {
            method: 'POST',
            headers: {
                ...(token && { Authorization: `Bearer ${token}` })
            },
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Error al subir archivo');
        }
        
        return await response.json();
    }
    
    // ==========================================
    // INICIALIZAR IA
    // ==========================================

    async inicializarContextoIA(grupoId) {
        return this.request(`/api/grupos/${grupoId}/inicializar-ia`, { method: 'POST' });
    }

    // ==========================================
    // CALIFICACIONES
    // ==========================================

    async getCalificaciones(grupoId) {
        return this.request(`/api/grupos/${grupoId}/calificaciones`);
    }

    async createCalificacion(grupoId, data) {
        return this.request(`/api/grupos/${grupoId}/calificaciones`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async updateCalificacion(grupoId, calId, data) {
        return this.request(`/api/grupos/${grupoId}/calificaciones/${calId}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    async deleteCalificacion(grupoId, calId) {
        return this.request(`/api/grupos/${grupoId}/calificaciones/${calId}`, {
            method: 'DELETE'
        });
    }

    // Upsert: crear o actualizar nota por (estudiante, columna, periodo)
    async upsertCalificacion(grupoId, idEstudiante, idColumna, valor, periodo = 1) {
        return this.request(`/api/grupos/${grupoId}/calificaciones/upsert`, {
            method: 'POST',
            body: JSON.stringify({ id_estudiante: idEstudiante, id_columna: idColumna, valor, periodo })
        });
    }

    // ==========================================
    // COLUMNAS DE EVALUACIÓN (libro de notas)
    // ==========================================

    async getColumnas(grupoId, periodo = null) {
        const qs = periodo !== null ? `?periodo=${periodo}` : '';
        return this.request(`/api/grupos/${grupoId}/columnas${qs}`);
    }

    async createColumna(grupoId, data) {
        return this.request(`/api/grupos/${grupoId}/columnas`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async updateColumna(grupoId, colId, data) {
        return this.request(`/api/grupos/${grupoId}/columnas/${colId}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    async deleteColumna(grupoId, colId) {
        return this.request(`/api/grupos/${grupoId}/columnas/${colId}`, {
            method: 'DELETE'
        });
    }

    // ==========================================
    // SUSCRIPCIONES
    // ==========================================
    
    async getSubscription() {
        return this.request('/api/suscripciones/mi-suscripcion');
    }
    
    async createCheckoutSession(plan) {
        return this.request('/api/suscripciones/checkout', {
            method: 'POST',
            body: JSON.stringify({ plan })
        });
    }
}

// Crear instancia global
const api = new ApiClient(window.APP_CONFIG.API_URL);

// Exportar
window.api = api;
