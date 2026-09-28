// ============================================
// REPORTAR UN PROBLEMA (sprint primer-uso, Parte D)
// ============================================
// Botón discreto + modal, inyectados por JS — una sola línea
// (<script src="js/reportar-problema.js">) agrega la función completa a
// cualquier página autenticada, sin duplicar HTML en cada una.
//
// El docente SOLO escribe la descripción. Todo lo demás se captura
// solo: docente (Auth.getUser()), pantalla actual, fecha/hora,
// correlation_id del último error visto en esta sesión (api.js y el
// handler de ia_error de chat.html lo guardan en localStorage bajo
// 'ultimo_correlation_id' — es el mismo ID que generó errores.py del
// lado del servidor), navegador y si es móvil o escritorio (derivados
// de navigator.userAgent, nunca se manda el user-agent crudo).
//
// Minimización de datos a propósito: nada de capturas de pantalla,
// contenido de otros campos que el docente estuviera llenando, ni
// datos de estudiantes.

(function () {
    function _detectarNavegador(ua) {
        if (/Edg\//.test(ua)) return 'Edge';
        if (/OPR\//.test(ua)) return 'Opera';
        if (/Chrome\//.test(ua) && !/Chromium/.test(ua)) return 'Chrome';
        if (/Firefox\//.test(ua)) return 'Firefox';
        if (/Safari\//.test(ua) && !/Chrome/.test(ua)) return 'Safari';
        return 'Otro';
    }

    function _esMovil(ua) {
        return /Android|iPhone|iPad|iPod|Mobile/i.test(ua);
    }

    function _crearWidget() {
        const boton = document.createElement('button');
        boton.id = 'btn-reportar-problema';
        boton.type = 'button';
        boton.title = 'Reportar un problema';
        boton.setAttribute('aria-label', 'Reportar un problema');
        boton.className = 'fixed bottom-4 right-4 z-40 w-11 h-11 rounded-full bg-white border border-gray-300 text-gray-500 shadow-md flex items-center justify-center hover:bg-gray-50 hover:text-gray-700 transition-colors';
        boton.innerHTML = '<i class="fas fa-circle-exclamation text-lg"></i>';

        const modal = document.createElement('div');
        modal.id = 'modal-reportar-problema';
        modal.className = 'hidden fixed inset-0 z-50 flex items-center justify-center p-4';
        modal.innerHTML = `
            <div class="absolute inset-0 bg-black/40" data-cerrar-reporte></div>
            <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
                <div class="flex items-start justify-between mb-3">
                    <h2 class="text-lg font-bold text-gray-900">Reportar un problema</h2>
                    <button type="button" data-cerrar-reporte class="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
                </div>
                <p class="text-sm text-gray-500 mb-4">Contanos qué pasó — el resto lo completamos nosotros.</p>
                <textarea id="reporte-descripcion" rows="4" maxlength="2000"
                    class="w-full border border-gray-300 rounded-lg p-3 text-sm focus:outline-none focus:ring-2"
                    style="--tw-ring-color: var(--brand-primary, #1D9E75);"
                    placeholder="Ej: intenté generar una planeación y se quedó cargando sin terminar nunca."></textarea>
                <p id="reporte-error" class="hidden text-xs text-red-600 mt-2"></p>
                <div class="flex justify-end gap-2 mt-4">
                    <button type="button" data-cerrar-reporte class="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100">Cancelar</button>
                    <button type="button" id="btn-enviar-reporte" class="px-4 py-2 rounded-lg text-sm font-semibold text-white"
                        style="background: var(--brand-primary, #1D9E75);">Enviar reporte</button>
                </div>
            </div>`;

        document.body.appendChild(boton);
        document.body.appendChild(modal);

        function abrir() {
            document.getElementById('reporte-error').classList.add('hidden');
            document.getElementById('reporte-descripcion').value = '';
            modal.classList.remove('hidden');
            document.getElementById('reporte-descripcion').focus();
        }
        function cerrar() {
            modal.classList.add('hidden');
        }

        boton.addEventListener('click', abrir);
        modal.querySelectorAll('[data-cerrar-reporte]').forEach((el) => {
            el.addEventListener('click', cerrar);
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !modal.classList.contains('hidden')) cerrar();
        });

        document.getElementById('btn-enviar-reporte').addEventListener('click', async () => {
            const descripcion = document.getElementById('reporte-descripcion').value.trim();
            const errorEl = document.getElementById('reporte-error');
            if (!descripcion) {
                errorEl.textContent = 'Escribe qué pasó antes de enviar.';
                errorEl.classList.remove('hidden');
                return;
            }
            const btn = document.getElementById('btn-enviar-reporte');
            btn.disabled = true;
            const textoOriginal = btn.textContent;
            btn.textContent = 'Enviando...';
            try {
                const ua = navigator.userAgent || '';
                await window.api.crearReporteProblema({
                    descripcion,
                    pantalla: window.location.pathname + window.location.search,
                    correlation_id: localStorage.getItem('ultimo_correlation_id') || null,
                    navegador: _detectarNavegador(ua),
                    es_movil: _esMovil(ua),
                });
                cerrar();
                if (typeof window.toast === 'function') {
                    window.toast('Gracias, recibimos tu reporte.', 'success');
                } else {
                    alert('Gracias, recibimos tu reporte.');
                }
            } catch (err) {
                errorEl.textContent = 'No pudimos enviar el reporte. Intenta de nuevo en un momento.';
                errorEl.classList.remove('hidden');
            } finally {
                btn.disabled = false;
                btn.textContent = textoOriginal;
            }
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        // Sólo para docentes con sesión — si no hay Auth o no está
        // autenticado, no tiene sentido ofrecer el botón (páginas de
        // login/registro no cargan este script de todos modos).
        if (window.Auth && typeof Auth.isAuthenticated === 'function' && !Auth.isAuthenticated()) {
            return;
        }
        _crearWidget();
    });
})();
