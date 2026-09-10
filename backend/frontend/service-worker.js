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

// SPRINT 3: dispositivos que todavía no habían actualizado a esta versión
// pueden tener cachés huérfanas de versiones cache-first muy anteriores
// (maestria-v2/v3/v4) sentadas en Cache Storage — nada las lee ya (este SW
// no tiene fetch handler), pero tampoco nadie las había borrado nunca.
// Al activar, se borran TODAS sin excepción — no hay ningún caché que
// este SW necesite conservar.
self.addEventListener('activate', (event) => {
    event.waitUntil(
        Promise.all([
            caches.keys().then((nombres) => Promise.all(nombres.map((n) => caches.delete(n)))),
            clients.claim(),
        ])
    );
});
// Sin fetch handler — el navegador maneja todo directamente.
