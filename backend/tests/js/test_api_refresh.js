// Sprint auto-refresh-jwt-frontend, Parte A.
//
// Carga el frontend/js/api.js REAL (ver _load_api_client.js) y prueba
// la orquestación de refresh-y-reintento con un fetch mockeado — nada
// de esto puede probarse en Python porque es lógica de concurrencia
// async que vive enteramente en el navegador. Corre con el test runner
// nativo de Node (`node --test`), sin dependencias nuevas: no hay
// package.json en este repo y este sprint no le agrega uno.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { cargarApiClient, jsonResponse } = require('./_load_api_client.js');

const TOKEN_EXPIRADO = 'token-expirado';
const TOKEN_NUEVO = 'token-nuevo';
const REFRESH_VALIDO = 'refresh-valido';
const REFRESH_NUEVO = 'refresh-nuevo';

function bearer(req) {
  const h = req.headers instanceof Headers ? req.headers : new Headers(req.headers || {});
  return h.get('Authorization') || (req.headers && req.headers.Authorization) || '';
}

// ═══════════════════════════════════════════════════════════════
// ESCENARIO COMPLETO — login → expira → petición → refresh
// transparente → la petición original se completa → nunca vuelve a login
// ═══════════════════════════════════════════════════════════════

test('escenario completo: request con token vencido se refresca y se completa sola, sin volver a login', async () => {
  let llamadasRefresh = 0;
  const { api, localStorage, location } = cargarApiClient({
    localStorageInicial: { token: TOKEN_EXPIRADO, refresh_token: REFRESH_VALIDO },
    fetchImpl: async (url, opts = {}) => {
      const auth = (opts.headers || {}).Authorization || '';
      if (url.endsWith('/api/auth/refresh')) {
        llamadasRefresh += 1;
        const body = JSON.parse(opts.body);
        assert.equal(body.refresh_token, REFRESH_VALIDO);
        return jsonResponse(200, {
          access_token: TOKEN_NUEVO, refresh_token: REFRESH_NUEVO, token_type: 'bearer',
        });
      }
      if (url.endsWith('/api/grupos')) {
        if (auth === `Bearer ${TOKEN_EXPIRADO}`) {
          return jsonResponse(401, { detail: 'Token inválido o expirado' });
        }
        if (auth === `Bearer ${TOKEN_NUEVO}`) {
          return jsonResponse(200, [{ id_grupo: 'g1', nombre_grupo: 'Grupo A' }]);
        }
        return jsonResponse(401, { detail: 'token inesperado en el mock' });
      }
      throw new Error(`URL no esperada en el mock: ${url}`);
    },
  });

  const resultado = await api.request('/api/grupos');

  assert.deepEqual(resultado, [{ id_grupo: 'g1', nombre_grupo: 'Grupo A' }]);
  assert.equal(llamadasRefresh, 1);
  assert.equal(localStorage.getItem('token'), TOKEN_NUEVO);
  assert.equal(localStorage.getItem('refresh_token'), REFRESH_NUEVO);
  assert.equal(location._replacedTo, undefined, 'nunca debió redirigir a login');
});

// ═══════════════════════════════════════════════════════════════
// CONCURRENCIA — 5 peticiones simultáneas con token vencido → 1 refresh
// ═══════════════════════════════════════════════════════════════

test('5 peticiones simultáneas con token vencido disparan UN solo refresh', async () => {
  let llamadasRefresh = 0;
  const endpoints = ['/a', '/b', '/c', '/d', '/e'];

  const { api } = cargarApiClient({
    localStorageInicial: { token: TOKEN_EXPIRADO, refresh_token: REFRESH_VALIDO },
    fetchImpl: async (url, opts = {}) => {
      const auth = (opts.headers || {}).Authorization || '';
      if (url.endsWith('/api/auth/refresh')) {
        llamadasRefresh += 1;
        // Sin await extra acá a propósito — si el dedup no funciona,
        // queremos que la carrera sea lo más ajustada posible.
        return jsonResponse(200, {
          access_token: TOKEN_NUEVO, refresh_token: REFRESH_NUEVO, token_type: 'bearer',
        });
      }
      const endpoint = endpoints.find((e) => url.endsWith(e));
      if (endpoint) {
        if (auth === `Bearer ${TOKEN_EXPIRADO}`) {
          return jsonResponse(401, { detail: 'Token inválido o expirado' });
        }
        return jsonResponse(200, { endpoint, ok: true });
      }
      throw new Error(`URL no esperada: ${url}`);
    },
  });

  const resultados = await Promise.all(endpoints.map((e) => api.request(e)));

  assert.equal(llamadasRefresh, 1, `esperaba exactamente 1 refresh, hubo ${llamadasRefresh}`);
  resultados.forEach((r, i) => assert.deepEqual(r, { endpoint: endpoints[i], ok: true }));
});

// ═══════════════════════════════════════════════════════════════
// REFRESH TOKEN REVOCADO/INVÁLIDO → cierra sesión y manda a login
// ═══════════════════════════════════════════════════════════════

test('refresh token revocado: cierra sesión (limpia localStorage) y redirige a login', async () => {
  const { api, localStorage, location } = cargarApiClient({
    localStorageInicial: { token: TOKEN_EXPIRADO, refresh_token: 'refresh-revocado', user: '{"nombre":"Ana"}' },
    fetchImpl: async (url, opts = {}) => {
      const auth = (opts.headers || {}).Authorization || '';
      if (url.endsWith('/api/auth/refresh')) {
        // El backend rechaza explícito — token blacklisteado/vencido.
        return jsonResponse(401, { detail: 'Refresh token inválido o expirado' });
      }
      if (url.endsWith('/api/grupos')) {
        assert.equal(auth, `Bearer ${TOKEN_EXPIRADO}`);
        return jsonResponse(401, { detail: 'Token inválido o expirado' });
      }
      throw new Error(`URL no esperada: ${url}`);
    },
  });

  await assert.rejects(() => api.request('/api/grupos'));

  assert.equal(localStorage.getItem('token'), null, 'el access token debió limpiarse');
  assert.equal(localStorage.getItem('refresh_token'), null, 'el refresh token debió limpiarse');
  assert.equal(localStorage.getItem('user'), null, 'el usuario cacheado debió limpiarse');
  assert.equal(location._replacedTo, 'login.html');
});

// ═══════════════════════════════════════════════════════════════
// FALLO DE RED durante el refresh — NO cierra sesión, no redirige
// ═══════════════════════════════════════════════════════════════

test('fallo de red durante el refresh no cierra la sesión ni redirige', async () => {
  const { api, localStorage, location } = cargarApiClient({
    localStorageInicial: { token: TOKEN_EXPIRADO, refresh_token: REFRESH_VALIDO },
    fetchImpl: async (url) => {
      if (url.endsWith('/api/auth/refresh')) {
        throw new TypeError('Failed to fetch'); // fetch real lanza esto sin conexión
      }
      if (url.endsWith('/api/grupos')) {
        return jsonResponse(401, { detail: 'Token inválido o expirado' });
      }
      throw new Error(`URL no esperada: ${url}`);
    },
  });

  await assert.rejects(() => api.request('/api/grupos'));

  // A diferencia del caso "revocado": la sesión NO se toca. El refresh
  // token guardado podría seguir siendo perfectamente válido — el
  // problema fue no poder preguntarle al servidor, no que la respuesta
  // haya sido "no".
  assert.equal(localStorage.getItem('token'), TOKEN_EXPIRADO);
  assert.equal(localStorage.getItem('refresh_token'), REFRESH_VALIDO);
  assert.equal(location._replacedTo, undefined, 'un fallo de red no debe redirigir a login');
});

// ═══════════════════════════════════════════════════════════════
// MÁXIMO UN INTENTO DE REFRESH POR PETICIÓN — nunca un loop
// ═══════════════════════════════════════════════════════════════

test('si el reintento post-refresh también da 401, no vuelve a intentar refrescar (sin loop)', async () => {
  let llamadasRefresh = 0;
  let llamadasGrupos = 0;

  const { api } = cargarApiClient({
    localStorageInicial: { token: TOKEN_EXPIRADO, refresh_token: REFRESH_VALIDO },
    fetchImpl: async (url, opts = {}) => {
      if (url.endsWith('/api/auth/refresh')) {
        llamadasRefresh += 1;
        return jsonResponse(200, {
          access_token: TOKEN_NUEVO, refresh_token: REFRESH_NUEVO, token_type: 'bearer',
        });
      }
      if (url.endsWith('/api/grupos')) {
        llamadasGrupos += 1;
        // SIEMPRE 401, incluso con el token "nuevo" — simula un backend
        // que rechaza por otro motivo (p.ej. cuenta deshabilitada).
        return jsonResponse(401, { detail: 'Token inválido o expirado' });
      }
      throw new Error(`URL no esperada: ${url}`);
    },
  });

  await assert.rejects(() => api.request('/api/grupos'));

  assert.equal(llamadasGrupos, 2, 'debe intentar la petición original + UN reintento, nunca más');
  assert.equal(llamadasRefresh, 1, 'debe refrescar una sola vez, nunca en loop');
});

// ═══════════════════════════════════════════════════════════════
// email_no_verificado — NO dispara refresh (no es un token vencido)
// ═══════════════════════════════════════════════════════════════

test('401 con code=email_no_verificado no dispara ningún refresh', async () => {
  let llamadasRefresh = 0;
  const { api } = cargarApiClient({
    localStorageInicial: { token: 'token-valido-pero-sin-verificar', refresh_token: REFRESH_VALIDO },
    fetchImpl: async (url) => {
      if (url.endsWith('/api/auth/refresh')) {
        llamadasRefresh += 1;
        return jsonResponse(200, { access_token: 'x', refresh_token: 'y', token_type: 'bearer' });
      }
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, {
          detail: { code: 'email_no_verificado', message: 'Verifica tu correo' },
        });
      }
      throw new Error(`URL no esperada: ${url}`);
    },
  });

  await assert.rejects(() => api.getMe());
  assert.equal(llamadasRefresh, 0, 'email_no_verificado no debe gastar cuota de refresh');
});

// ═══════════════════════════════════════════════════════════════
// logout() — manda el refresh_token al backend
// ═══════════════════════════════════════════════════════════════

test('api.logout manda el access token en el header y el refresh token en el body', async () => {
  let logoutLlamado = null;
  const { api } = cargarApiClient({
    localStorageInicial: { token: 'access-actual', refresh_token: 'refresh-actual' },
    fetchImpl: async (url, opts = {}) => {
      if (url.endsWith('/api/auth/logout')) {
        logoutLlamado = { auth: opts.headers.Authorization, body: JSON.parse(opts.body) };
        return jsonResponse(200, { mensaje: 'Sesión cerrada correctamente' });
      }
      throw new Error(`URL no esperada: ${url}`);
    },
  });

  await api.logout('refresh-actual');

  assert.deepEqual(logoutLlamado, {
    auth: 'Bearer access-actual',
    body: { refresh_token: 'refresh-actual' },
  });
});

test('api.logout nunca lanza aunque la red falle (best-effort)', async () => {
  const { api } = cargarApiClient({
    localStorageInicial: { token: 'access-actual', refresh_token: 'refresh-actual' },
    fetchImpl: async () => { throw new TypeError('Failed to fetch'); },
  });

  await assert.doesNotReject(() => api.logout('refresh-actual'));
});
