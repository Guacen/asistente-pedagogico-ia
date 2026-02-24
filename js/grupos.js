// ============================================
// GRUPOS.JS - GESTIÓN DE GRUPOS Y ESTUDIANTES
// ============================================

/**
 * Variables globales
 */
let grupos = [];
let grupoSeleccionado = null;
let estudiantes = [];
let modoEdicion = false;

// ==========================================
// INICIALIZACIÓN
// ==========================================

/**
 * Inicializa la página de grupos
 */
async function initGrupos() {
    try {
        // Proteger página
        Auth.requireAuth();
        
        // Cargar grupos
        await cargarGrupos();
        
        // Poblar select de grupos para estudiantes
        poblarSelectGrupos();
        
        // Inicializar event listeners
        initEventListeners();
        
        console.log('✅ Grupos.js inicializado');
        
    } catch (error) {
        console.error('Error inicializando grupos:', error);
        mostrarAlerta('Error al cargar la página', 'error');
    }
}

// ==========================================
// CARGAR DATOS
// ==========================================

/**
 * Carga todos los grupos del docente
 */
async function cargarGrupos() {
    try {
        mostrarLoadingGrupos();
        
        grupos = await api.getGrupos();
        
        if (grupos.length === 0) {
            mostrarMensajeVacio();
        } else {
            renderGrupos();
        }
        
    } catch (error) {
        console.error('Error cargando grupos:', error);
        mostrarAlerta('Error al cargar grupos', 'error');
    }
}

/**
 * Carga estudiantes de un grupo específico
 */
async function cargarEstudiantesGrupo(grupoId) {
    if (!grupoId) {
        document.getElementById('estudiantes-container').classList.add('hidden');
        document.getElementById('empty-estudiantes').classList.remove('hidden');
        return;
    }
    
    grupoSeleccionado = grupoId;
    
    try {
        mostrarLoadingEstudiantes();
        
        estudiantes = await api.getEstudiantes(grupoId);
        
        document.getElementById('estudiantes-container').classList.remove('hidden');
        document.getElementById('empty-estudiantes').classList.add('hidden');
        
        renderEstudiantes();
        
    } catch (error) {
        console.error('Error cargando estudiantes:', error);
        mostrarAlerta('Error al cargar estudiantes', 'error');
    }
}

// ==========================================
// RENDERIZADO DE GRUPOS
// ==========================================

/**
 * Renderiza la lista de grupos en el grid
 */
function renderGrupos() {
    const grid = document.getElementById('grupos-grid');
    const empty = document.getElementById('empty-grupos');
    
    if (grupos.length === 0) {
        grid.classList.add('hidden');
        empty.classList.remove('hidden');
        return;
    }
    
    grid.classList.remove('hidden');
    empty.classList.add('hidden');
    
    grid.innerHTML = grupos.map(grupo => crearCardGrupo(grupo)).join('');
}

/**
 * Crea el HTML de una card de grupo
 */
function crearCardGrupo(grupo) {
    const colorAsignatura = grupo.asignatura === 'álgebra' ? 'blue' : 'green';
    const iconoAsignatura = grupo.asignatura === 'álgebra' ? 'square-root-alt' : 'flask';
    
    return `
        <div class="bg-white rounded-lg shadow-md hover:shadow-xl transition-shadow overflow-hidden">
            <div class="p-6">
                <div class="flex items-center justify-between mb-4">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-${colorAsignatura}-100 rounded-lg flex items-center justify-center mr-3">
                            <i class="fas fa-${iconoAsignatura} text-2xl text-${colorAsignatura}-600"></i>
                        </div>
                        <div>
                            <h3 class="font-bold text-lg">${grupo.nombre_grupo}</h3>
                            <p class="text-sm text-gray-600">${grupo.grado} • ${grupo.asignatura}</p>
                        </div>
                    </div>
                </div>
                
                <div class="space-y-2 mb-4">
                    <div class="flex items-center text-sm text-gray-600">
                        <i class="fas fa-users w-5"></i>
                        <span>${grupo.cantidad_estudiantes} estudiantes</span>
                    </div>
                    <div class="flex items-center text-sm text-gray-600">
                        <i class="fas fa-calendar w-5"></i>
                        <span>${grupo.año_lectivo || '2026'} • Período ${grupo.periodo_actual || '1'}</span>
                    </div>
                </div>
                
                <div class="flex space-x-2">
                    <a 
                        href="chat.html?id=${grupo.id_grupo}" 
                        class="flex-1 bg-blue-600 text-white py-2 rounded-lg text-center hover:bg-blue-700 transition-colors"
                    >
                        <i class="fas fa-comments mr-1"></i>
                        Chat
                    </a>
                    <button 
                        onclick="editarGrupo('${grupo.id_grupo}')" 
                        class="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                        title="Editar"
                    >
                        <i class="fas fa-edit"></i>
                    </button>
                    <button 
                        onclick="confirmarEliminarGrupo('${grupo.id_grupo}', '${grupo.nombre_grupo}')" 
                        class="px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
                        title="Eliminar"
                    >
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `;
}

/**
 * Muestra mensaje cuando no hay grupos
 */
function mostrarMensajeVacio() {
    const grid = document.getElementById('grupos-grid');
    const empty = document.getElementById('empty-grupos');
    
    grid.classList.add('hidden');
    empty.classList.remove('hidden');
}

/**
 * Muestra loading en grid de grupos
 */
function mostrarLoadingGrupos() {
    const grid = document.getElementById('grupos-grid');
    grid.innerHTML = `
        <div class="col-span-full text-center py-12">
            <i class="fas fa-spinner fa-spin text-4xl text-gray-400 mb-4"></i>
            <p class="text-gray-600">Cargando grupos...</p>
        </div>
    `;
}

// ==========================================
// FILTRADO DE GRUPOS
// ==========================================

/**
 * Filtra grupos según criterios de búsqueda
 */
function filtrarGrupos() {
    const search = document.getElementById('search-grupos').value.toLowerCase();
    const grado = document.getElementById('filter-grado').value;
    const asignatura = document.getElementById('filter-asignatura').value;
    const año = document.getElementById('filter-año').value;
    
    const gruposFiltrados = grupos.filter(grupo => {
        const matchSearch = grupo.nombre_grupo.toLowerCase().includes(search);
        const matchGrado = !grado || grupo.grado === grado;
        const matchAsignatura = !asignatura || grupo.asignatura === asignatura;
        const matchAño = !año || (grupo.año_lectivo && grupo.año_lectivo.toString() === año);
        
        return matchSearch && matchGrado && matchAsignatura && matchAño;
    });
    
    renderGruposFiltrados(gruposFiltrados);
}

/**
 * Renderiza grupos filtrados
 */
function renderGruposFiltrados(gruposFiltrados) {
    const grid = document.getElementById('grupos-grid');
    
    if (gruposFiltrados.length === 0) {
        grid.innerHTML = `
            <div class="col-span-full text-center py-12">
                <i class="fas fa-search text-6xl text-gray-300 mb-4"></i>
                <p class="text-gray-600">No se encontraron grupos con esos filtros</p>
            </div>
        `;
    } else {
        grid.innerHTML = gruposFiltrados.map(grupo => crearCardGrupo(grupo)).join('');
    }
}

// ==========================================
// CRUD GRUPOS
// ==========================================

/**
 * Abre modal para crear nuevo grupo
 */
function abrirModalNuevoGrupo() {
    modoEdicion = false;
    
    document.getElementById('modal-grupo-title').textContent = 'Nuevo Grupo';
    document.getElementById('form-grupo').reset();
    document.getElementById('grupo-id').value = '';
    document.getElementById('btn-guardar-text').textContent = 'Crear Grupo';
    
    // Valores por defecto
    document.getElementById('grupo-año').value = new Date().getFullYear();
    document.getElementById('grupo-periodo').value = '1';
    
    document.getElementById('modal-grupo').classList.remove('hidden');
}

/**
 * Abre modal para editar grupo existente
 */
async function editarGrupo(grupoId) {
    modoEdicion = true;
    
    try {
        const grupo = await api.getGrupo(grupoId);
        
        document.getElementById('modal-grupo-title').textContent = 'Editar Grupo';
        document.getElementById('grupo-id').value = grupo.id_grupo;
        document.getElementById('grupo-nombre').value = grupo.nombre_grupo;
        document.getElementById('grupo-grado').value = grupo.grado;
        document.getElementById('grupo-asignatura').value = grupo.asignatura;
        document.getElementById('grupo-año').value = grupo.año_lectivo || new Date().getFullYear();
        document.getElementById('grupo-periodo').value = grupo.periodo_actual || '1';
        document.getElementById('grupo-cantidad').value = grupo.cantidad_estudiantes;
        
        // Recursos
        if (grupo.recursos_disponibles) {
            document.getElementById('recurso-laboratorio').checked = grupo.recursos_disponibles.laboratorio_fisica || false;
            document.getElementById('recurso-informatica').checked = grupo.recursos_disponibles.sala_informatica || false;
            document.getElementById('recurso-internet').checked = grupo.recursos_disponibles.internet_estable || false;
            document.getElementById('recurso-proyector').checked = grupo.recursos_disponibles.proyector || false;
        }
        
        document.getElementById('btn-guardar-text').textContent = 'Guardar Cambios';
        document.getElementById('modal-grupo').classList.remove('hidden');
        
    } catch (error) {
        console.error('Error cargando grupo:', error);
        mostrarAlerta('Error al cargar datos del grupo', 'error');
    }
}

/**
 * Cierra modal de grupo
 */
function cerrarModalGrupo() {
    document.getElementById('modal-grupo').classList.add('hidden');
    document.getElementById('form-grupo').reset();
}

/**
 * Guarda grupo (crear o actualizar)
 */
async function guardarGrupo(event) {
    event.preventDefault();
    
    const grupoId = document.getElementById('grupo-id').value;
    
    const data = {
        nombre_grupo: document.getElementById('grupo-nombre').value.trim(),
        grado: document.getElementById('grupo-grado').value,
        asignatura: document.getElementById('grupo-asignatura').value,
        año_lectivo: parseInt(document.getElementById('grupo-año').value),
        periodo_actual: parseInt(document.getElementById('grupo-periodo').value),
        cantidad_estudiantes: parseInt(document.getElementById('grupo-cantidad').value),
        recursos_disponibles: {
            laboratorio_fisica: document.getElementById('recurso-laboratorio').checked,
            sala_informatica: document.getElementById('recurso-informatica').checked,
            internet_estable: document.getElementById('recurso-internet').checked,
            proyector: document.getElementById('recurso-proyector').checked
        }
    };
    
    // Validaciones
    if (!data.nombre_grupo) {
        mostrarAlerta('El nombre del grupo es requerido', 'error');
        return;
    }
    
    if (!data.grado || !data.asignatura) {
        mostrarAlerta('Debes seleccionar grado y asignatura', 'error');
        return;
    }
    
    if (data.cantidad_estudiantes < 1 || data.cantidad_estudiantes > 50) {
        mostrarAlerta('La cantidad de estudiantes debe estar entre 1 y 50', 'error');
        return;
    }
    
    const btn = document.getElementById('btn-guardar-grupo');
    const btnText = document.getElementById('btn-guardar-text');
    const spinner = document.getElementById('btn-guardar-spinner');
    
    btn.disabled = true;
    btnText.textContent = modoEdicion ? 'Guardando...' : 'Creando...';
    spinner.classList.remove('hidden');
    
    try {
        if (modoEdicion && grupoId) {
            await api.updateGrupo(grupoId, data);
            mostrarAlerta('Grupo actualizado correctamente', 'success');
        } else {
            await api.createGrupo(data);
            mostrarAlerta('Grupo creado correctamente', 'success');
        }
        
        cerrarModalGrupo();
        await cargarGrupos();
        poblarSelectGrupos();
        
    } catch (error) {
        console.error('Error guardando grupo:', error);
        mostrarAlerta(error.message || 'Error al guardar el grupo', 'error');
    } finally {
        btn.disabled = false;
        btnText.textContent = modoEdicion ? 'Guardar Cambios' : 'Crear Grupo';
        spinner.classList.add('hidden');
    }
}

/**
 * Confirma eliminación de grupo
 */
function confirmarEliminarGrupo(grupoId, nombreGrupo) {
    const confirmacion = confirm(
        `¿Estás seguro de eliminar el grupo "${nombreGrupo}"?\n\n` +
        `Esta acción no se puede deshacer y eliminará:\n` +
        `• Todos los estudiantes del grupo\n` +
        `• Todo el historial de chat\n` +
        `• Todas las notas y archivos\n\n` +
        `Escribe "ELIMINAR" para confirmar.`
    );
    
    if (confirmacion) {
        const texto = prompt('Escribe "ELIMINAR" para confirmar:');
        
        if (texto === 'ELIMINAR') {
            eliminarGrupo(grupoId);
        }
    }
}

/**
 * Elimina un grupo
 */
async function eliminarGrupo(grupoId) {
    try {
        await api.deleteGrupo(grupoId);
        mostrarAlerta('Grupo eliminado correctamente', 'success');
        
        await cargarGrupos();
        poblarSelectGrupos();
        
        // Si el grupo eliminado era el seleccionado, limpiar estudiantes
        if (grupoSeleccionado === grupoId) {
            grupoSeleccionado = null;
            estudiantes = [];
            document.getElementById('select-grupo-estudiantes').value = '';
            document.getElementById('estudiantes-container').classList.add('hidden');
            document.getElementById('empty-estudiantes').classList.remove('hidden');
        }
        
    } catch (error) {
        console.error('Error eliminando grupo:', error);
        mostrarAlerta(error.message || 'Error al eliminar el grupo', 'error');
    }
}

// ==========================================
// RENDERIZADO DE ESTUDIANTES
// ==========================================

/**
 * Renderiza la tabla de estudiantes
 */
function renderEstudiantes() {
    const tbody = document.getElementById('estudiantes-table-body');
    
    if (estudiantes.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" class="px-6 py-12 text-center text-gray-500">
                    No hay estudiantes agregados aún
                    <br>
                    <button 
                        onclick="abrirModalNuevoEstudiante()" 
                        class="mt-4 text-blue-600 hover:underline"
                    >
                        <i class="fas fa-plus mr-1"></i>
                        Agregar primer estudiante
                    </button>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = estudiantes.map(est => crearFilaEstudiante(est)).join('');
}

/**
 * Crea el HTML de una fila de estudiante
 */
function crearFilaEstudiante(estudiante) {
    const generoIcon = estudiante.genero === 'masculino' ? 'mars' : 
                       estudiante.genero === 'femenino' ? 'venus' : 'genderless';
    
    return `
        <tr class="hover:bg-gray-50">
            <td class="px-6 py-4">
                <div class="flex items-center">
                    <div class="w-10 h-10 bg-gray-200 rounded-full flex items-center justify-center mr-3">
                        <i class="fas fa-user text-gray-600"></i>
                    </div>
                    <span class="font-medium">${estudiante.codigo_estudiante}</span>
                </div>
            </td>
            <td class="px-6 py-4">
                ${estudiante.genero ? `<i class="fas fa-${generoIcon} mr-1"></i> ${estudiante.genero}` : '<span class="text-gray-400">No especifica</span>'}
            </td>
            <td class="px-6 py-4">
                ${estudiante.tiene_piar ? 
                    '<span class="bg-yellow-100 text-yellow-800 px-2 py-1 rounded text-xs font-semibold">Sí</span>' : 
                    '<span class="text-gray-400">No</span>'
                }
            </td>
            <td class="px-6 py-4">
                <button 
                    onclick="editarEstudiante('${estudiante.id_estudiante}')" 
                    class="text-blue-600 hover:text-blue-800 mr-3"
                    title="Editar"
                >
                    <i class="fas fa-edit"></i>
                </button>
                <button 
                    onclick="confirmarEliminarEstudiante('${estudiante.id_estudiante}', '${estudiante.codigo_estudiante}')" 
                    class="text-red-600 hover:text-red-800"
                    title="Eliminar"
                >
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `;
}

/**
 * Muestra loading en tabla de estudiantes
 */
function mostrarLoadingEstudiantes() {
    const tbody = document.getElementById('estudiantes-table-body');
    tbody.innerHTML = `
        <tr>
            <td colspan="4" class="px-6 py-12 text-center">
                <i class="fas fa-spinner fa-spin text-4xl text-gray-400 mb-4"></i>
                <p class="text-gray-600">Cargando estudiantes...</p>
            </td>
        </tr>
    `;
}

// ==========================================
// CRUD ESTUDIANTES
// ==========================================

/**
 * Abre modal para crear nuevo estudiante
 */
function abrirModalNuevoEstudiante() {
    if (!grupoSeleccionado) {
        mostrarAlerta('Primero selecciona un grupo', 'error');
        return;
    }
    
    document.getElementById('modal-estudiante-title').textContent = 'Nuevo Estudiante';
    document.getElementById('form-estudiante').reset();
    document.getElementById('estudiante-id').value = '';
    document.getElementById('estudiante-grupo-id').value = grupoSeleccionado;
    document.getElementById('piar-fields').classList.add('hidden');
    document.getElementById('btn-guardar-est-text').textContent = 'Agregar Estudiante';
    
    document.getElementById('modal-estudiante').classList.remove('hidden');
}

/**
 * Abre modal para editar estudiante
 */
async function editarEstudiante(estudianteId) {
    try {
        const estudiante = await api.getEstudiante(grupoSeleccionado, estudianteId);
        
        document.getElementById('modal-estudiante-title').textContent = 'Editar Estudiante';
        document.getElementById('estudiante-id').value = estudiante.id_estudiante;
        document.getElementById('estudiante-grupo-id').value = grupoSeleccionado;
        document.getElementById('estudiante-codigo').value = estudiante.codigo_estudiante;
        document.getElementById('estudiante-genero').value = estudiante.genero || '';
        document.getElementById('estudiante-piar').checked = estudiante.tiene_piar || false;
        
        if (estudiante.tiene_piar) {
            document.getElementById('piar-fields').classList.remove('hidden');
            document.getElementById('estudiante-diagnostico').value = estudiante.diagnostico || '';
            document.getElementById('estudiante-ajustes').value = estudiante.ajustes || '';
        }
        
        document.getElementById('btn-guardar-est-text').textContent = 'Guardar Cambios';
        document.getElementById('modal-estudiante').classList.remove('hidden');
        
    } catch (error) {
        console.error('Error cargando estudiante:', error);
        mostrarAlerta('Error al cargar datos del estudiante', 'error');
    }
}

/**
 * Cierra modal de estudiante
 */
function cerrarModalEstudiante() {
    document.getElementById('modal-estudiante').classList.add('hidden');
    document.getElementById('form-estudiante').reset();
}

/**
 * Toggle campos PIAR
 */
function togglePiarFields() {
    const checked = document.getElementById('estudiante-piar').checked;
    const fields = document.getElementById('piar-fields');
    
    if (checked) {
        fields.classList.remove('hidden');
    } else {
        fields.classList.add('hidden');
    }
}

/**
 * Guarda estudiante (crear o actualizar)
 */
async function guardarEstudiante(event) {
    event.preventDefault();
    
    const estudianteId = document.getElementById('estudiante-id').value;
    const grupoId = document.getElementById('estudiante-grupo-id').value || grupoSeleccionado;
    
    const data = {
        codigo_estudiante: document.getElementById('estudiante-codigo').value.trim(),
        genero: document.getElementById('estudiante-genero').value || null,
        tiene_piar: document.getElementById('estudiante-piar').checked
    };
    
    if (data.tiene_piar) {
        data.diagnostico = document.getElementById('estudiante-diagnostico').value.trim();
        data.ajustes = document.getElementById('estudiante-ajustes').value.trim();
    }
    
    // Validación
    if (!data.codigo_estudiante) {
        mostrarAlerta('El código/nombre del estudiante es requerido', 'error');
        return;
    }
    
    const btn = document.getElementById('btn-guardar-estudiante');
    const btnText = document.getElementById('btn-guardar-est-text');
    const spinner = document.getElementById('btn-guardar-est-spinner');
    
    btn.disabled = true;
    btnText.textContent = estudianteId ? 'Guardando...' : 'Agregando...';
    spinner.classList.remove('hidden');
    
    try {
        if (estudianteId) {
            await api.updateEstudiante(grupoId, estudianteId, data);
            mostrarAlerta('Estudiante actualizado correctamente', 'success');
        } else {
            await api.createEstudiante(grupoId, data);
            mostrarAlerta('Estudiante agregado correctamente', 'success');
        }
        
        cerrarModalEstudiante();
        await cargarEstudiantesGrupo(grupoId);
        
    } catch (error) {
        console.error('Error guardando estudiante:', error);
        mostrarAlerta(error.message || 'Error al guardar el estudiante', 'error');
    } finally {
        btn.disabled = false;
        btnText.textContent = estudianteId ? 'Guardar Cambios' : 'Agregar Estudiante';
        spinner.classList.add('hidden');
    }
}

/**
 * Confirma eliminación de estudiante
 */
function confirmarEliminarEstudiante(estudianteId, codigo) {
    if (confirm(`¿Eliminar estudiante "${codigo}"?`)) {
        eliminarEstudiante(estudianteId);
    }
}

/**
 * Elimina un estudiante
 */
async function eliminarEstudiante(estudianteId) {
    try {
        await api.deleteEstudiante(grupoSeleccionado, estudianteId);
        mostrarAlerta('Estudiante eliminado correctamente', 'success');
        
        await cargarEstudiantesGrupo(grupoSeleccionado);
        
    } catch (error) {
        console.error('Error eliminando estudiante:', error);
        mostrarAlerta(error.message || 'Error al eliminar el estudiante', 'error');
    }
}

// ==========================================
// TABS
// ==========================================

/**
 * Cambia entre pestañas (Grupos / Estudiantes)
 */
function cambiarTab(tab) {
    // Actualizar botones
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('border-blue-600', 'text-blue-600');
        btn.classList.add('border-transparent', 'text-gray-500');
    });
    
    document.getElementById(`tab-${tab}`).classList.add('border-blue-600', 'text-blue-600');
    document.getElementById(`tab-${tab}`).classList.remove('border-transparent', 'text-gray-500');
    
    // Mostrar contenido
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.add('hidden');
    });
    
    document.getElementById(`content-${tab}`).classList.remove('hidden');
}

// ==========================================
// SELECT DE GRUPOS
// ==========================================

/**
 * Pobla el select de grupos para la pestaña de estudiantes
 */
function poblarSelectGrupos() {
    const select = document.getElementById('select-grupo-estudiantes');
    select.innerHTML = '<option value="">-- Selecciona un grupo --</option>' + 
        grupos.map(g => `<option value="${g.id_grupo}">${g.nombre_grupo} (${g.grado} ${g.asignatura})</option>`).join('');
}

// ==========================================
// EVENT LISTENERS
// ==========================================

/**
 * Inicializa todos los event listeners
 */
function initEventListeners() {
    // Formulario de grupo
    const formGrupo = document.getElementById('form-grupo');
    if (formGrupo) {
        formGrupo.addEventListener('submit', guardarGrupo);
    }
    
    // Formulario de estudiante
    const formEstudiante = document.getElementById('form-estudiante');
    if (formEstudiante) {
        formEstudiante.addEventListener('submit', guardarEstudiante);
    }
    
    // Filtros de grupos
    const searchGrupos = document.getElementById('search-grupos');
    if (searchGrupos) {
        searchGrupos.addEventListener('input', filtrarGrupos);
    }
    
    const filterGrado = document.getElementById('filter-grado');
    if (filterGrado) {
        filterGrado.addEventListener('change', filtrarGrupos);
    }
    
    const filterAsignatura = document.getElementById('filter-asignatura');
    if (filterAsignatura) {
        filterAsignatura.addEventListener('change', filtrarGrupos);
    }
    
    const filterAño = document.getElementById('filter-año');
    if (filterAño) {
        filterAño.addEventListener('change', filtrarGrupos);
    }
    
    // Select de grupo para estudiantes
    const selectGrupo = document.getElementById('select-grupo-estudiantes');
    if (selectGrupo) {
        selectGrupo.addEventListener('change', (e) => {
            cargarEstudiantesGrupo(e.target.value);
        });
    }
    
    // Checkbox PIAR
    const piarCheckbox = document.getElementById('estudiante-piar');
    if (piarCheckbox) {
        piarCheckbox.addEventListener('change', togglePiarFields);
    }
}

// ==========================================
// UTILIDADES
// ==========================================

/**
 * Muestra alerta temporal
 */
function mostrarAlerta(mensaje, tipo = 'info') {
    const colores = {
        success: 'bg-green-100 border-green-400 text-green-700',
        error: 'bg-red-100 border-red-400 text-red-700',
        info: 'bg-blue-100 border-blue-400 text-blue-700',
        warning: 'bg-yellow-100 border-yellow-400 text-yellow-700'
    };
    
    const iconos = {
        success: 'check-circle',
        error: 'exclamation-circle',
        info: 'info-circle',
        warning: 'exclamation-triangle'
    };
    
    const alerta = document.createElement('div');
    alerta.className = `fixed top-20 right-4 ${colores[tipo]} border px-6 py-4 rounded-lg shadow-lg z-50 max-w-md`;
    alerta.innerHTML = `
        <div class="flex items-center">
            <i class="fas fa-${iconos[tipo]} mr-3 text-xl"></i>
            <span>${mensaje}</span>
        </div>
    `;
    
    document.body.appendChild(alerta);
    
    // Auto-remover después de 4 segundos
    setTimeout(() => {
        alerta.remove();
    }, 4000);
}

// ==========================================
// EXPORTAR GLOBALMENTE
// ==========================================

window.initGrupos = initGrupos;
window.cambiarTab = cambiarTab;
window.abrirModalNuevoGrupo = abrirModalNuevoGrupo;
window.editarGrupo = editarGrupo;
window.cerrarModalGrupo = cerrarModalGrupo;
window.confirmarEliminarGrupo = confirmarEliminarGrupo;
window.eliminarGrupo = eliminarGrupo;
window.abrirModalNuevoEstudiante = abrirModalNuevoEstudiante;
window.editarEstudiante = editarEstudiante;
window.cerrarModalEstudiante = cerrarModalEstudiante;
window.togglePiarFields = togglePiarFields;
window.confirmarEliminarEstudiante = confirmarEliminarEstudiante;
window.cargarEstudiantesGrupo = cargarEstudiantesGrupo;
window.filtrarGrupos = filtrarGrupos;

// ==========================================
// LOG DE DESARROLLO
// ==========================================

if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    console.log('📚 Grupos.js cargado');
}