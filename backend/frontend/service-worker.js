// Service worker Maestr.ia — sin intercepción de red.
//
// El SW anterior (fetch passthrough: event.respondWith(fetch(event.request)))
// ya no cacheaba nada, pero seguía intercediendo en cada fetch — suficiente
// para introducir comportamiento distinto entre navegadores frente a
// respuestas cross-origin/opacas (Tailwind, Font Awesome, Google Fonts).
// Sin un fetch handler, el navegador maneja esas peticiones directamente,
// sin pasar por el pipeline de Service Worker en absoluto.
//
// skipWaiting()/clients.claim() se mantienen para que este cambio llegue
// a pestañas ya abiertas sin que el usuario cierre el navegador.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(clients.claim()));
// Sin fetch handler — el navegador maneja todo directamente.
