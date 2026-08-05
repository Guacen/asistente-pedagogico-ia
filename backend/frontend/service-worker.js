// Service worker de Maestr.ia — estrategia cache-first para assets estáticos.
// Las peticiones a /api/* NUNCA se cachean: siempre van a red.

const CACHE_NAME = 'maestria-v1';

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
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((nombres) =>
      Promise.all(
        nombres
          .filter((nombre) => nombre !== CACHE_NAME)
          .map((nombre) => caches.delete(nombre))
      )
    )
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
