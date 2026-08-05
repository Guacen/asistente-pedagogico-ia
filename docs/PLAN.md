# Plan de trabajo — Maestr.ia

## Estado del producto (2026-08-05)

### Lo que ya funciona

- **Autenticación completa**: registro, login (JWT), verificación de correo por token (24h de validez, tabla `email_verifications`), reenvío de verificación, cambio de contraseña (estando logueado), recuperación de contraseña vía email (token de 1h, un solo uso, tabla `password_reset_tokens` — PR #34), eliminar cuenta.
- **Consentimiento Ley 1581**: campos `consentimiento_datos`, `fecha_consentimiento`, `ip_consentimiento` en `Docente`; endpoint `POST /api/auth/aceptar-consentimiento`; usuarios pre-existentes quedan "grandfathered" (`NULL`) para que el frontend les muestre el banner.
- **Chat multi-modo**: `planeacion`, `socioemocional`, `calificacion`, `piar`, cada uno con su prompt especializado, rate limit diario configurable por modo (10/20/20/5) y bypass para docentes marcados como admin.
- **Sesiones temáticas de chat**: cada conversación es una sesión con título automático (generado por el LLM tras el primer intercambio), archivable, aislada por (grupo, modo, estudiante).
- **Generador de PIAR (Decreto 1421 de 2017)**: conversación guiada → síntesis a JSON estructurado vía LLM → documento DOCX con marca. Formato fijo de 10 secciones (template estático + contenido del LLM), versionado paralelo (v1, v2… sin borrar anteriores), estados borrador/aprobado.
- **Módulo de Observaciones y Seguimiento Estudiantil (Ley 1620 de 2013, Decreto 1965 de 2013, Ley 1098 de 2006 Art. 44)** — PR #41. Nuevo modo de chat "observaciones" + endpoint REST de un solo turno: el docente narra la situación, la IA redacta la observación formal para el Observador del Alumno, la clasifica según la Ruta de Atención Integral (Tipo I/II/III) y recomienda nivel de escalación (docente/coordinador/orientador/externo/icbf). Alerta explícita citando el Art. 44 de la Ley 1098 en situaciones Tipo III. Seguimiento con estado (abierta/en_seguimiento/cerrada) y fecha de seguimiento, badge de alertas en el dashboard, exportación a DOCX reusando el pipeline Markdown→DOCX existente. **Sin límite de rate limiting en ningún plan** (ni el contador diario ni el tope mensual del plan free) — decisión de producto: las observaciones son urgentes y no deben quedar detrás de un paywall. **Diferenciador**: no se conoce otro asistente pedagógico colombiano con esta cobertura legal específica (Ley 1620/1098) integrada al flujo de chat.
- **Marco legal del PIAR ya implementado en los prompts** (no solo planeado): citan Ley 1618, Convención ONU (Ley 1346), definen BAP como del contexto (no del estudiante), los 3 principios DUA, diferencian ajuste razonable de apoyo y flexibilización, usan lenguaje de capacidades (prohíben términos clínicos), y recuerdan la firma de rector/acudiente para validez legal. Verificado por 17 tests dedicados en `test_piar_legal_compliance.py`.
- **Multi-institución con roles**: `docente` / `coordinador` / `rector`, dashboard institucional agregado (grupos y PIARs consolidados por institución), invitar/remover docentes, cambiar rol.
- **Gestión de grupos y estudiantes**: CRUD completo, import CSV de estudiantes, libro de calificaciones con columnas ponderadas por período, boletines en DOCX.
- **Proveedor de IA con fallback**: Claude (Anthropic) como proveedor primario, Gemini (Google) como alternativa automática si no hay `CLAUDE_API_KEY` válida configurada — abstracción única en `llm.py`, sin lógica duplicada en `ia.py`/`piar.py`.
- **Pasarela de pago — código Stripe Colombia listo, pero NO activado** (PR #39): checkout con dos planes en COP ("Docente" $25.000/mes, "Pro" $45.000/mes vía `STRIPE_PRICE_ID_DOCENTE_COP`/`STRIPE_PRICE_ID_PRO_COP`), PSE y Nequi habilitados como métodos de pago junto a tarjeta, checkout en español (`locale='es'`), cancelación de suscripción, webhook. **Actualización posterior al PR**: Stripe no opera en Colombia como procesador local, así que este código no se activó en producción — ver "Estado del negocio" y la fila de Wompi en el backlog. Interim: upgrades a Pro manuales por WhatsApp.
- **Versión corta para el Observador físico** (commit directo a `main`, 2026-08-04): el prompt del modo "observaciones" ahora siempre cierra con una versión condensada (máx. 50 palabras / 3 líneas) lista para copiar al Observador del Alumno en papel — fecha, hecho principal, acción tomada, próximo paso.
- **Identidad de marca Maestr.ia** aplicada a los 11 HTML del frontend, logo y paleta de colores (`css/brand.css`), exportación DOCX rebrandeada (planes, rúbricas, boletines, PIAR).
- **CI**: GitHub Actions corre la suite completa de pytest en cada push/PR contra `main`.
- **Endpoint admin de mantenimiento** (`backend/admin.py`, PR #37): `POST /api/admin/reset-limites-periodo` purga `rate_limit_counter`, protegido por `Docente.es_admin`. Pensado para llamarse a mano o desde un cron externo (no incluye scheduler propio — ver nota en el backlog).
- **PWA instalable** (PR #42): `manifest.json` + `service-worker.js` (cache-first, `/api/*` y `/socket.io/*` siempre a red), meta tags PWA en los 14 HTML, service worker registrado en index/dashboard/chat. Descarga de DOCX arreglada en iOS Safari (que no dispara `<a download>`) en los dos lugares donde existía esa lógica (`api.js._descargarBlob` y `descargarDocx()` de chat.html) — abre el blob ya autenticado en pestaña nueva en vez de la URL cruda de la API (que perdería el header `Authorization`).
- **Responsive móvil completo en las 8 páginas principales** (PR #36 + #42): dashboard, chat, login, precios, grupos, grupo-panel y panel-docente. `precios.html` reescrito con 4 planes en COP y paleta de marca (ya no depende de la Prioridad 1 "Landing page" para eso).

### Tests

- **290 tests**, distribuidos en 30 archivos bajo `backend/tests/`.
- **290 passed, 0 failed** en la corrida completa (~72s) al momento de este análisis (273 base + 17 de `test_observaciones_crud.py`, PR #41).
- Cobertura por área: auth (incluye recuperación de contraseña), aislamiento entre docentes (multi-tenant), chat multi-modo (unitario + integración), sesiones, PIAR (generación, formato, validación JSON, cumplimiento legal, ficha de estudiante), calificaciones/boletines, DOCX (template + markdown parser), multi-institución, panel docente, import CSV, verificación de email + consentimiento, reset de rate limits admin, pagos/Stripe (checkout, webhook, cancelación — mockeado, sin red real).
- No hay medición de cobertura de línea (`coverage.py`) configurada — el número de tests es alto y cubre casos de negocio, pero no hay un % de cobertura de código reportado.

### Deuda técnica conocida

- **Responsive móvil sin verificación visual real** (PR #36 + #42): el trabajo de responsive (dashboard, chat, login, precios, grupos, grupo-panel, panel-docente) se hizo por lectura de código (breakpoints Tailwind vs. anchos en px, `grep` para confirmar ausencia de sidebar donde el spec asumía que había una), **no hay herramienta de browser/screenshot en este entorno para confirmarlo visualmente en ningún sprint de esta sesión**. Pendiente que alguien lo abra en un dispositivo/DevTools real antes de darlo por cerrado del todo. Lo mismo aplica a la instalación de la PWA (PR #42) — nunca se probó "Agregar a pantalla de inicio" en un dispositivo real.
- **Sin mascota Chispa** en ningún HTML/CSS del frontend.
- **Sin exportación a PDF** desde el chat (solo DOCX vía PIAR/documento.py).
- **Sin programa de referidos** ni código de benchmark de modelos IA (Claude/GPT/Gemini) — ninguno tiene rastro en el código todavía, aunque el diseño experimental ya existe (ver "Contexto académico").
- **`README.md` y `RESUMEN.md` (antes de este commit) describían un deploy a Hostinger vía FTP con Stripe genérico** — completamente desactualizado frente a la arquitectura real (Railway + FastAPI sirviendo el frontend estático embebido en `backend/frontend/`, sin Hostinger, sin FTP).
- **`docs/legal/` ya tiene 3 borradores** (política de tratamiento de datos, términos de uso, texto de consentimiento) con advertencia explícita de que son borradores técnicos, no redactados por abogado — pendiente de revisión legal antes de publicarse.
- **`grupo-panel.html` no es la ficha del estudiante** (PR #41): el sprint de Observaciones pedía agregar la sección ahí, pero el código real de "ficha del estudiante con PIAR" (Issue #48) vive en el modal `#modal-estudiante` de `grupos.html` — `grupo-panel.html` es otra vista (tabla/roster del grupo). La sección de Observaciones se agregó en `grupos.html` para quedar consistente con dónde vive PIAR realmente. `grupo-panel.html` sigue sin sección de Observaciones ni de PIAR.
- **Panel "Observaciones" del chat sin verificación visual** (PR #41): mismo caso que el responsive — construido por lectura de código, sin browser disponible en este entorno para confirmar que el flujo (generar → ver resultado → descargar DOCX) funciona end-to-end en un navegador real.

---

## Sprints completados

(De `git log --oneline`, orden cronológico ascendente)

1. **Infra de deploy en Railway** — pin de Python 3.11 (SQLAlchemy incompatible con 3.13), Procfile y requirements.txt en raíz para forzar buildpack Python, SQLAlchemy 2.0.41 + psycopg2 2.9.10 compatibles.
2. **Chat multi-modo (#9, #10)** — migración `Mensaje.modo`, socket handler que persiste y aísla historial por modo, selector de modo + banner de rate limit en frontend, contexto especializado por modo (socioemocional/calificación), rate limiting diario configurable (10/20/20).
3. **Generador de PIAR (#11)** — modelo `PIAR` + `Mensaje.id_estudiante`, prompt legal real (Decreto 1421), endpoints REST + DOCX on-demand con marca BORRADOR/APROBADO, UI (chip, sub-dropdown de estudiante, botón Generar, banner).
4. **Multi-institución (#12)** — instituciones + roles (docente/coordinador/rector) + agregados institucionales.
5. **PIAR desde ficha de estudiante (#13)** — Issue #48.
6. **Fixes de despliegue y UX (#14–#21)** — Procfile/requirements en raíz, pin Python 3.11, crear grupo+estudiantes en una operación atómica, eliminar loops de redirección en auth, limpiar token en 401, flush de input a medio llenar en wizard de grupo.
7. **Soporte multi-proveedor de IA (#22–#24)** — alias `ANTHROPIC_API_KEY`/`CLAUDE_API_KEY`, soporte Gemini como alternativa, migración al SDK `google-genai` con `gemini-2.0-flash`.
8. **Sesiones temáticas de chat (#25)** — reemplaza el hilo infinito por modo con conversaciones separadas, título automático, flag admin sin rate limit.
9. **Identidad de marca Maestr.ia (#27–#29)** — pipeline Markdown → DOCX con template Maestr.ia + backfill legacy, logo y assets, rebrand de blockquotes/headings/DOCX legado a la paleta de marca.
10. **Fix de bugs de documento.py** — 5 bugs (logo, separadores, headings, tabla, título duplicado).
11. **PIAR marco legal completo + 10 secciones con DUA (#30)** — expansión del prompt a la estructura legal completa verificada por tests.
12. **PIAR formato fijo e inamovible (#31)** — template estático + JSON del LLM, no editable en estructura.
13. **Verificación de correo + consentimiento Ley 1581** (PR #32, mergeado 2026-08-03).
14. **Cache-busting de assets estáticos** (commit directo a `main`, 2026-08-03) — `?v=` en todos los `<script>`/`<link>` locales.
15. **Recuperación de contraseña** (PR #34, 2026-08-03) — mismo patrón que verificación de email: `PasswordResetToken` (1h TTL, un solo uso), `forgot-password` / `reset-password`, `recuperar-password.html` + `nueva-password.html`.
16. **Confirmación de estado del backlog** (PR #35, 2026-08-03) — PIAR template JSON y Decreto 1421 ya estaban done desde PRs anteriores, corregido en este documento.
17. **Responsive móvil — dashboard y chat** (PR #36, 2026-08-03) — sidebar de dashboard.html a drawer con backdrop en <768px, panel de sesiones de chat.html colapsado por defecto en mobile, fix de un overflow introducido por el PR #34 en login.html.
18. **Reset de límites por período académico** (PR #37, 2026-08-03) — `POST /api/admin/reset-limites-periodo`, protegido por `Docente.es_admin`, purga `rate_limit_counter`.
19. **Stripe configurado para Colombia — código listo, sin activar** (PR #39, 2026-08-03) — PSE + Nequi + tarjeta, dos precios COP (Docente/Pro) vía `STRIPE_PRICE_ID_DOCENTE_COP`/`STRIPE_PRICE_ID_PRO_COP`, `locale='es'`, límites de plan movidos a `config.LIMITES_PLAN`, WARNING de startup si `STRIPE_SECRET_KEY` está vacío, 7 tests nuevos (módulo antes sin cobertura). Actualización 2026-08-04: Stripe no opera en Colombia como procesador local — este código quedó sin activar; Wompi es ahora la decisión estratégica pendiente (ver backlog).
20. **Landing page de marketing** (PR #40, 2026-08-04) — `index.html` reescrito desde cero: navbar sticky + menú móvil, hero, dolor→solución, cómo funciona, marco legal, 4 planes en COP con WhatsApp, para colegios, FAQ, footer. CSS puro, sin frameworks.
21. **Módulo de Observaciones y Seguimiento Estudiantil** (PR #41, 2026-08-04) — modelo `Observacion`, modo de chat "observaciones" (sin límite de rate limiting), endpoints REST (`crear`, `listar`, `detalle`, `actualizar estado`, `seguimientos-pendientes`, `exportar DOCX`), sección en la ficha del estudiante (en `grupos.html`, no en `grupo-panel.html` — ver nota de deuda técnica), tab en `chat.html`, alerta en `dashboard.html`. 17 tests nuevos.
22. **Versión corta para Observador físico** (commit directo a `main`, 2026-08-04) — el prompt de "observaciones" agrega siempre una versión condensada de máx. 3 líneas / 50 palabras al final de cada registro.
23. **PWA + responsive completo** (PR #42, 2026-08-05) — `manifest.json` + `service-worker.js`, meta tags PWA en los 14 HTML, fix de descarga DOCX en iOS Safari (2 lugares). Responsive: `precios.html` reescrito (COP + marca + WhatsApp, mismo enfoque que el PR #40), `grupos.html` con header/tabs corregidos. Corrección sobre el spec: `precios.html`, `grupos.html`, `grupo-panel.html` y `panel-docente.html` no tenían sidebar `w-64` como se asumía — `grupo-panel.html` y `panel-docente.html` ya eran responsive, sin cambios.

Nota sobre la numeración: #32 a #41 incluye 3 PRs solo-docs (#33, #35, #38 — actualizaciones de este mismo archivo, sin cambios de código) y 2 commits directos a `main` sin número de PR (cache-busting de assets, sprint #14; versión corta del Observador, sprint #22) — ambos autorizados explícitamente así por el usuario, sin pasar por PR.

---

## Backlog priorizado

### Prioridad 1 — Obligatorio antes de cobrar

| Tarea | Descripción | Complejidad | Estado |
|-------|-------------|-------------|--------|
| Verificación de correo | Token de verificación por email, 24h de validez, bloqueo de `/me` hasta verificar | Media | ✅ done — 2026-08-03, PR #32 |
| Consentimiento Ley 1581 con banner | Campo + endpoint de aceptación, banner pendiente de confirmar en frontend para usuarios grandfathered | Baja | 🟡 Backend listo (PR #32), falta confirmar visualmente el wiring del banner en frontend |
| Recuperación de contraseña | Flujo "olvidé mi contraseña" vía email (token + reset) | Media | ✅ done — 2026-08-03, PR #34 |
| PIAR formato fijo con template JSON | Estructura de secciones inamovible, JSON del LLM sobre template estático | Alta | ✅ done — ya implementado en PR #31 (verificado de nuevo el 2026-08-03, sin cambios de código). `backend/templates/piar_template.md` existe con 10 secciones top-level (una de ellas, "Ajustes razonables y estrategias DUA", se subdivide en 3 sub-secciones DUA — 13 bloques de contenido en total, no 14). El test pedido ("3 PIARs distintos deben tener siempre las mismas secciones") ya existe: `test_3_piars_distintos_producen_las_mismas_10_secciones_en_el_mismo_orden` en `test_piar_format_consistency.py`. |
| Prompts con Decreto 1421 completo | Marco legal completo en el prompt del modo PIAR | Alta | ✅ done — ya implementado, verificado de nuevo el 2026-08-03 sin cambios de código (17 tests de cumplimiento legal en `test_piar_legal_compliance.py`) |
| Pasarela de pago Stripe (código) | Checkout COP con PSE + Nequi + tarjeta vía Stripe | Media-Alta | ✅ código done — 2026-08-03, PR #39. Checkout con dos precios COP (Docente/Pro), `locale='es'`, `payment_method_types=['card','pse','nequi']`. Límites de plan movidos de `suscripciones.py` a `config.LIMITES_PLAN`. 7 tests nuevos en `test_suscripciones.py` (antes tenía cero). **🚫 No activado en producción** — Stripe no opera en Colombia como procesador local (ver "Estado del negocio"). |
| Pasarela de pago Wompi | Cobro en COP vía procesador local (PSE + Nequi + tarjetas) | Media-Alta | ⏳ **Pendiente — decisión estratégica**, 2026-08-04. Stripe no opera en Colombia como procesador local. Decisión interim: upgrades manuales por WhatsApp hasta tener 20–30 usuarios pagando. Retomar cuando haya tracción real. Requiere: cuenta Wompi verificada + reescritura completa de `suscripciones.py` (Wompi no tiene SDK Python oficial, es API REST directa). |
| Landing page de marketing | `index.html` con hero, features, pricing, testimonios | Media | ✅ done — 2026-08-04, PR #40 (mergeado, rama `feature/landing-page` ya no existe). Sin frameworks externos, CSS puro con variables de marca. Pendiente menor: WhatsApp con número placeholder (+57 300 000 0000) por reemplazar, y el commit separado de `main.py` (redirect a dashboard si hay JWT válido) que nunca se hizo a propósito. Sin verificación visual (sin herramienta de browser en este entorno). |
| Responsive móvil | Adaptación real a pantallas chicas | Media | ✅ done — 2026-08-05, PR #36 + #42. Las 8 páginas principales cubiertas (dashboard, chat, login, precios, grupos, grupo-panel, panel-docente). Sin verificación visual real en ningún sprint (sin herramienta de browser en este entorno) — pendiente confirmar en dispositivo/DevTools real. |
| Reset de límites por período académico | Atar rate limit/uso a `periodo_actual` del grupo, no solo a fecha/mes calendario | Media | ✅ done — 2026-08-03, PR #37. Endpoint admin (no cron automático — ver nota abajo) que purga `rate_limit_counter` completo. No toca `UsoMensual` ni `periodo_actual` de grupos directamente. |

### Prioridad 2 — Mejoras de producto

| Tarea | Descripción | Complejidad | Estado |
|-------|-------------|-------------|--------|
| Mascota Chispa en estados de la UI | Ilustraciones/animaciones de Chispa en loading, error, éxito | Media | ❌ No implementado — sin rastro en HTML/CSS |
| Benchmark de modelos IA (OpenAI, Gemini, Claude) | Comparación de calidad de respuesta entre proveedores | Alta | ❌ No implementado en código — diseño de perfiles de evaluación existe fuera del repo (ver contexto académico) |
| Dashboard de analítica por estudiante | Métricas de progreso individual | Alta | ❌ No implementado |
| Módulo institucional (coordinador/rector) | Roles + vista agregada para coordinador/rector | Alta | ✅ Backend implementado (`institucion.py`: roles, dashboard, grupos/PIAR consolidados) — **el template lo daba por pendiente; falta confirmar consumo desde el frontend** |
| Programa de referidos | Incentivo de invitación entre docentes | Media | ❌ No implementado |
| Exportación a PDF desde el chat | Exportar conversación o respuesta puntual a PDF | Baja-Media | ❌ No implementado (solo DOCX vía PIAR/documento.py) |

### Prioridad 3 — Escala

| Tarea | Descripción | Complejidad | Estado |
|-------|-------------|-------------|--------|
| Multi-institución con roles | Base ya construida en Prioridad 2; escalar a más instituciones simultáneas y planes diferenciados | Alta | 🟡 Base ✅, escala pendiente de validar con carga real |
| API pública para integraciones | Endpoints documentados para terceros (más allá de Swagger interno) | Alta | ❌ No implementado |
| App móvil (PWA o nativa) | Empaquetado móvil del frontend actual | Alta | ✅ PWA done — 2026-08-05, PR #42. `manifest.json` + `service-worker.js` instalable en Android/iOS ("Agregar a pantalla de inicio"). Sin verificación real de instalación en un dispositivo. App nativa sigue sin implementar (no se pidió). |
| Integraciones con sistemas escolares colombianos (SIMAT) | Sincronización de matrícula/estudiantes con SIMAT | Muy alta | ❌ No implementado |

---

## Requisitos legales pendientes

| Requisito | Ley/Decreto | Costo estimado | Estado |
|-----------|-------------|----------------|--------|
| Política de Tratamiento de Datos | Ley 1581/2012 + Decreto 1377/2013 | Revisión abogado ~$300.000–800.000 COP | 🟡 Borrador técnico en `docs/legal/politica_tratamiento_datos.md`, falta revisión legal |
| Términos y Condiciones | — | Incluido en revisión anterior | 🟡 Borrador técnico en `docs/legal/terminos_de_uso.md`, falta revisión legal |
| Registro SIC (datos sensibles menores) | Ley 1581/2012, art. 7 | Sin costo de registro, sí de asesoría | ❌ Pendiente — la plataforma trata diagnósticos clínicos y datos de menores con discapacidad (PIAR) |
| RUT/NIT | DIAN | Sin costo (trámite) | ❌ Pendiente de confirmar si ya existe entidad constituida |
| Constitución SAS | Código de Comercio | ~$500.000–1.500.000 COP (notaría/cámara de comercio) | ❌ Pendiente de confirmar |
| Facturación electrónica DIAN | Decreto 358/2020 | Software de facturación ~$50.000–150.000 COP/mes | ❌ Pendiente — necesario en cuanto haya cobros |
| Licencia industria y comercio | Municipal | Variable por municipio | ❌ Pendiente de confirmar |

---

## Arquitectura actual

```
Frontend (HTML/JS estático, backend/frontend/)
        │  servido directamente por FastAPI (StaticFiles)
        ▼
   FastAPI + Socket.io (backend/main.py)
        │
        ├──► PostgreSQL (prod, Railway) / SQLite (dev local)
        │
        ├──► Claude API (Anthropic) — proveedor primario
        │
        └──► Gemini API (Google) — fallback si no hay CLAUDE_API_KEY válida
```

Una sola URL sirve todo: `http://localhost:8000/` (frontend), `/api/...` (REST), `/docs` (Swagger), y el WebSocket de Socket.io para el chat en tiempo real.

### Stack

- fastapi 0.111.0
- uvicorn[standard] 0.29.0
- python-socketio 5.11.2
- sqlalchemy 2.0.41
- psycopg2-binary 2.9.10
- python-jose[cryptography] 3.3.0
- passlib[bcrypt] 1.7.4 / bcrypt 4.0.1
- python-multipart 0.0.9
- anthropic ≥0.40.0
- google-genai ≥1.0.0
- stripe 9.9.0
- python-dotenv 1.0.1
- pydantic-settings 2.2.1
- aiofiles 23.2.1
- python-docx 1.1.2
- pytest 8.4.2

### Variables de entorno requeridas

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | Cadena de conexión — SQLite en dev, PostgreSQL en producción (Railway) |
| `SECRET_KEY` | Clave secreta para firmar JWT |
| `ALGORITHM` | Algoritmo JWT (default `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Expiración del token (default 10080 = 7 días) |
| `CLAUDE_API_KEY` (alias `ANTHROPIC_API_KEY`) | Clave de la API de Anthropic |
| `CLAUDE_MODEL` | Modelo de Claude a usar |
| `GOOGLE_API_KEY` | Clave de Gemini — si está y `CLAUDE_API_KEY` no es válida, se usa como fallback |
| `GEMINI_MODEL` | Modelo de Gemini a usar |
| `STRIPE_SECRET_KEY` | Clave secreta de Stripe |
| `STRIPE_WEBHOOK_SECRET` | Secreto del webhook de Stripe |
| `STRIPE_PRICE_ID_PRO` | Legacy (USD) — ya no lo referencia el checkout |
| `STRIPE_PRICE_ID_DOCENTE_COP` | ID del precio del plan Docente en COP (Stripe Dashboard) |
| `STRIPE_PRICE_ID_PRO_COP` | ID del precio del plan Pro en COP (Stripe Dashboard) |
| `FRONTEND_URL` | URL del frontend, usada para CORS |
| `SENDGRID_API_KEY` | Clave de SendGrid (envío de correo, opción 1) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_TLS` | Config SMTP (envío de correo, opción 2, fallback si no hay SendGrid) |
| `FROM_EMAIL` / `FROM_NAME` | Remitente de los correos enviados |
| `UPLOAD_DIR` | Carpeta de archivos subidos |
| `MAX_FILE_SIZE_MB` | Tamaño máximo de archivo subido |
| `ENVIRONMENT` | `development` / `production` |

Si ninguno de `SENDGRID_API_KEY` o el bloque SMTP está configurado, `email_service.py` cae automáticamente a un modo "LogOnly" que imprime el link de verificación por consola — el flujo de auth funciona igual en desarrollo local sin cuenta de correo real.

### Estructura de directorios

```
.
├── backend/
│   ├── auth.py, chat.py, config.py, database.py, documento.py
│   ├── email_service.py, grupos.py, ia.py, institucion.py, llm.py
│   ├── markdown_parser.py, migrate.py, models.py, permisos.py
│   ├── piar.py, prompts.py, schemas.py, sesiones.py
│   ├── socket_events.py, suscripciones.py, main.py
│   ├── frontend/          (14 HTML + manifest.json + service-worker.js + css/ + js/ + assets/)
│   ├── tests/              (25 archivos, 255 tests)
│   └── requirements.txt, .env.example, Procfile
├── docs/
│   └── legal/               (3 borradores + README)
├── .github/
│   └── workflows/tests.yml
├── Procfile
├── requirements.txt          (delega a backend/requirements.txt)
├── README.md
└── RESUMEN.md
```

---

## Costos de infraestructura

| Servicio | Plan actual | Costo/mes | Notas |
|----------|-------------|-----------|-------|
| Railway | Pro | $20 USD | Backend + PostgreSQL |
| Anthropic API | Pay-per-use | ~$30–150 USD | Según uso |
| SendGrid | Free | $0 | <100 emails/día |
| Dominio | - | $2 USD | Pendiente registrar |
| **Total** | | **~$52–172 USD** | |

---

## Modelo de negocio

| Plan | Precio COP | Límites | Estado |
|------|------------|---------|--------|
| Gratis | $0 | Límites diarios por modo actuales (10 planeación / 20 socioemocional / 20 calificación / 5 PIAR) | 🟡 Límites técnicos existen, falta confirmar si corresponden al plan Gratis o son globales |
| Docente | $25.000 COP/mes | Igual que Pro (999999 — "ilimitado") | 🟡 Precio de venta definido; el checkout de Stripe existe en código (PR #39) pero está inactivo (ver "Estado del negocio"). Internamente activaría el mismo `Suscripcion.plan="pro"` que el plan Pro — no es un tier separado a nivel de datos, solo a nivel de precio de venta |
| Pro | $45.000 COP/mes | `config.LIMITES_PLAN["pro"]` — sin límites diarios de mensajes/grupos | 🟡 Precio de venta definido; cobro real hoy es manual por WhatsApp, no vía el checkout de Stripe (inactivo) |
| Institución | Por definir | Roles coordinador/rector, agregados institucionales | 🟡 Backend de roles ya existe (`Institucion.plan == 'institucional'`), falta modelo de precio |

`precios.html` (frontend) sigue sin actualizar a estos precios en COP ni a la paleta de marca — pendiente, ver backlog de Prioridad 1.

---

## Estado del negocio

- **Usuarios activos**: en beta cerrada.
- **Upgrades a Pro**: manuales por WhatsApp (número de WhatsApp Business pendiente de definir/publicar).
- **Wompi**: pendiente verificación de cuenta — ver fila en el backlog de Prioridad 1.
- **Stripe**: configurado en código (PR #39, PSE/Nequi/COP) pero sin activar — no hay cuenta Stripe Colombia.
- **Precio Pro**: $45.000 COP/mes.
- **Punto de equilibrio**: 9 usuarios Pro (a los costos de infraestructura actuales — ver tabla de Costos).

---

## Marca

- Nombre: Maestr.ia
- Tagline: "Tu colega que conoce la ley"
- Colores: #0B3D2E (oscuro), #1D9E75 (principal), #F5B731 (ámbar)
- Mascota: Chispa (pendiente integración en UI)
- Logo: backend/frontend/assets/logo.png ✅

---

## Contexto académico

Este proyecto es la tesis doctoral de Jorge Eduardo Londoño Arango.
El objetivo de investigación incluye benchmark comparativo de modelos
IA (Claude, GPT-4, Gemini) aplicados a educación inclusiva colombiana.
Los perfiles de evaluación del benchmark están diseñados pero pendientes
de ejecución una vez estén disponibles las API keys de OpenAI y Google.

---

## Próximos sprints recomendados

1. **Verificación visual real en un dispositivo/DevTools** — ningún sprint de frontend de esta sesión (#36, #40, #42) se probó en un browser real, sin excepción. Incluye: responsive de las 8 páginas, instalación de la PWA ("Agregar a pantalla de inicio" en Android/iOS), y el flujo de descarga de DOCX en iOS Safari.
2. **Reemplazar el número de WhatsApp placeholder** (+57 300 000 0000) por el real — está repetido en `index.html` (PR #40) y ahora también en `precios.html` (PR #42), más de 10 links en total.
3. **El commit separado de `main.py`** (redirect a dashboard si hay JWT válido) que se dejó pendiente a propósito desde el PR #40.
4. **Onboarding guiado primer uso** — no hay nada implementado todavía; no estaba en el backlog original.
5. **Wompi** — retomar cuando haya tracción real (20–30 usuarios Pro pagando manual por WhatsApp). Requiere cuenta Wompi verificada + reescritura de `suscripciones.py`.
6. **Benchmark de modelos IA** — objetivo de la tesis doctoral (ver "Contexto académico"); pendiente de API keys de OpenAI y Google.
7. **Mascota Chispa en estados de la UI** — sin implementar, sin assets encontrados en el repo.

---
*Generado automáticamente por Claude Code el 2026-08-05*
*Repositorio: github.com/Guacen/asistente-pedagogico-ia*
