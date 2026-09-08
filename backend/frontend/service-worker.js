// Service worker de Maestr.ia — estrategia cache-first para assets estáticos.
// Las peticiones a /api/* NUNCA se cachean: siempre van a red.

// v4: bump forzado — el CSP (header de /index.html y otras páginas
// precacheadas) cambió en el server (PR #72) pero el header viejo quedó
// servido desde el caché del SW indefinidamente, porque una Response
// cacheada incluye sus headers tal como estaban al momento de guardarla.
// Este bump + skipWaiting()/clients.claim() de abajo son el fix real:
// antes, un SW nuevo se quedaba "waiting" hasta que el usuario cerrara
// TODAS las pestañas del sitio — cada fix de estáticos/headers requería
// que alguien limpiara el caché a mano. Con skipWaiting() el SW nuevo
// se activa apenas termina de instalar (sin esperar a las pestañas
// viejas) y con clients.claim() toma control inmediato de las pestañas
// ya abiertas — el próximo fetch (o navegación) en cualquier pestaña ya
// usa la versión nueva, sin necesidad de cerrar nada.
const CACHE_NAME = 'maestria-v4';

// Páginas principales + CSS/JS/assets locales. El resto de los HTML
// (verificar-email, recuperar-password, nueva-password, politica-datos,
// panel-docente, grupo-panel) se cachean en runtime la primera vez que
// se visitan (ver fetch handler), no en el install.
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/login.html',
  '/registro.html',
  '/dashboard.html',
  '/chat.html',
  '/grupos.html',
  '/cuenta.html',
  '/precios.html',
  '/css/main.css',
  '/css/brand.css',
  '/js/config.js',
  '/js/api.js',
  '/js/auth.js',
  '/js/main.js',
  '/js/grupos.js',
  '/js/chat.js',
  '/assets/logo.png',
  '/assets/icon.png',
];

self.addEventListener('install', (event) => {
  // No esperar a que las pestañas viejas se cierren — activar el SW nuevo
  // apenas termine de instalar (precache incluido).
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    Promise.all([
      caches.keys().then((nombres) =>
        Promise.all(
          nombres
            .filter((nombre) => nombre !== CACHE_NAME)
            .map((nombre) => caches.delete(nombre))
        )
      ),
      // Tomar control de las pestañas ya abiertas de inmediato — sin esto,
      // aunque el SW nuevo ya esté activo, las pestañas abiertas ANTES de
      // este deploy siguen siendo controladas por el SW viejo hasta que
      // navegan o recargan.
      self.clients.claim(),
    ])
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // La API y el WebSocket de Socket.io siempre van a red — nunca se cachean.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/socket.io/')) {
    return;
  }

  // Solo cacheamos GET — POST/PUT/PATCH/DELETE siempre van a red.
  if (event.request.method !== 'GET') {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cacheado) => {
      if (cacheado) return cacheado;

      return fetch(event.request).then((respuesta) => {
        if (respuesta && respuesta.ok) {
          const copia = respuesta.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copia));
        }
        return respuesta;
      });
    })
  );
});
