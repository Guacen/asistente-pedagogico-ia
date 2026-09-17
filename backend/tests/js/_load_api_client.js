// Harness compartido: carga el frontend/js/api.js REAL (sin tocarlo, sin
// transpilar) en un contexto de node:vm con stubs mínimos de window/
// localStorage/fetch — api.js es un <script> clásico de navegador (no
// un módulo CommonJS/ESM), así que esto es lo más fiel posible a cómo
// corre de verdad sin necesitar un navegador ni jsdom (no está instalado
// en este repo — cero dependencias nuevas a propósito).
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const API_JS_PATH = path.join(__dirname, '..', '..', 'frontend', 'js', 'api.js');

function crearLocalStorageStub(inicial = {}) {
  const store = { ...inicial };
  return {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
    _store: store,
  };
}

/**
 * Carga una instancia fresca de ApiClient (como `window.api`) en un
 * contexto aislado.
 * @param {object} opts
 * @param {Function} opts.fetchImpl - reemplaza fetch global dentro del sandbox
 * @param {object} [opts.localStorageInicial] - contenido inicial de localStorage
 * @returns {{ api: object, localStorage: object, location: object, sandbox: object }}
 */
function cargarApiClient({ fetchImpl, localStorageInicial = {} }) {
  const localStorageStub = crearLocalStorageStub(localStorageInicial);
  const locationStub = {
    pathname: '/dashboard.html',
    search: '',
    href: 'https://usemaestria.co/dashboard.html',
    replace(url) { this._replacedTo = url; this.href = url; },
  };
  const windowStub = {
    APP_CONFIG: { API_URL: 'https://api.test.local' },
    location: locationStub,
  };

  const sandbox = {
    window: windowStub,
    localStorage: localStorageStub,
    fetch: fetchImpl,
    console,
    URLSearchParams,
    URL,
    FormData: class FormDataStub {},
    Response,
    Headers,
    Request,
  };
  vm.createContext(sandbox);
  const codigo = fs.readFileSync(API_JS_PATH, 'utf8');
  new vm.Script(codigo, { filename: 'api.js' }).runInContext(sandbox);

  return {
    api: sandbox.window.api,
    localStorage: localStorageStub,
    location: locationStub,
    sandbox,
  };
}

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

module.exports = { cargarApiClient, jsonResponse, crearLocalStorageStub };
