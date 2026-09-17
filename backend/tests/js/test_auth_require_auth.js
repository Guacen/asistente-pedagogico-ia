// Sprint auto-refresh-jwt-frontend, Parte A — el hallazgo original de la
// auditoría: "requireAuth() desloguea sin intentar refrescar". Prueba
// auth.js REAL (junto con api.js, su dependencia) contra el escenario
// concreto: un docente vuelve a una pestaña con el access token ya
// vencido (60 min) pero el refresh token (30 días) todavía vivo.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { cargarAuth, jsonResponse, jwtFalso } = require('./_load_auth.js');

const AHORA_S = Math.floor(Date.now() / 1000);
const TOKEN_VENCIDO = jwtFalso({ sub: 'doc-1', exp: AHORA_S - 3600 }); // venció hace 1h
const TOKEN_VIGENTE = jwtFalso({ sub: 'doc-1', exp: AHORA_S + 3600 }); // vence en 1h
const TOKEN_NUEVO = jwtFalso({ sub: 'doc-1', exp: AHORA_S + 3600 });

test('requireAuth() con token vencido: NO redirige de inmediato, refresca en background y se queda en la página', async () => {
  let llamadasRefresh = 0;
  const { Auth, localStorage, location } = cargarAuth({
    localStorageInicial: { token: TOKEN_VENCIDO, refresh_token: 'refresh-valido' },
    fetchImpl: async (url, opts = {}) => {
      if (url.endsWith('/api/auth/refresh')) {
        llamadasRefresh += 1;
        return jsonResponse(200, {
          access_token: TOKEN_NUEVO, refresh_token: 'refresh-nuevo', token_type: 'bearer',
        });
      }
      throw new Error(`URL no esperada: ${url}`);
    },
  });

  Auth.requireAuth();

  // Síncrono: NO debió redirigir todavía — el refresh está en vuelo.
  assert.equal(location._replacedTo, undefined, 'requireAuth no debe redirigir de inmediato');

  // Esperar a que el refresh en background termine (microtask + la
  // promesa de fetch mockeada).
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(llamadasRefresh, 1);
  assert.equal(localStorage.getItem('token'), TOKEN_NUEVO, 'el token debió renovarse solo');
  assert.equal(location._replacedTo, undefined, 'nunca debió mandar a login — el refresh funcionó');
});

test('requireAuth() con token vigente no toca nada (comportamiento normal, sin red)', () => {
  let fetchLlamado = false;
  const { Auth, location } = cargarAuth({
    localStorageInicial: { token: TOKEN_VIGENTE, refresh_token: 'refresh-valido' },
    fetchImpl: async () => { fetchLlamado = true; throw new Error('no debería llamarse'); },
  });

  Auth.requireAuth();

  assert.equal(fetchLlamado, false);
  assert.equal(location._replacedTo, undefined);
});

test('requireAuth() sin ningún token manda a login de inmediato, sin intentar refrescar', () => {
  let fetchLlamado = false;
  const { Auth, location } = cargarAuth({
    localStorageInicial: {},
    fetchImpl: async () => { fetchLlamado = true; throw new Error('no debería llamarse'); },
  });

  Auth.requireAuth();

  assert.equal(fetchLlamado, false);
  assert.equal(location._replacedTo, 'login.html');
});

test('requireAuth() con token vencido y refresh también inválido: limpia la sesión y manda a login', async () => {
  const { Auth, localStorage, location } = cargarAuth({
    localStorageInicial: { token: TOKEN_VENCIDO, refresh_token: 'refresh-muerto', user: '{"nombre":"Ana"}' },
    fetchImpl: async (url) => {
      if (url.endsWith('/api/auth/refresh')) {
        return jsonResponse(401, { detail: 'Refresh token inválido o expirado' });
      }
      throw new Error(`URL no esperada: ${url}`);
    },
  });

  Auth.requireAuth();
  assert.equal(location._replacedTo, undefined, 'no debe redirigir hasta saber que el refresh falló');

  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(localStorage.getItem('token'), null);
  assert.equal(localStorage.getItem('refresh_token'), null);
  assert.equal(location._replacedTo, 'login.html');
});

// ═══════════════════════════════════════════════════════════════
// isAuthenticated() — ya NO desloguea sólo por ver el exp vencido
// ═══════════════════════════════════════════════════════════════

test('isAuthenticated() con token vencido devuelve true (hay credenciales) y NO limpia el refresh token', () => {
  const { Auth, localStorage } = cargarAuth({
    localStorageInicial: { token: TOKEN_VENCIDO, refresh_token: 'refresh-valido' },
    fetchImpl: async () => { throw new Error('isAuthenticated no debe llamar a la red'); },
  });

  assert.equal(Auth.isAuthenticated(), true);
  // Éste es EXACTAMENTE el bug original: isAuthenticated() destruía el
  // refresh token con sólo mirar el exp del access token, sin haber
  // intentado nunca refrescar.
  assert.equal(localStorage.getItem('refresh_token'), 'refresh-valido');
});

test('isAuthenticated() sin ningún token devuelve false', () => {
  const { Auth } = cargarAuth({ localStorageInicial: {}, fetchImpl: async () => { throw new Error('no red'); } });
  assert.equal(Auth.isAuthenticated(), false);
});
