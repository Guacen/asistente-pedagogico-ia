// Harness compartido para auth.js — carga api.js + auth.js REALES (sin
// tocar ninguno) en el mismo contexto de node:vm, con stubs mínimos de
// document/window/localStorage/fetch. Mismo criterio que
// _load_api_client.js: cero dependencias nuevas (nada de jsdom).
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const API_JS_PATH = path.join(__dirname, '..', '..', 'frontend', 'js', 'api.js');
const AUTH_JS_PATH = path.join(__dirname, '..', '..', 'frontend', 'js', 'auth.js');

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

function crearDocumentStub() {
  const listeners = {};
  return {
    addEventListener(nombre, cb) {
      (listeners[nombre] = listeners[nombre] || []).push(cb);
    },
    querySelectorAll() { return []; }, // updateAuthUI/initLogoutButtons — sin elementos, no-op seguro
    _listeners: listeners,
    _disparar(nombre, evt) { (listeners[nombre] || []).forEach((cb) => cb(evt)); },
  };
}

/**
 * Carga Auth (y su dependencia api) en un contexto aislado.
 * @param {object} opts
 * @param {Function} opts.fetchImpl
 * @param {object} [opts.localStorageInicial]
 * @param {string} [opts.pathname]
 */
function cargarAuth({ fetchImpl, localStorageInicial = {}, pathname = '/dashboard.html' }) {
  const localStorageStub = crearLocalStorageStub(localStorageInicial);
  const locationStub = {
    pathname,
    search: '',
    hostname: 'usemaestria.co',
    href: `https://usemaestria.co${pathname}`,
    replace(url) { this._replacedTo = url; this.href = url; },
  };
  const documentStub = crearDocumentStub();

  const sandbox = {
    window: {
      APP_CONFIG: { API_URL: 'https://api.test.local' },
      location: locationStub,
      addEventListener() {},
      dispatchEvent() {},
    },
    document: documentStub,
    localStorage: localStorageStub,
    fetch: fetchImpl,
    console,
    URLSearchParams,
    URL,
    FormData: class FormDataStub {},
    Response,
    Headers,
    Request,
    CustomEvent: class CustomEventStub { constructor(name, opts) { this.name = name; this.detail = opts && opts.detail; } },
    confirm: () => true,
    setInterval: () => 0, // startAutoRefresh — no hace falta que el timer corra de verdad en estos tests
    // atob/btoa son globales de navegador — Node no los expone en vm
    // contexts. Auth.parseToken() los necesita para decodificar el JWT.
    atob: (b64) => Buffer.from(b64, 'base64').toString('binary'),
    btoa: (str) => Buffer.from(str, 'binary').toString('base64'),
  };
  vm.createContext(sandbox);

  for (const filePath of [API_JS_PATH, AUTH_JS_PATH]) {
    const codigo = fs.readFileSync(filePath, 'utf8');
    new vm.Script(codigo, { filename: path.basename(filePath) }).runInContext(sandbox);
  }

  return {
    Auth: sandbox.window.Auth,
    api: sandbox.window.api,
    localStorage: localStorageStub,
    location: locationStub,
    document: documentStub,
    sandbox,
  };
}

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** JWT sintético (sin firma real — sólo header.payload.signature en
 * base64url, que es todo lo que Auth.parseToken() decodifica). */
function jwtFalso(payload) {
  const b64url = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64')
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `${b64url({ alg: 'none' })}.${b64url(payload)}.firma-falsa`;
}

module.exports = { cargarAuth, jsonResponse, jwtFalso };
