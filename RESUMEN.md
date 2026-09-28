# RESUMEN — Maestr.ia

*Estado real del proyecto al 2026-09-28. Reemplaza la versión anterior (desfasada desde el PR #55 — el proyecto ya va por el PR #93). Para el historial completo de sprints y el backlog priorizado con detalle línea por línea, ver [`docs/PLAN.md`](docs/PLAN.md) — este documento es la versión ejecutiva: qué está hecho, qué está en curso, qué falta y por qué.*

---

## COMPLETADO

Todo lo listado acá está mergeado en `main` (rama de producción — Railway despliega desde ahí).

**Producto core** (pre-existente a esta sesión, PRs #1–#42):
- Autenticación completa: registro, login JWT, verificación de correo (#32), recuperación de contraseña (#34), consentimiento Ley 1581 (#32).
- Chat multi-modo (planeación/socioemocional/calificación/PIAR/observaciones) con sesiones temáticas y rate limit diario configurable (#9, #10, #25).
- Generador de PIAR con marco legal completo del Decreto 1421 de 2017 (#11, #27, #30, #31) — 10 secciones fijas, template estático + contenido del LLM, verificado por tests de cumplimiento legal.
- Módulo de Observaciones y Seguimiento Estudiantil, Ley 1620/1098 (#41).
- Multi-institución con roles docente/coordinador/rector (#12, #13).
- Gestión de grupos/estudiantes, libro de calificaciones, boletines DOCX.
- Proveedor de IA con fallback Claude → Gemini (#22–#24).
- Identidad de marca Maestr.ia + rebrand de exportaciones DOCX (#27–#29).
- Landing page + precios en COP (#40).
- PWA instalable, responsive en las páginas principales (#42).
- Reset de límites de uso vía endpoint admin (#37).

**Sesión anterior** (PRs #43–#55):
- **#44** — Adaptador de correo Resend (Railway bloquea SMTP saliente), con fallback Resend → SendGrid → SMTP → LogOnly.
- **#45, #46** — Número real de WhatsApp Business en todos los CTAs del sitio.
- **#47** — Política de Tratamiento de Datos y Términos de Uso v1.0 (páginas nuevas).
- **#48, #49** — Seguidor de Malla Curricular: catálogo de 412 DBA del MEN (Derechos Básicos de Aprendizaje), generación de malla por IA, seguimiento de cobertura por período.
- **#50** — Prueba gratuita self-service de 7 días: registro sin tarjeta, bloqueo automático (402) al vencer vía `verify_trial_active`, aplicado a todos los endpoints de producto (REST + Socket.io del chat en tiempo real).
- **#51** — Integración de pagos Wompi: checkout PSE/Nequi/tarjeta, webhook de confirmación con verificación de firma real (corregida contra la documentación oficial de Wompi), reactivación automática de cuentas con trial vencido. Incluye el mismo fix aplicado retroactivamente al webhook de Stripe.
- **#52** — Brand kit oficial del diseñador (logo, isotipo, versión blanca) reemplazando los placeholders.
- **#53** — `Cache-Control: no-cache` en `/assets/*` y `/css/*` para que Cloudflare siempre revalide con el origen.
- **#54** — Logo visible en el sidebar oscuro del dashboard, tamaño correcto en todos los nav, widget "Plan Pro" del sidebar con contraste corregido.
- **#55** — Datos reales de contacto en las páginas legales (ciudad, correo `legal@usemaestria.co`, razón social/NIT con comentarios HTML de lo que sigue pendiente).

**Esta sesión, primera mitad** (PRs #56–#67) — cierre de cabos sueltos + endurecimiento de seguridad:
- **#57, #58** — Botones de planes de `index.html` conectados a Wompi de verdad (antes iban a WhatsApp); precio en COP corregido en `cuenta.html`.
- **#59–#65** — Re-extracción **verbatim** de los 7 catálogos DBA (Lenguaje 88, Matemáticas, Ciencias Naturales, Ciencias Sociales, Inglés, Transición) directo de los PDF oficiales MEN — el contenido original venía truncado/con viñetas mal separadas de una fuente intermedia sin verificar contra el documento oficial. `seed_dbas.py` se volvió upsert-aware: un redeploy corrige la DB de producción sin migración manual.
- **#66** — **Seguridad avanzada** (sprint grande, 9 frentes): security headers (CSP/X-Frame-Options/etc., auditado contra los recursos externos reales que carga el sitio), JWT de vida corta (60 min) + refresh token de 30 días con tabla `token_blacklist` y `POST /api/auth/logout`/`refresh`, rate limiting (slowapi) en login/registro/forgot-password/refresh, sanitización (bleach) + guarda anti-prompt-injection en el chat, CORS restrictivo a `usemaestria.co` en producción, política de contraseñas, `audit_log` de acciones sensibles (Ley 1581), `pip-audit` obligatorio en CI.
- **#67** — Auto-refresh de JWT en el frontend (cierra el pendiente explícito del #66): `api.js` intercepta cualquier 401, pide un access token nuevo con el refresh token y reintenta la llamada original una vez; `auth.js` además refresca proactivamente cada minuto. Sin esto, el access token de 60 min iba a forzar relogin constante.

**Esta sesión, Presentaciones Interactivas** (PRs #68–#86) — construida, endurecida en producción, y ahora **congelada** para el lanzamiento de la beta gratuita:
- **#68** — Sprint original: generación de diapositivas con IA (contenido + preguntas tipo Kahoot: opción múltiple/verdadero-falso/encuesta/nube de palabras), sesión en vivo por Socket.io con código de 6 caracteres, estudiantes se unen sin cuenta desde `join.html`.
- **#69** — Flag `es_admin`: bypass de trial/rate-limit para el fundador, sin efectos secundarios sobre el plan de otros docentes.
- **#70** — Eliminar grupo con cascada real: bug encontrado y corregido (`Grupo` no cascadeaba `chat_sesiones`/`piar`/`observaciones`/`presentaciones`/`seguimiento_dbas` — un `DELETE` con cualquiera de esos hijos habría fallado con `IntegrityError` en Postgres).
- **#71–#77** — Serie de diagnósticos y fixes de 502/caching en producción (Railway + Cloudflare): bump de caché del service worker, ajustes de CSP (Google Fonts, Cloudflare Insights) sin romper Socket.io, y finalmente un service worker mínimo sin `fetch` handler propio — el patrón cache-first anterior servía HTML/CSS viejo tras cada deploy.
- **#78 (Sprint 1)** — Bugs reales reportados en clase: el `cuerpo` de una diapositiva a veces llegaba como array y se mostraba literalmente `['a', 'b']` en pantalla; el estudiante quedaba colgado en "Uniendo…" sin nunca recibir confirmación ni error.
- **#79 (Sprint 2)** — Cache-Control en HTML, cantidad de diapositivas/preguntas configurable por el docente, tipo `verdadero_falso`, catálogo cerrado de 6 diagramas SVG generados por descriptor (nunca markup crudo de la IA).
- **#80 (Sprint 3)** — `join.html` reescrito autosuficiente: sin Tailwind/Font Awesome/CDN externos, CSS y SVG inline — la página que abre un estudiante en un celular ajeno con datos móviles malos no puede depender de que un CDN cargue.
- **#81** — Generación asíncrona: `POST /generar` respondía 502 de Cloudflare en generaciones grandes porque esperaba a Claude dentro del request HTTP; ahora responde 202 de inmediato y la IA corre en background.
- **#82** — Generación en dos fases (esqueleto del índice + relleno de cada diapositiva en paralelo, máx. 5 concurrentes) para acotar el tamaño de cada llamada a la IA.
- **#83** — Puntaje configurable (modo competencia con bonus por velocidad, o modo inclusivo sólo por acierto) con ajuste de tiempo extendido para estudiantes con PIAR registrado en el grupo; podio en vivo; paleta de diagramas corregida para contraste real sobre proyector (WCAG AA).
- **#84** — Multi-tema por secciones (hasta 5 temas en una sola presentación), límites de duración estimada con semáforo verde/ámbar/rojo, tabla de posiciones en vivo durante la sesión.
- **#85** — **Bug crítico** reportado en clase: un estudiante que cambiaba de app o bloqueaba el celular quedaba con la pantalla congelada al volver — el socket reconectaba pero nunca se re-unía a la sala. Corregido con reconexión automática + identidad estable de participante. Además: validación estructural (Pydantic) de cada diapositiva generada antes de guardarla, y modo pantalla completa para proyectar.
- **#86** — **Feature flag `FEATURE_PRESENTACIONES`** (default `False`, env var): Presentaciones Interactivas se **congela**, no se borra, para el lanzamiento de la beta gratuita. Ver el detalle completo más abajo. Este PR se quedó abierto varios días esperando revisión manual mientras el resto de la sesión seguía con la auditoría pre-beta — se mergeó (rebaseado sobre los 4 commits que main ya llevaba encima) recién en el sprint de abajo.

**Esta sesión, auditoría pre-beta y endurecimiento de producción** (PRs #87–#93) — con la beta gratuita ya encima, se auditó el estado real (no asumido) de seguridad/estabilidad/infra, y cada hallazgo P0 se cerró con su propio PR verificado en producción, dos veces con dos minutos de diferencia, antes de darlo por bueno:

- **`AUDITORIA-BETA.md`** — auditoría de 10 áreas (auth, grupos, planeación IA, notas, dashboard, base de datos, seguridad, errores visibles, estados vacíos, infraestructura) hecha **sin tocar código** (regla explícita del sprint) para no confundir "el código está bien" con "funciona en producción" — precedente ya vivido en este proyecto (CSS que no cargaba en el celular, deploy que nunca corrió). Encontró 2 P0 de seguridad reales (cadena XSS vía import CSV + render de IA sin sanitizar; Host header sin validar en links de verificación/reset) y 1 P0 de estabilidad (streaming del chat sin timeout — mismo patrón que ya había causado un 502 en Presentaciones).
- **#87** — Cierra la cadena de XSS: `DOMPurify` (vendored local, no CDN) sanitiza el render de IA en el chat con allowlist estricta; el import CSV de estudiantes ahora valida cada fila vía el mismo schema Pydantic que la creación individual (bleach + límites de longitud) en vez de construir el ORM directo desde celdas crudas, y rechaza inyección de fórmulas de hoja de cálculo y caracteres de control; `TrustedHostMiddleware` + `settings.BASE_URL` reemplazan `request.base_url` (que Starlette arma desde el header Host sin validar) para construir los links de verificación/reset. Incluye además `GET /api/version` (commit + hora de arranque, público) pedido en el mismo PR para poder confirmar en una petición si un commit está vivo en producción.
- **#88, #89 — dos hotfixes P0 el mismo día del merge de #87**: el sitio quedó caído con 502 en todas las rutas dos veces seguidas. Primero, la allowlist nueva de `TrustedHostMiddleware` rechazaba el healthcheck de Railway (se abrió a `allowed_hosts=["*"]` para restaurar el servicio — **sigue así, es un P0 de seguimiento sin cerrar**, ver Pendiente Técnico). Segundo — causa distinta, mismo síntoma —, una migración de Presentaciones (`slide_abierto_en DATETIME`, sintaxis SQLite/MySQL inválida en Postgres) tumbaba el arranque completo desde una función que ni siquiera estaba activa todavía (el flag `#86` seguía sin mergear). Revisado todo `migrate.py`: era el único tipo inválido en Postgres del archivo.
- **#90** — **Aísla cada migración individual** (`errores.py`-style: `_paso()` loguea y registra en `MIGRATION_ERRORS` en vez de tumbar el arranque; una migración rota nunca vuelve a tumbar el sitio entero) y las expone en `GET /health`/`GET /api/version` (siempre 200, nunca deja de pasar el healthcheck) más un banner rojo en el dashboard sólo para `es_admin=true`. Agrega un servicio Postgres real al CI (`tests/test_migraciones_postgres.py`) — exactamente el chequeo que habría atrapado el bug de #89 antes del merge, porque el resto de la suite corre en SQLite, que acepta cualquier nombre de tipo sin quejarse.
- **#91** — Cierra el pendiente real detrás de `Auth.startAutoRefresh()` (que el #67 de la sesión anterior daba por resuelto pero no lo estaba del todo): `requireAuth()`/`isAuthenticated()` desloguéaban de inmediato con sólo mirar el `exp` del access token, sin intentar refrescar — ahora refrescan en background sin bloquear la carga de la página. `api.js` distingue un fallo de red durante el refresh (no cierra sesión) de un refresh token inválido/revocado (sí la cierra). `Auth.logout()`/`POST /api/auth/logout` ahora blacklistean access **y** refresh token — antes "el refresh token asociado seguía vivo" tras un logout. Las 3 páginas con botón real de logout (que tenían cada una su propia implementación ad-hoc) ahora delegan en `Auth.logout()`. Además, `llm.stream_respuesta` gana `timeout_s` (mismo patrón que `respuesta_completa` desde el #81) — cierra el P0 de estabilidad del chat. Primera vez que este repo corre tests de JS de verdad (`node --test`, cero dependencias npm nuevas) para probar la orquestación async de refresh/reintento, que ninguna verificación estática podía probar honestamente.
- **#92** — `fastapi` 0.111.0→0.141.1, `starlette` pinneada en 1.6.0: cierra las 7 vulnerabilidades de Starlette que el CI traía triadas y aplazadas desde el sprint de seguridad avanzada (#66). Starlette ≥1.0 eliminó `@app.on_event`/`@app.middleware` — migrado a `lifespan`/`add_middleware(BaseHTTPMiddleware, ...)` sin cambiar la lógica de arranque ni el orden de middlewares. Verificación estricta de los 10 puntos críticos (arranque, migraciones contra Postgres real, auth completo, CSP, CORS, rate limiting, TrustedHostMiddleware, `/api/version`/`/api/features`/`/health`, flag de presentaciones) antes de mergear.
- **#93** — **Errores comprensibles + correlation ID** (Parte C del sprint primer-uso, ver Pendiente Técnico para las partes que faltan): manejador global de excepciones no capturadas (nunca deja pasar stack traces/SQL/tokens a la pantalla, siempre da un `correlation_id` de 8 caracteres) + los 9 sitios reales que sí filtraban detalle técnico (`documento.py`, `grupos.py`, `observaciones.py`, `piar.py`, `suscripciones.py`) corregidos con el mismo helper (`errores.error_manejable()`). Los dos `ia_error` del chat en vivo también llevan `correlation_id` — es la función más usada de la app, y es la base de la que depende "Reportar un problema" (todavía sin construir).

**Tests**: 627 pasando (0 fallos) contra SQLite + los 2 tests reales contra Postgres del #90 (sólo corren en CI, con el servicio disponible) + 14 tests de JS (`node --test`, sin dependencias npm) del #91 — suite completa corre en CI en cada PR contra `main`.

---

### Presentaciones Interactivas — estado exacto al congelarse

La función quedó **funcionalmente completa** tras 8 sprints (#68, #78–#85): generación de contenido y preguntas por IA (una o varias secciones temáticas), sesión en vivo tipo Kahoot con código de acceso, dos modos de puntaje con ajuste de tiempo para estudiantes con PIAR, podio y tabla de posiciones en vivo, reconexión automática de estudiantes ante pérdida de conexión, validación estructural de cada diapositiva generada, y modo pantalla completa para proyectar. 557 tests cubren todo eso, incluyendo los 4 bugs críticos reportados en clase real que motivaron los Sprints 1 y 8.

**Qué falta si se retoma** (nada de esto es código roto — es verificación manual que este entorno no puede hacer):
- Confirmar en un celular real que la reconexión automática (Parte A del Sprint 8) funciona al cambiar de app/bloquear pantalla — sólo se probó con handlers de Socket.io invocados directamente en tests, nunca contra un navegador móvil real.
- Confirmar el modo pantalla completa en Safari/iPad contra un proyector real — los prefijos `webkit` están puestos pero sin poder probarlos en hardware real.
- Una generación real con Claude en producción, de punta a punta, con el volumen de diapositivas que un docente pediría de verdad (todo el desarrollo usó mocks de la respuesta de la IA).
- Congelar la función significa que **nada de esto se pierde** — el código, los modelos, las tablas y las migraciones siguen intactos en `main`; sólo hace falta poner `FEATURE_PRESENTACIONES=true` en Railway para reactivarla tal como quedó.

**Cómo funciona el flag**:
- `FEATURE_PRESENTACIONES` (env var, default `False`) en `config.py`.
- Apagado: toda la API `/api/presentaciones/*` responde 404 (indistinguible de una ruta inexistente — es una dependency a nivel de router, cubre hasta el endpoint público `GET /join/{codigo}`). El dashboard y `grupo-panel.html` ocultan sus botones de entrada a la función (consultan el nuevo endpoint público `GET /api/features`). `join.html` se sigue sirviendo por URL directa pero muestra "Función no disponible" en vez del formulario de unirse.
- Prendido: todo vuelve a funcionar exactamente como quedó en el PR #85, sin ningún cambio de comportamiento.

---

## EN PROGRESO

**Ninguno.** No hay PRs abiertos ni corriendo CI en este momento — todo lo mergeado hasta el #93 está en `main` y verificado en producción.

**Sprint primer-uso** (onboarding, estados vacíos, errores comprensibles, reportar un problema) va por su Parte C (#93, arriba). Faltan Partes A, B y D — ver Pendiente Técnico #1.

---

## PENDIENTE TÉCNICO

En orden de prioridad:

1. **Sprint primer-uso — Partes A, B y D (Parte C ya en `main`, #93).** Onboarding mínimo (dos caminos "Crear mi primer grupo"/"Explorar un grupo de ejemplo", guía progresiva saltable, sin mencionar Presentaciones porque está archivada); estados vacíos con explicación + acción en vez de "No hay datos" (inventario de pantallas todavía sin hacer); botón "Reportar un problema" accesible desde cualquier pantalla, que capture el `correlation_id` del último error (Parte C ya deja esa pieza lista) — mismo ID en el reporte y en el log, o un reporte de "no me funcionó" no sirve para investigar nada.
2. **`TrustedHostMiddleware` sigue abierto a `allowed_hosts=["*"]`** — P0 de seguimiento del #88, sin cerrar. Restaura el sitio (era la prioridad ese día) pero no cierra el hallazgo original de Host header sin validar. Falta confirmar en los logs de Railway (o Railway → Settings → Healthcheck) qué Host manda de verdad el healthcheck, para volver a la allowlist real (`_ALLOWED_HOSTS_OBJETIVO`, ya escrita en `main.py`, sólo falta el host correcto).
3. **`chat.html` referencia `css/chat.css`, que no existe en el repo** (`main.css`/`brand.css` sí cargan bien) — encontrado durante la verificación post-deploy del #93, no investigado todavía cuánto se nota visualmente ni desde cuándo está así.
4. **Wompi: pasar de sandbox a producción.** El código está completo desde el #51, pero corre contra el ambiente sandbox de Wompi. Falta: activar las claves reales de producción en Railway, hacer una transacción real de prueba, y confirmar que el webhook llega y se procesa correctamente en producción.
5. **Retirar o archivar el código de Stripe** (#39) una vez Wompi esté confirmado en producción — hoy coexisten dos pasarelas de pago, sólo una se va a usar (ver Deuda técnica).
6. **Extender la verificación visual real al resto del frontend.** Sigue sin auditarse con screenshots reales: `grupo-panel.html`, `cuenta.html`, `panel-docente.html`, `chat.html`, y los breakpoints móviles reales (verificados sólo por lectura de CSS). Este entorno no tiene herramienta de automatización de navegador — tampoco se pudo confirmar el flujo completo de chat en vivo (login → enviar mensaje → respuesta en streaming) contra producción después del #93 por el mismo motivo, más el costo real de una llamada a la IA.
7. **Presentaciones Interactivas — verificación manual real antes de reactivar el flag.** Ver el detalle completo en la sección de arriba (reconexión en un celular real, pantalla completa en Safari/proyector, generación con Claude real en producción).
8. **Mascota Chispa** — sin ningún asset ni integración en la UI todavía.
9. **Exportación a PDF desde el chat** — hoy sólo DOCX vía PIAR/documento.py.
10. **Programa de referidos** — no implementado.
11. **Dashboard de analítica por estudiante** — no implementado.
12. **Benchmark de modelos IA** (Claude/GPT/Gemini, objetivo de la tesis doctoral) — diseño de perfiles de evaluación existe fuera del repo, pendiente de API keys de OpenAI y Google.
13. **API pública para integraciones** e **integración con SIMAT** — Prioridad de escala, sin empezar.

---

## PENDIENTE NO-TÉCNICO

Bloqueado por decisiones externas, no por código:

- **Constitución de la SAS** — la razón social legal sigue sin definir; las páginas legales muestran "Maestr.ia" como nombre comercial neutro con un comentario HTML `<!-- PENDIENTE: razón social SAS -->` (#55) en vez de inventar un nombre.
- **NIT** — pendiente de asignación (depende de la constitución de la SAS). Se muestra en pantalla como "(en trámite)", con comentario HTML de seguimiento.
- **Revisión legal profesional** de la Política de Tratamiento de Datos y los Términos de Uso — son borradores técnicos redactados sin abogado, nunca revisados formalmente. La "fecha de entrada en vigencia" de ambos documentos sigue en blanco hasta que eso pase.
- **Registro ante la SIC** (Superintendencia de Industria y Comercio) — obligatorio porque la plataforma trata datos sensibles de menores con discapacidad (diagnósticos, vía PIAR).
- **Cuenta Wompi de producción verificada** (KYC del comercio + cuenta bancaria asociada) — bloquea el punto 1 de Pendiente Técnico.
- **Facturación electrónica DIAN** — necesaria en cuanto haya cobros reales, no configurada todavía.
- **Licencia de industria y comercio municipal** — pendiente de confirmar.
- **Lanzamiento de la beta gratuita** — objetivo inmediato de toda esta sesión (Presentaciones ya congelada desde el #86; la auditoría pre-beta #87–#93 fue el endurecimiento previo al lanzamiento). El flujo trial→pago (#50 + #51) sigue construido de punta a punta pero nunca se probó con un usuario real pagando con dinero real — la beta gratuita no depende de eso todavía.
- **Buzón `legal@usemaestria.co`** — el dominio ya tiene Cloudflare Email Routing activo (usado hoy por `hola@usemaestria.co`); falta solamente agregar la regla de forwarding para `legal@` en el dashboard de Cloudflare — pendiente de que el usuario lo haga, no depende de código.

---

## DEUDA TÉCNICA

Cosas que funcionan pero están incompletas o frágiles:

- **Dos pasarelas de pago en el código a la vez**: Stripe (#39, nunca operó como procesador local en Colombia) y Wompi (#51, en sandbox). Ambas activan internamente el mismo `Suscripcion.plan="pro"` y ambos webhooks desbloquean el trial — es lógica duplicada que hay que consolidar en cuanto Wompi esté confirmado en producción.
- **CI de GitHub Actions con fallas de entrega intermitentes**: al menos 2 veces en la sesión anterior (PR #49, PR #50) los workflows tardaron en dispararse o nunca lo hicieron por un problema de infraestructura de GitHub, no del código. El #93 (11 días después del deploy anterior, #92) sí disparó y desplegó sin problema, pero quedó anotado como riesgo a vigilar explícitamente cuando un pipeline lleva mucho tiempo sin ejercitarse.
- **`TrustedHostMiddleware` abierto a `allowed_hosts=["*"]`** desde el hotfix del #88 — ver Pendiente Técnico #2, es el P0 de seguridad más viejo sin cerrar de los que trajo la auditoría pre-beta.
- **`grupo-panel.html` sigue sin sección de Observaciones ni de PIAR** (deuda heredada del #41) — esas dos features viven en `grupos.html` en su lugar, por una inconsistencia entre lo que pedía el spec original y dónde vive realmente la ficha del estudiante.
- **Rate limiting atado a fecha calendario, no al período académico** (`Grupo.periodo_actual`) — el reset es manual vía endpoint admin (#37), sin cron automático.
- **Sin medición de cobertura de línea** (`coverage.py`) — 627 tests dan buena señal cualitativa de negocio, pero no hay un % de cobertura de código reportado.
- **Envío de correo por Resend** (#44, con fallback SendGrid→SMTP→LogOnly) — nunca confirmado el envío real end-to-end en producción con una bandeja real, sólo a nivel de código y tests mockeados.
- **Presentaciones Interactivas congelada sin haber corrido nunca con el flag prendido en producción real** — todo el desarrollo y los tests corrieron con mocks de la IA y del socket; la primera vez que el flag se prenda en Railway de verdad es, en sí misma, la prueba de humo pendiente (ver Pendiente Técnico #7).
- **Streaming del chat en vivo nunca verificado de punta a punta contra producción** — el #91 le agregó timeout y el #93 le agregó `correlation_id` a sus errores, ambos verificados con tests que simulan al proveedor de IA; nadie ha confirmado en el navegador, contra Railway real, que login → enviar mensaje → respuesta en streaming efectivamente funciona (este entorno no tiene navegador ni credenciales reales, y no dispara una llamada real a la IA por su cuenta sin permiso explícito — tiene costo real).

---
*Generado por Claude Code el 2026-09-28 — repositorio github.com/Guacen/asistente-pedagogico-ia.*
