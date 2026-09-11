// SPRINT 8, Parte B — VERIFICACIÓN OBLIGATORIA #3: el botón
// btn-iniciar-pregunta se revela cuando la diapositiva activa tiene
// pregunta (tipo "multiple" o "verdadero_falso") y sigue oculto para
// "contenido"/"separador".
//
// A diferencia de test_render_contenido_diapositiva.mjs (que extrae un
// snippet acotado), acá se corre el SCRIPT PRINCIPAL completo del
// archivo real dentro de un DOM mínimo simulado — renderSlideActual()
// depende de demasiadas funciones/objetos dispersos (PD, los 6
// renderers de diagramas, etc.) para recortar un fragmento angosto sin
// arriesgarse a probar una copia que diverge del comportamiento real.
//
// No hay runner JS (jest/vitest) en este repo — se ejecuta directo con
// Node y no está enganchado al pipeline de CI (que sólo corre pytest).
// Correr manualmente: node backend/tests/frontend/test_boton_iniciar_pregunta.mjs

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const htmlPath = path.join(__dirname, '..', '..', 'frontend', 'presentacion-docente.html');
const html = readFileSync(htmlPath, 'utf8');

// ── DOM mínimo suficiente para renderSlideActual/actualizarControles ──
// getElementById/classList/innerHTML (con "parseo" superficial: un
// id="..." mencionado en un innerHTML asignado queda disponible para
// un getElementById posterior, que es exactamente el patrón que usa
// este archivo: pinta el HTML del slide y después busca sus hijos).
class ClassList {
    constructor() { this.set = new Set(); }
    add(...c) { c.forEach((x) => this.set.add(x)); }
    remove(...c) { c.forEach((x) => this.set.delete(x)); }
    toggle(c, force) {
        if (force === undefined) {
            if (this.set.has(c)) { this.set.delete(c); return false; }
            this.set.add(c); return true;
        }
        if (force) { this.set.add(c); return true; }
        this.set.delete(c); return false;
    }
    contains(c) { return this.set.has(c); }
}

class Elemento {
    constructor(id) {
        this.id = id;
        this.classList = new ClassList();
        this._innerHTML = '';
        this.textContent = '';
        this.style = {};
        this.value = '';
        this.disabled = false;
    }
    set innerHTML(valor) {
        this._innerHTML = valor;
        const re = /id="([\w-]+)"/g;
        let m;
        while ((m = re.exec(valor))) {
            if (!registro[m[1]]) registro[m[1]] = new Elemento(m[1]);
        }
    }
    get innerHTML() { return this._innerHTML; }
    appendChild() {}
    closest() { return null; }
    querySelector() { return null; }
}

let registro = {};
function crearDocumentoFalso() {
    registro = {};
    return {
        getElementById(id) {
            if (!registro[id]) registro[id] = new Elemento(id);
            return registro[id];
        },
        querySelectorAll() { return []; },
        addEventListener() {},
        createElement() { return new Elemento(null); },
        activeElement: null,
    };
}

function prepararElementosEstaticos(document) {
    // Estado inicial real de estos elementos tal como está en el HTML
    // (btn-iniciar-pregunta/btn-revelar/control-contador nacen con
    // class="hidden" — ver PARTE B del sprint, "nace con class=hidden
    // y nunca se revela").
    const conHidden = ['btn-iniciar-pregunta', 'btn-revelar', 'control-contador', 'control-notas'];
    conHidden.forEach((id) => document.getElementById(id).classList.add('hidden'));
    document.getElementById('pantalla-vivo'); // registrado, sin clase 'activa'
}

function cargarScriptPresentacionDocente(contexto) {
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
    const principal = scripts.reduce((a, b) => (a.length > b.length ? a : b));
    assert.ok(principal.includes('function renderSlideActual'), 'No se encontró renderSlideActual en el script principal');
    vm.createContext(contexto);
    vm.runInContext(`${principal}
        globalThis.__exp = { renderSlideActual: typeof renderSlideActual !== 'undefined' ? renderSlideActual : undefined };
    `, contexto);
    return contexto;
}

function nuevoContexto() {
    const document = crearDocumentoFalso();
    prepararElementosEstaticos(document);
    const contexto = {
        document,
        window: { APP_CONFIG: { WS_URL: 'ws://x' }, location: { search: '', pathname: '/x' }, crypto: {} },
        io() { return { on() {}, emit() {}, connect() {} }; },
        localStorage: { getItem() { return null; }, setItem() {} },
        sessionStorage: { getItem() { return null; }, setItem() {} },
        URLSearchParams: function () { return { get() { return null; } }; },
        navigator: { serviceWorker: { getRegistrations: () => Promise.resolve([]) } },
        Auth: { requireAuth() {} },
        api: {},
        console,
    };
    cargarScriptPresentacionDocente(contexto);
    return { contexto, document };
}

let pasados = 0;
function ok(desc, fn) {
    try {
        fn();
        pasados++;
        console.log(`  ok - ${desc}`);
    } catch (err) {
        console.error(`  FAIL - ${desc}`);
        console.error(err);
        process.exitCode = 1;
    }
}

function estaOculto(document, id) {
    return document.getElementById(id).classList.contains('hidden');
}

console.log('btn-iniciar-pregunta — se revela con pregunta, sigue oculto sin ella');

ok('tipo "multiple" con slideAbierta=false → botón VISIBLE (no hidden)', () => {
    const { contexto, document } = nuevoContexto();
    vm.runInContext(`
        PD.presentacion = { diapositivas: [
            { tipo: 'multiple', pregunta: '¿Cuál es la capital de Colombia?',
              opciones: ['Bogotá', 'Medellín', 'Cali', 'Cartagena'], correcta: 0, tiempo_s: 20, puntos: 100 }
        ]};
        PD.slideIndex = 0;
        PD.slideAbierta = false;
        renderSlideActual();
    `, contexto);
    assert.equal(estaOculto(document, 'btn-iniciar-pregunta'), false);
});

ok('tipo "verdadero_falso" con slideAbierta=false → botón VISIBLE (no hidden)', () => {
    const { contexto, document } = nuevoContexto();
    vm.runInContext(`
        PD.presentacion = { diapositivas: [
            { tipo: 'verdadero_falso', pregunta: '¿La Tierra es plana?',
              opciones: ['Verdadero', 'Falso'], correcta: 1, tiempo_s: 15, puntos: 100 }
        ]};
        PD.slideIndex = 0;
        PD.slideAbierta = false;
        renderSlideActual();
    `, contexto);
    assert.equal(estaOculto(document, 'btn-iniciar-pregunta'), false);
});

ok('tipo "contenido" → botón sigue OCULTO', () => {
    const { contexto, document } = nuevoContexto();
    vm.runInContext(`
        PD.presentacion = { diapositivas: [
            { tipo: 'contenido', titulo: 'A', cuerpo: 'x', notas_docente: 'x' }
        ]};
        PD.slideIndex = 0;
        PD.slideAbierta = false;
        renderSlideActual();
    `, contexto);
    assert.equal(estaOculto(document, 'btn-iniciar-pregunta'), true);
});

ok('tipo "separador" → botón sigue OCULTO', () => {
    const { contexto, document } = nuevoContexto();
    vm.runInContext(`
        PD.presentacion = { diapositivas: [
            { tipo: 'separador', titulo: 'Sección 1' }
        ]};
        PD.slideIndex = 0;
        PD.slideAbierta = false;
        renderSlideActual();
    `, contexto);
    assert.equal(estaOculto(document, 'btn-iniciar-pregunta'), true);
});

ok('pregunta con slideAbierta=true → btn-iniciar-pregunta OCULTO, btn-revelar VISIBLE', () => {
    const { contexto, document } = nuevoContexto();
    vm.runInContext(`
        PD.presentacion = { diapositivas: [
            { tipo: 'multiple', pregunta: '¿Cuál?', opciones: ['A', 'B'], correcta: 0, tiempo_s: 20, puntos: 100 }
        ]};
        PD.slideIndex = 0;
        PD.slideAbierta = true;
        renderSlideActual();
    `, contexto);
    assert.equal(estaOculto(document, 'btn-iniciar-pregunta'), true);
    assert.equal(estaOculto(document, 'btn-revelar'), false);
});

ok('opciones de la pregunta se pintan en el proyector (enunciado + cada opción)', () => {
    const { contexto, document } = nuevoContexto();
    vm.runInContext(`
        PD.presentacion = { diapositivas: [
            { tipo: 'multiple', pregunta: '¿Cuál es la capital de Colombia?',
              opciones: ['Bogotá', 'Medellín', 'Cali', 'Cartagena'], correcta: 0, tiempo_s: 20, puntos: 100 }
        ]};
        PD.slideIndex = 0;
        PD.slideAbierta = false;
        renderSlideActual();
    `, contexto);
    const proyectable = document.getElementById('slide-proyectable').innerHTML;
    assert.match(proyectable, /¿Cuál es la capital de Colombia\?/);
    const opciones = document.getElementById('slide-opciones-proyeccion').innerHTML;
    assert.match(opciones, /Bogotá/);
    assert.match(opciones, /Cartagena/);
});

console.log(`\n${pasados} aserciones OK` + (process.exitCode ? ' — HUBO FALLAS ARRIBA' : ''));
