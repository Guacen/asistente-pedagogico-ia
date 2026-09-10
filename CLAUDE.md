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

## Páginas críticas de cara al estudiante deben ser autosuficientes

`join.html` la abren estudiantes en teléfonos ajenos, con datos móviles
malos, en navegadores que no controlamos — no puede depender de que
Tailwind CDN, Font Awesome CDN o `brand.css` externo carguen. Esa página
inlinea todo su CSS y usa SVG inline en vez de iconos de fuente. Cualquier
página nueva con ese mismo perfil de riesgo (estudiante, sin cuenta,
dispositivo/red no controlados) debe seguir el mismo criterio.
