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
    
    async register(nombre, email, password, consentimientoDatos = false) {
        return this.request('/api/auth/register', {
            method: 'POST',
            body: JSON.stringify({
                nombre_completo: nombre,
                email,
                password,
                consentimiento_datos: consentimientoDatos,
            })
        });
    }

    async getMe() {
        return this.request('/api/auth/me');
    }

    async getMeRaw() {
        // Igual que getMe pero NO exige email verificado — la usan las
        // pantallas del flujo de verificación para saber quién es el
        // docente sin dispararse el 401 code=email_no_verificado.
        return this.request('/api/auth/me-raw');
    }

    async verificarEmail(token) {
        // GET con querystring; el backend responde 200 + {verificado:true}
        return this.request(`/api/auth/verificar-email?token=${encodeURIComponent(token)}`);
    }

    async reenviarVerificacion(email) {
        return this.request('/api/auth/reenviar-verificacion', {
            method: 'POST',
            body: JSON.stringify({ email }),
        });
    }

    async aceptarConsentimiento() {
        // Endpoint para grandfathered: docentes con consentimiento_datos = NULL
        // aceptan la Ley 1581 vía banner post-login.
        return this.request('/api/auth/aceptar-consentimiento', {
            method: 'POST',
            body: JSON.stringify({ aceptado: true }),
        });
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

    async forgotPassword(email) {
        return this.request('/api/auth/forgot-password', {
            method: 'POST',
            body: JSON.stringify({ email }),
        });
    }

    async resetPassword(token, passwordNuevo) {
        return this.request(`/api/auth/reset-password?token=${encodeURIComponent(token)}`, {
            method: 'POST',
            body: JSON.stringify({ password_nuevo: passwordNuevo }),
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
    
    async getChatHistorial(grupoId, limit = 50, modo = null, idEstudiante = null, idSesion = null) {
        // Fase B: filtra por modo (planeacion/socioemocional/calificacion/piar).
        // Fase C: idEstudiante filtra PIAR — cada estudiante tiene su propia conversación.
        // Sprint sesiones: idSesion tiene precedencia — cuando se pasa, el backend
        // ignora modo/idEstudiante y devuelve sólo los mensajes de esa sesión.
        const params = new URLSearchParams({ limit: String(limit) });
        if (idSesion) params.set('id_sesion', idSesion);
        else {
            if (modo) params.set('modo', modo);
            if (idEstudiante) params.set('id_estudiante', idEstudiante);
        }
        return this.request(`/api/grupos/${grupoId}/chat/historial?${params.toString()}`);
    }

    // ==========================================
    // SESIONES TEMÁTICAS (sprint sesiones)
    // ==========================================

    async listarSesiones(grupoId, { modo = null, idEstudiante = null, incluirArchivadas = false } = {}) {
        const params = new URLSearchParams();
        if (modo) params.set('modo', modo);
        if (idEstudiante) params.set('id_estudiante', idEstudiante);
        if (incluirArchivadas) params.set('incluir_archivadas', 'true');
        const qs = params.toString();
        return this.request(`/api/grupos/${grupoId}/sesiones${qs ? '?' + qs : ''}`);
    }

    async crearSesion(grupoId, modo, { titulo = null, idEstudiante = null } = {}) {
        const body = { modo };
        if (titulo) body.titulo = titulo;
        if (idEstudiante) body.id_estudiante = idEstudiante;
        return this.request(`/api/grupos/${grupoId}/sesiones`, {
            method: 'POST',
            body: JSON.stringify(body),
        });
    }

    async archivarSesion(idSesion) {
        return this.request(`/api/sesiones/${encodeURIComponent(idSesion)}/archivar`, {
            method: 'PUT',
        });
    }

    async actualizarTituloSesion(idSesion, titulo) {
        return this.request(`/api/sesiones/${encodeURIComponent(idSesion)}/titulo`, {
            method: 'PUT',
            body: JSON.stringify({ titulo }),
        });
    }

    // ==========================================
    // PIAR (Fase C)
    // ==========================================

    async listarPiarsEstudiante(idEstudiante) {
        return this.request(`/api/piar/estudiante/${encodeURIComponent(idEstudiante)}`);
    }

    async crearPiar(idEstudiante, periodo, anio = null) {
        const body = { id_estudiante: idEstudiante, periodo };
        if (anio) body.anio = anio;
        return this.request('/api/piar/', {
            method: 'POST',
            body: JSON.stringify(body),
        });
    }

    async aprobarPiar(piarId) {
        return this.request(`/api/piar/${encodeURIComponent(piarId)}/aprobar`, {
            method: 'PUT',
        });
    }

    async descargarPiarDocx(piarId) {
        return this._descargarBlob(
            `/api/piar/${encodeURIComponent(piarId)}/docx`,
            `PIAR_${piarId}.docx`,
        );
    }

    // ==========================================
    // MALLA CURRICULAR (Derechos Básicos de Aprendizaje — MEN)
    // ==========================================

    async getAsignaturasMalla() {
        return this.request('/api/malla/asignaturas');
    }

    async getDbas(asignatura, grado) {
        const qs = new URLSearchParams({ asignatura, grado }).toString();
        return this.request(`/api/malla/dbas?${qs}`);
    }

    async getMallaGrupo(idGrupo, asignatura) {
        const qs = new URLSearchParams({ asignatura }).toString();
        return this.request(`/api/malla/grupo/${encodeURIComponent(idGrupo)}?${qs}`);
    }

    async generarMalla(idGrupo, asignatura, periodos = 4) {
        return this.request('/api/malla/generar', {
            method: 'POST',
            body: JSON.stringify({ id_grupo: idGrupo, asignatura, periodos }),
        });
    }

    async marcarSeguimientoDba(idGrupo, idDba, periodo, cubierto, referencia = '') {
        return this.request('/api/malla/seguimiento', {
            method: 'POST',
            body: JSON.stringify({ id_grupo: idGrupo, id_dba: idDba, periodo, cubierto, referencia }),
        });
    }

    async getProgresoMalla(idGrupo, asignatura, periodo = null) {
        const params = { asignatura };
        if (periodo != null) params.periodo = periodo;
        const qs = new URLSearchParams(params).toString();
        return this.request(`/api/malla/progreso/${encodeURIComponent(idGrupo)}?${qs}`);
    }

    // ==========================================
    // OBSERVACIONES (Observador del Alumno + seguimiento)
    // ==========================================

    async crearObservacion(data) {
        return this.request('/api/observaciones', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async listarObservaciones(params = {}) {
        const qs = new URLSearchParams(
            Object.fromEntries(Object.entries(params).filter(([, v]) => v))
        ).toString();
        return this.request(`/api/observaciones${qs ? '?' + qs : ''}`);
    }

    async getObservacion(idObservacion) {
        return this.request(`/api/observaciones/${encodeURIComponent(idObservacion)}`);
    }

    async actualizarObservacion(idObservacion, data) {
        return this.request(`/api/observaciones/${encodeURIComponent(idObservacion)}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }

    async seguimientosPendientes() {
        return this.request('/api/observaciones/seguimientos-pendientes');
    }

    async descargarObservacionDocx(idObservacion) {
        return this._descargarBlob(
            `/api/observaciones/${encodeURIComponent(idObservacion)}/exportar`,
            `observacion_${idObservacion}.docx`,
            'POST',
        );
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

    // Bulk import por CSV. Upsert por codigo_estudiante dentro del grupo.
    async importarEstudiantesCsv(grupoId, file) {
        const fd = new FormData();
        fd.append('file', file);
        const token = this.getToken();
        const res = await fetch(
            `${this.baseUrl}/api/grupos/${grupoId}/estudiantes/importar`,
            {
                method: 'POST',
                headers: { ...(token && { Authorization: `Bearer ${token}` }) },
                body: fd,
            }
        );
        if (!res.ok) {
            const txt = await res.text();
            throw new Error(txt || `Error ${res.status}`);
        }
        return res.json();
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

    // ==========================================
    // BOLETINES DOCX
    // ==========================================
    // Ambos endpoints devuelven un stream DOCX que descargamos directo.
    // Helper: encapsula fetch + Blob download y valida el Content-Type.

    async _descargarBlob(url, filenameFallback, method = 'GET') {
        const token = this.getToken();
        const res = await fetch(`${this.baseUrl}${url}`, {
            method,
            headers: { ...(token && { Authorization: `Bearer ${token}` }) },
        });
        if (!res.ok) {
            const txt = await res.text();
            throw new Error(txt || `Error ${res.status}`);
        }
        // Sacar nombre del Content-Disposition si viene
        let filename = filenameFallback;
        const cd = res.headers.get('content-disposition');
        if (cd) {
            const m = cd.match(/filename="?([^";]+)"?/i);
            if (m) filename = m[1];
        }
        const blob = await res.blob();
        const objUrl = URL.createObjectURL(blob);

        // iOS Safari no dispara la descarga con el truco de <a download> para
        // .docx (el click en un <a> invisible no hace nada, o abre una
        // pestaña con contenido binario ilegible). El endpoint requiere el
        // Bearer token, así que NO podemos abrir la URL de la API directo
        // con window.open — ya perdimos el header ahí. En cambio, abrimos el
        // blob que YA descargamos (con auth) en una pestaña nueva: Safari
        // muestra su visor nativo con el botón de compartir/guardar.
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        if (isIOS) {
            window.open(objUrl, '_blank');
            const mensaje = 'En iPhone, usa el botón compartir (□↑) para guardar el archivo.';
            if (typeof window.toast === 'function') {
                window.toast(mensaje, 'info');
            } else if (typeof window.mostrarAlerta === 'function') {
                window.mostrarAlerta(mensaje, 'info');
            } else {
                alert(mensaje);
            }
            // No revocar de inmediato — Safari todavía está cargando la
            // pestaña nueva. Se libera solo, un minuto después.
            setTimeout(() => URL.revokeObjectURL(objUrl), 60000);
        } else {
            const a = document.createElement('a');
            a.href = objUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(objUrl);
        }
        return { filename, size: blob.size };
    }

    async descargarBoletinEstudiante(grupoId, estudianteId, periodo) {
        return this._descargarBlob(
            `/api/grupos/${grupoId}/boletin/${estudianteId}?periodo=${periodo}`,
            `boletin_${estudianteId}_P${periodo}.docx`,
        );
    }

    async descargarBoletinGrupo(grupoId, periodo) {
        return this._descargarBlob(
            `/api/grupos/${grupoId}/boletin?periodo=${periodo}`,
            `boletin_grupo_${grupoId}_P${periodo}.docx`,
        );
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
