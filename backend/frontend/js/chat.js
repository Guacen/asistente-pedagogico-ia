// ============================================
// CHAT.JS - GESTIÓN DE CHAT CON IA
// ============================================

/**
 * Clase principal para manejar el chat con WebSocket
 */
class ChatManager {
    constructor(grupoId) {
        this.grupoId = grupoId;
        this.socket = null;
        this.mensajes = [];
        this.streamingMessage = '';
        this.isConnected = false;
        this.isIAGenerating = false;
        
        // Elementos del DOM
        this.containerMensajes = document.getElementById('mensajes-container');
        this.inputMensaje = document.getElementById('mensaje-input');
        this.formMensaje = document.getElementById('mensaje-form');
        this.btnEnviar = document.getElementById('send-btn');
        
        // Configuración
        this.autoScrollEnabled = true;
        this.maxReconnectAttempts = 5;
        this.reconnectAttempt = 0;
        this.reconnectDelay = 1000;
    }
    
    // ==========================================
    // INICIALIZACIÓN
    // ==========================================
    
    /**
     * Inicializa el chat: carga historial y conecta WebSocket
     */
    async init() {
        try {
            // Mostrar loading
            this.showLoading('Cargando historial...');
            
            // Cargar historial
            await this.cargarHistorial();
            
            // Conectar WebSocket
            await this.conectarWebSocket();
            
            // Inicializar event listeners
            this.initEventListeners();
            
            // Ocultar loading
            this.hideLoading();
            
            console.log('✅ Chat inicializado correctamente');
            
        } catch (error) {
            console.error('Error inicializando chat:', error);
            this.showError('Error al cargar el chat. Por favor recarga la página.');
        }
    }
    
    /**
     * Carga el historial de mensajes desde la API
     */
    async cargarHistorial() {
        try {
            this.mensajes = await api.getChatHistorial(this.grupoId, 50);
            this.renderMensajes();
            this.scrollToBottom(false);
        } catch (error) {
            console.error('Error cargando historial:', error);
            throw error;
        }
    }
    
    // ==========================================
    // WEBSOCKET
    // ==========================================
    
    /**
     * Conecta al servidor WebSocket
     */
    async conectarWebSocket() {
        return new Promise((resolve, reject) => {
            try {
                const token = Auth.getToken();
                
                if (!token) {
                    reject(new Error('No hay token de autenticación'));
                    return;
                }
                
                // Conectar con Socket.io
                this.socket = io(window.APP_CONFIG.WS_URL, {
                    auth: { token },
                    transports: ['websocket', 'polling'],
                    reconnection: true,
                    reconnectionAttempts: this.maxReconnectAttempts,
                    reconnectionDelay: this.reconnectDelay
                });
                
                // Evento: Conectado
                this.socket.on('connect', () => {
                    console.log('🟢 WebSocket conectado');
                    this.isConnected = true;
                    this.reconnectAttempt = 0;
                    
                    // Unirse a la sala del grupo
                    this.socket.emit('join_group', { grupo_id: this.grupoId });
                    
                    this.hideConnectionError();
                    resolve();
                });
                
                // Evento: Desconectado
                this.socket.on('disconnect', (reason) => {
                    console.log('🔴 WebSocket desconectado:', reason);
                    this.isConnected = false;
                    
                    if (reason === 'io server disconnect') {
                        this.socket.connect();
                    }
                    
                    this.showConnectionError('Conexión perdida. Reconectando...');
                });
                
                // Evento: Error de conexión
                this.socket.on('connect_error', (error) => {
                    console.error('❌ Error de conexión WebSocket:', error);
                    this.reconnectAttempt++;
                    
                    if (this.reconnectAttempt >= this.maxReconnectAttempts) {
                        this.showConnectionError('No se pudo conectar. Recarga la página.');
                        reject(error);
                    }
                });
                
                // Evento: Nuevo mensaje
                this.socket.on('new_message', (data) => {
                    this.onNuevoMensaje(data);
                });
                
                // Evento: IA generando
                this.socket.on('ia_generando', () => {
                    this.onIAGenerando();
                });
                
                // Evento: Chunk de streaming
                this.socket.on('ia_chunk', (chunk) => {
                    this.onIAChunk(chunk);
                });
                
                // Evento: IA completó
                this.socket.on('ia_complete', (mensaje) => {
                    this.onIAComplete(mensaje);
                });
                
                // Evento: Error IA
                this.socket.on('ia_error', (error) => {
                    this.onIAError(error);
                });
                
                // Timeout de conexión
                setTimeout(() => {
                    if (!this.isConnected) {
                        reject(new Error('Timeout de conexión WebSocket'));
                    }
                }, 10000);
                
            } catch (error) {
                console.error('Error en conectarWebSocket:', error);
                reject(error);
            }
        });
    }
    
    /**
     * Desconecta el WebSocket
     */
    desconectar() {
        if (this.socket) {
            this.socket.emit('leave_group', { grupo_id: this.grupoId });
            this.socket.disconnect();
            this.socket = null;
            this.isConnected = false;
        }
    }
    
    // ==========================================
    // EVENTOS DE WEBSOCKET
    // ==========================================
    
    onNuevoMensaje(data) {
        const existe = this.mensajes.find(m => m.id_mensaje === data.id_mensaje);
        
        if (!existe) {
            this.mensajes.push(data);
            this.agregarMensajeAlDOM(data);
            this.scrollToBottom();
        }
    }
    
    onIAGenerando() {
        console.log('🤖 IA generando...');
        this.isIAGenerating = true;
        this.streamingMessage = '';
        this.mostrarTypingIndicator();
        this.deshabilitarInput(true);
    }
    
    onIAChunk(chunk) {
        this.streamingMessage += chunk;
        this.actualizarMensajeStreaming(this.streamingMessage);
        this.scrollToBottom();
    }
    
    onIAComplete(mensajeCompleto) {
        console.log('✅ IA completó respuesta');
        this.isIAGenerating = false;
        this.streamingMessage = '';
        this.ocultarTypingIndicator();
        this.deshabilitarInput(false);
        
        // Remover mensaje streaming
        const streamingDiv = document.getElementById('streaming-message');
        if (streamingDiv) {
            streamingDiv.remove();
        }
    }
    
    onIAError(error) {
        console.error('❌ Error IA:', error);
        this.isIAGenerating = false;
        this.ocultarTypingIndicator();
        this.deshabilitarInput(false);
        
        const streamingDiv = document.getElementById('streaming-message');
        if (streamingDiv) {
            streamingDiv.remove();
        }
        
        this.showError(error.message || 'Error generando respuesta. Intenta nuevamente.');
    }
    
    // ==========================================
    // ENVIAR MENSAJES
    // ==========================================
    
    async enviarMensaje(mensaje, archivos = []) {
        if (!mensaje.trim() && archivos.length === 0) {
            return;
        }
        
        if (!this.isConnected) {
            this.showError('No hay conexión. Verifica tu internet.');
            return;
        }
        
        try {
            this.deshabilitarInput(true);
            
            this.socket.emit('send_message', {
                grupo_id: this.grupoId,
                mensaje: mensaje.trim(),
                archivos: archivos,
                id_docente: Auth.getUserId()
            });
            
            this.inputMensaje.value = '';
            this.ajustarAlturaTextarea();
            
        } catch (error) {
            console.error('Error enviando mensaje:', error);
            this.showError('Error enviando mensaje');
            this.deshabilitarInput(false);
        }
    }
    
    // ==========================================
    // RENDERIZADO
    // ==========================================
    
    renderMensajes() {
        this.containerMensajes.innerHTML = '';
        
        this.mensajes.forEach(mensaje => {
            this.agregarMensajeAlDOM(mensaje);
        });
    }
    
    agregarMensajeAlDOM(mensaje) {
        const isDocente = mensaje.remitente === 'docente';
        const div = document.createElement('div');
        div.className = `flex mb-4 ${isDocente ? 'justify-end' : 'justify-start'}`;
        
        const bubbleColor = isDocente ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-900';
        const timeColor = isDocente ? 'text-blue-100' : 'text-gray-500';
        
        const contenidoHTML = this.renderMarkdown(mensaje.contenido);
        const timestamp = this.formatearHora(mensaje.timestamp);
        
        div.innerHTML = `
            <div class="max-w-[70%] ${bubbleColor} rounded-lg px-4 py-3 shadow">
                <div class="mensaje-contenido prose prose-sm max-w-none ${isDocente ? 'prose-invert' : ''}">
                    ${contenidoHTML}
                </div>
                <div class="text-xs ${timeColor} mt-1">
                    ${timestamp}
                </div>
            </div>
        `;
        
        this.containerMensajes.appendChild(div);
    }
    
    mostrarTypingIndicator() {
        this.ocultarTypingIndicator();
        
        const div = document.createElement('div');
        div.id = 'typing-indicator';
        div.className = 'flex justify-start mb-4';
        
        div.innerHTML = `
            <div class="bg-gray-100 rounded-lg px-4 py-3">
                <div class="flex space-x-2">
                    <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                    <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.1s"></div>
                    <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
                </div>
            </div>
        `;
        
        this.containerMensajes.appendChild(div);
    }
    
    ocultarTypingIndicator() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) {
            indicator.remove();
        }
    }
    
    actualizarMensajeStreaming(contenido) {
        let streamingDiv = document.getElementById('streaming-message');
        
        if (!streamingDiv) {
            this.ocultarTypingIndicator();
            
            streamingDiv = document.createElement('div');
            streamingDiv.id = 'streaming-message';
            streamingDiv.className = 'flex justify-start mb-4';
            
            streamingDiv.innerHTML = `
                <div class="max-w-[70%] bg-gray-100 text-gray-900 rounded-lg px-4 py-3 shadow">
                    <div class="streaming-content prose prose-sm max-w-none"></div>
                </div>
            `;
            
            this.containerMensajes.appendChild(streamingDiv);
        }
        
        const contentDiv = streamingDiv.querySelector('.streaming-content');
        contentDiv.innerHTML = this.renderMarkdown(contenido);
    }
    
    renderMarkdown(texto) {
        if (typeof marked !== 'undefined') {
            return marked.parse(texto);
        } else {
            return texto
                .replace(/\n/g, '<br>')
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.*?)\*/g, '<em>$1</em>')
                .replace(/`(.*?)`/g, '<code>$1</code>');
        }
    }
    
    // ==========================================
    // UI HELPERS
    // ==========================================
    
    scrollToBottom(smooth = true) {
        if (!this.autoScrollEnabled) return;
        
        if (smooth) {
            this.containerMensajes.scrollTo({
                top: this.containerMensajes.scrollHeight,
                behavior: 'smooth'
            });
        } else {
            this.containerMensajes.scrollTop = this.containerMensajes.scrollHeight;
        }
    }
    
    deshabilitarInput(deshabilitar) {
        if (this.inputMensaje) {
            this.inputMensaje.disabled = deshabilitar;
        }
        
        if (this.btnEnviar) {
            this.btnEnviar.disabled = deshabilitar;
        }
    }
    
    ajustarAlturaTextarea() {
        if (!this.inputMensaje) return;
        
        this.inputMensaje.style.height = 'auto';
        this.inputMensaje.style.height = this.inputMensaje.scrollHeight + 'px';
    }
    
    showLoading(mensaje = 'Cargando...') {
        this.containerMensajes.innerHTML = `
            <div class="flex items-center justify-center h-full">
                <div class="text-center">
                    <i class="fas fa-spinner fa-spin text-4xl text-gray-400 mb-4"></i>
                    <p class="text-gray-600">${mensaje}</p>
                </div>
            </div>
        `;
    }
    
    hideLoading() {
        const loading = this.containerMensajes.querySelector('.fa-spinner');
        if (loading) {
            loading.closest('div').remove();
        }
    }
    
    showError(mensaje) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4';
        errorDiv.innerHTML = `
            <i class="fas fa-exclamation-circle mr-2"></i>
            ${mensaje}
        `;
        
        this.containerMensajes.insertBefore(errorDiv, this.containerMensajes.firstChild);
        
        setTimeout(() => errorDiv.remove(), 5000);
    }
    
    showConnectionError(mensaje) {
        let errorDiv = document.getElementById('connection-error');
        
        if (!errorDiv) {
            errorDiv = document.createElement('div');
            errorDiv.id = 'connection-error';
            errorDiv.className = 'fixed top-20 left-1/2 transform -translate-x-1/2 bg-yellow-100 border border-yellow-400 text-yellow-700 px-6 py-3 rounded-lg shadow-lg z-50';
            errorDiv.innerHTML = `
                <i class="fas fa-exclamation-triangle mr-2"></i>
                <span id="connection-error-text">${mensaje}</span>
            `;
            document.body.appendChild(errorDiv);
        } else {
            document.getElementById('connection-error-text').textContent = mensaje;
        }
    }
    
    hideConnectionError() {
        const errorDiv = document.getElementById('connection-error');
        if (errorDiv) {
            errorDiv.remove();
        }
    }
    
    // ==========================================
    // EVENT LISTENERS
    // ==========================================
    
    initEventListeners() {
        if (this.formMensaje) {
            this.formMensaje.addEventListener('submit', (e) => {
                e.preventDefault();
                
                const mensaje = this.inputMensaje.value.trim();
                if (mensaje) {
                    this.enviarMensaje(mensaje);
                }
            });
        }
        
        if (this.inputMensaje) {
            this.inputMensaje.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.formMensaje.dispatchEvent(new Event('submit'));
                }
            });
            
            this.inputMensaje.addEventListener('input', () => {
                this.ajustarAlturaTextarea();
            });
        }
        
        if (this.containerMensajes) {
            this.containerMensajes.addEventListener('scroll', () => {
                const isAtBottom = Math.abs(
                    this.containerMensajes.scrollHeight - 
                    this.containerMensajes.scrollTop - 
                    this.containerMensajes.clientHeight
                ) < 10;
                
                this.autoScrollEnabled = isAtBottom;
            });
        }
        
        window.addEventListener('beforeunload', () => {
            this.desconectar();
        });
    }
    
    // ==========================================
    // UTILIDADES
    // ==========================================
    
    formatearHora(timestamp) {
        const fecha = new Date(timestamp);
        const ahora = new Date();
        
        if (fecha.toDateString() === ahora.toDateString()) {
            return fecha.toLocaleTimeString('es-CO', {
                hour: '2-digit',
                minute: '2-digit'
            });
        }
        
        const ayer = new Date(ahora);
        ayer.setDate(ayer.getDate() - 1);
        if (fecha.toDateString() === ayer.toDateString()) {
            return 'Ayer ' + fecha.toLocaleTimeString('es-CO', {
                hour: '2-digit',
                minute: '2-digit'
            });
        }
        
        return fecha.toLocaleDateString('es-CO', {
            day: '2-digit',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
    
    limpiarChat() {
        this.mensajes = [];
        this.containerMensajes.innerHTML = '';
    }
}

// ==========================================
// FUNCIONES GLOBALES
// ==========================================

let chatManager = null;

async function initChat(grupoId) {
    if (!grupoId) {
        console.error('No se proporcionó grupoId');
        return;
    }
    
    try {
        chatManager = new ChatManager(grupoId);
        await chatManager.init();
        
        console.log('💬 Chat inicializado para grupo:', grupoId);
        
    } catch (error) {
        console.error('Error inicializando chat:', error);
        alert('Error al inicializar el chat. Por favor recarga la página.');
    }
}

function getChatManager() {
    return chatManager;
}

function closeChat() {
    if (chatManager) {
        chatManager.desconectar();
        chatManager = null;
    }
}

// ==========================================
// EXPORTAR GLOBALMENTE
// ==========================================

window.ChatManager = ChatManager;
window.initChat = initChat;
window.getChatManager = getChatManager;
window.closeChat = closeChat;

if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    console.log('💬 Chat.js cargado');
}