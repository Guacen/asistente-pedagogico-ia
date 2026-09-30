# Reglas del proyecto — Maestr.ia

## CSS: `var()` en atributos `style` inline SIEMPRE lleva valor de respaldo

Cualquier `var(--brand-*)` (u otra custom property) usado en un atributo
`style="..."` inline — o asignado dinámicamente desde JS a `element.style.*`
— **debe** incluir un valor de respaldo:

```html
<!-- MAL -->
<button style="background: var(--brand-primary);">Unirme</button>

<!-- BIEN -->
<button style="background: var(--brand-primary, #1D9E75);">Unirme</button>
```

**Por qué:** si `css/brand.css` no llega a cargar (red mala, CDN caído, bloqueo
de CSP, service worker viejo sirviendo una copia rota desde caché), `var()`
sin fallback resuelve a nada — el navegador ignora la declaración entera. En
`join.html` esto causó un bug real en producción: el botón "Unirme" quedaba
con `background` transparente y texto blanco (`class="text-white"`) sobre una
tarjeta blanca, es decir, **invisible**, en Firefox Focus, Safari iOS y
Chrome Android — verificado en 4 navegadores móviles reales (SPRINT 3).

Valores de respaldo actuales (tomados de `backend/frontend/css/brand.css`):

| Variable | Valor de respaldo |
|---|---|
| `--brand-primary` | `#1D9E75` |
| `--brand-primary-hover` | `#0F6E56` |
| `--brand-dark` | `#0B3D2E` |
| `--brand-amber` | `#F5B731` |
| `--brand-book` | `#2ECC71` |
| `--brand-mint` | `#E1F5EE` |

Esto aplica tanto si la página carga `brand.css` externamente como si define
sus propias variables `:root` inline (páginas autosuficientes como
`join.html`) — el fallback es defensa en profundidad barata, no cuesta nada
tenerlo aunque la variable "debería" estar siempre disponible.

## Tests de manejadores de excepción no capturadas: `TestClient(app, raise_server_exceptions=False)`

`TestClient(app)` con sus valores por default tiene `raise_server_exceptions=True`
— Starlette **re-lanza** la excepción hacia el propio test en vez de dejar
que un `@app.exception_handler(Exception)` la convierta en una respuesta,
que es exactamente lo que SÍ pasa en producción con un servidor ASGI real
(uvicorn). Un test que golpea una ruta que dispara una excepción no
manejada y espera ver la respuesta del handler global (status 500,
`correlation_id`, etc.) va a fallar con la excepción "escapándose" hacia
pytest, aunque el handler esté funcionando perfecto — no es un bug del
código, es el comportamiento por default del cliente de pruebas.

```python
# MAL — la excepción se re-lanza hacia el test, nunca llega al handler
r = client_no_auth.get("/ruta-que-explota")

# BIEN — deja que el handler responda, como en producción
with TestClient(app, raise_server_exceptions=False) as c:
    r = c.get("/ruta-que-explota")
```

Sólo hace falta este cliente especial para los tests que **ejercitan el
handler global de excepciones en sí** (ver `errores.py` /
`main.py::excepcion_no_manejada` y
`tests/test_errores_correlation_id.py`) — el resto de los tests, que
esperan que un endpoint responda con un error ya manejado (`HTTPException`,
`error_manejable()`), siguen usando los fixtures normales (`client`,
`client_no_auth`) sin ningún cambio.

## Páginas críticas de cara al estudiante deben ser autosuficientes

`join.html` la abren estudiantes en teléfonos ajenos, con datos móviles
malos, en navegadores que no controlamos — no puede depender de que
Tailwind CDN, Font Awesome CDN o `brand.css` externo carguen. Esa página
inlinea todo su CSS y usa SVG inline en vez de iconos de fuente. Cualquier
página nueva con ese mismo perfil de riesgo (estudiante, sin cuenta,
dispositivo/red no controlados) debe seguir el mismo criterio.

## Un flag que apaga una función debe cerrar TODAS sus vías de entrada, no sólo la HTTP

`FEATURE_PRESENTACIONES=False` gateaba el router HTTP
(`/api/presentaciones/*` → 404 vía una dependency que se re-evalúa en
cada request) pero no los handlers de Socket.io de la misma función:
`@sio.on("presentacion:...")` se registra UNA VEZ, en el momento en que
se importa el módulo que los define — no en cada conexión — así que
`import presentacion_events` sin condición en `main.py` los dejaba
activos sin importar el flag. Confirmado en producción (Sprint F, Parte
G1): con el flag apagado, `POST /api/presentaciones/generar` daba 404,
pero `socket.emit('presentacion:unirse', {...})` seguía respondiendo y
consultando la base de datos.

**Regla:** cuando una función se apaga con un flag, auditar TODAS sus
vías de entrada — HTTP, Socket.io, tareas en background, cron — no sólo
la que se probó primero. Un mecanismo de request-por-request
(`Depends()` de FastAPI) no protege un mecanismo de registro-al-importar
(`@sio.on(...)`); cada uno necesita su propio gate, en el punto donde
efectivamente se evalúa. Ver `main.py` (el `import presentacion_events`
ahora vive detrás de `if settings.FEATURE_PRESENTACIONES:`) y
`tests/test_socketio_flag_presentaciones.py`.

## Migraciones fallidas no tumban el arranque — no es un default, es una decisión con condición de reversa

Una migración de `migrate.py` que falla nunca mata el proceso: se
registra en `MIGRATION_ERRORS` con traceback completo y el arranque
sigue. `GET /health` responde 200 siempre, a propósito — **no es el
canal para detectar una migración rota**. El canal es `GET /api/version`
(mismo `MIGRATION_ERRORS`) y el banner de admin en el dashboard
(`mostrarBannerMigracionesFallidasSiAplica`, sólo `es_admin=true`).

**Por qué** (razonamiento completo en el docstring de `migrate.py`,
Sprint F Parte G3): la recomendación estándar de la industria —
migración fallida mata el arranque, así el balanceador conserva la
réplica anterior — asume múltiples réplicas y un healthcheck con
rollback automático verificado. Este proyecto no tiene ninguna de las
dos: un solo servicio en Railway, Health Check Path vacío. El 16 de
septiembre de 2026, una sola columna con tipo inválido en una migración
de una función archivada (Presentaciones, ni siquiera activa) tumbó
TODO el sitio 40 minutos porque el proceso moría al arrancar y no había
ninguna réplica sana detrás. Aislar cada migración (`_paso()`) convirtió
ese mismo tipo de fallo en algo localizado y visible en vez de total y
silencioso.

**Cuándo reconsiderar esto** (verificado, no supuesto — no antes):
- el servicio pasa a correr con más de una réplica en Railway; o
- se configura un Health Check Path en Railway y se confirma con una
  prueba real (no leyendo documentación) que un healthcheck fallido
  dispara rollback automático sin intervención manual.

Sin ninguna de las dos, no cambiar este comportamiento — volver a
"migración fallida mata el arranque" sin esas piezas reintroduciría el
incidente del 16 de septiembre, no lo previene.
