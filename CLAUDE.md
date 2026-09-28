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
