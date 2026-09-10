// Test standalone del render defensivo de `cuerpo`/`titulo`/`pregunta` en
// presentacion-docente.html — cubre BUG 1 (SPRINT 1 presentaciones):
// la IA a veces devuelve `cuerpo` como array en vez de string, y antes de
// este fix la interpolación directa mostraba literalmente "['a', 'b']"
// en pantalla (bug reportado en clase real).
//
// No hay runner JS (jest/vitest) en este repo — se ejecuta directo con
// Node y no está enganchado al pipeline de CI (que sólo corre pytest).
// Correr manualmente: node backend/tests/frontend/test_render_contenido_diapositiva.mjs
//
// Extrae las funciones puras (escapeHtmlPD/normalizarCampoLista/
// textoSeguroPD/renderCuerpoPD) directo del HTML real en vez de
// reimplementarlas acá — así el test falla si alguien las cambia sin
// querer, en lugar de quedar probando una copia desactualizada.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const htmlPath = path.join(__dirname, '..', '..', 'frontend', 'presentacion-docente.html');
const html = readFileSync(htmlPath, 'utf8');

const inicio = html.indexOf('function escapeHtmlPD');
const fin = html.indexOf('function renderSlideActual');
assert.ok(inicio !== -1 && fin !== -1 && fin > inicio,
    'No se encontraron los marcadores esperados en presentacion-docente.html — ¿se renombraron las funciones?');

const snippet = html.slice(inicio, fin);
const contexto = {};
vm.createContext(contexto);
vm.runInContext(`
    ${snippet}
    globalThis.__exports = { escapeHtmlPD, normalizarCampoLista, textoSeguroPD, renderCuerpoPD, renderDiagramaPD };
`, contexto);
const { normalizarCampoLista, textoSeguroPD, renderCuerpoPD, renderDiagramaPD } = contexto.__exports;

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

console.log('renderCuerpoPD — array real');
ok('renderiza <ul><li> por cada elemento', () => {
    const html = renderCuerpoPD([
        'Es un dibujo simplificado que muestra TODAS las fuerzas',
        'El objeto se representa como un punto o forma simple',
    ]);
    assert.match(html, /<ul/);
    assert.match(html, /<li>Es un dibujo simplificado que muestra TODAS las fuerzas<\/li>/);
    assert.match(html, /<li>El objeto se representa como un punto o forma simple<\/li>/);
    assert.doesNotMatch(html, /\[.*'.*'.*\]/, 'no debe quedar rastro de corchetes/comillas de repr de lista');
});

console.log('renderCuerpoPD — string plano');
ok('renderiza <p> con el texto tal cual', () => {
    const html = renderCuerpoPD('Explicación en un solo párrafo.');
    assert.match(html, /<p/);
    assert.match(html, /Explicación en un solo párrafo\./);
    assert.doesNotMatch(html, /<ul/);
});

console.log('renderCuerpoPD — string que en realidad es un array serializado como JSON');
ok('parsea el JSON y renderiza <ul><li>', () => {
    const html = renderCuerpoPD('["Primer punto", "Segundo punto"]');
    assert.match(html, /<ul/);
    assert.match(html, /<li>Primer punto<\/li>/);
    assert.match(html, /<li>Segundo punto<\/li>/);
});

console.log('renderCuerpoPD — XSS: el contenido de cada <li> debe estar escapado');
ok('escapa < y > dentro de un item de la lista', () => {
    const html = renderCuerpoPD(['<script>alert(1)</script>']);
    assert.doesNotMatch(html, /<script>alert/);
    assert.match(html, /&lt;script&gt;/);
});

console.log('textoSeguroPD — campos de una sola línea (título/pregunta/instrucción)');
ok('une un array en un solo string en vez de dejarlo como lista', () => {
    assert.equal(textoSeguroPD(['¿Cuál', 'es', 'la fuerza?']), '¿Cuál es la fuerza?');
});
ok('deja un string normal intacto', () => {
    assert.equal(textoSeguroPD('¿Cuál es la fuerza?'), '¿Cuál es la fuerza?');
});
ok('parsea un string-JSON de array y lo une', () => {
    assert.equal(textoSeguroPD('["¿Cuál", "es?"]'), '¿Cuál es?');
});

console.log('normalizarCampoLista — string que PARECE lista pero no es JSON válido (repr de Python, comillas simples)');
ok('no revienta y cae a null (texto plano) en vez de tirar excepción', () => {
    // str(['a', 'b']) en Python produce esto — NO es JSON válido (comillas simples).
    assert.equal(normalizarCampoLista("['a', 'b']"), null);
});

console.log('\nrenderDiagramaPD — SPRINT 2 Parte C: catálogo cerrado de diagramas SVG');

const CASOS_VALIDOS = {
    fuerzas: { objeto: 'Caja', fuerzas: [
        { nombre: 'Peso', direccion: 'abajo', magnitud: 3 },
        { nombre: 'Normal', direccion: 'arriba', magnitud: 3 },
    ] },
    ciclo: { pasos: ['Paso 1', 'Paso 2', 'Paso 3', 'Paso 4'] },
    linea_tiempo: { eventos: [
        { etiqueta: '1810', texto: 'Independencia' },
        { etiqueta: '1819', texto: 'Batalla de Boyacá' },
    ] },
    comparacion: {
        titulo_izquierda: 'Mitosis', items_izquierda: ['1 división', '2 células'],
        titulo_derecha: 'Meiosis', items_derecha: ['2 divisiones', '4 células'],
    },
    jerarquia: { raiz: 'Reino Animal', hijos: ['Vertebrados', 'Invertebrados'] },
    proceso: { pasos: ['Paso 1', 'Paso 2', 'Paso 3'] },
};

for (const [tipo, datos] of Object.entries(CASOS_VALIDOS)) {
    ok(`"${tipo}" renderiza un <svg> sin lanzar excepción con datos de ejemplo`, () => {
        const html = renderDiagramaPD({ tipo, datos });
        assert.match(html, /<svg/, `"${tipo}" debería producir un <svg>`);
    });
}

ok('un tipo fuera del catálogo cerrado no rompe — devuelve string vacío', () => {
    assert.equal(renderDiagramaPD({ tipo: 'no_existe_en_el_catalogo', datos: {} }), '');
});

ok('diagrama null no rompe — devuelve string vacío', () => {
    assert.equal(renderDiagramaPD(null), '');
});

ok('diagrama con datos incompletos (fuerzas sin fuerzas) no rompe — devuelve string vacío', () => {
    assert.equal(renderDiagramaPD({ tipo: 'fuerzas', datos: {} }), '');
});

ok('un tipo válido con datos.pasos ausente no rompe (ciclo)', () => {
    assert.equal(renderDiagramaPD({ tipo: 'ciclo', datos: {} }), '');
});

ok('texto de un diagrama queda escapado contra XSS', () => {
    const html = renderDiagramaPD({ tipo: 'proceso', datos: { pasos: ['<script>alert(1)</script>', 'Paso 2'] } });
    assert.doesNotMatch(html, /<script>alert/);
    assert.match(html, /&lt;script&gt;/);
});

console.log(`\n${pasados} aserciones OK` + (process.exitCode ? ' — HUBO FALLAS ARRIBA' : ''));
