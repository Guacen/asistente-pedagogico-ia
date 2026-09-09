// Service worker mínimo — SIN caché.
//
// El service worker anterior (cache-first, v2-v4) causaba fallos
// intermitentes al cargar Tailwind/Font Awesome/Google Fonts desde su
// CDN: "FetchEvent.respondWith received an error: TypeError: Load
// failed". Interceptar y cachear respuestas cross-origin (muchas
// opacas, por scripts <script src> sin crossorigin) resultó frágil
// entre navegadores. Este SW no cachea nada — sólo reenvía cada
// request tal cual a la red, eliminando esa clase de bug de raíz.
//
// skipWaiting()/clients.claim() se mantienen (del fix anterior, PR #73)
// para que este cambio también llegue a pestañas ya abiertas sin que
// el usuario tenga que cerrar todo el navegador — importante porque
// mientras el SW viejo (cache-first) siga activo en una pestaña, el
// bug reportado sigue ocurriendo ahí.
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
