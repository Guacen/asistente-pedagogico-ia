# RESUMEN — Maestr.ia

*Estado real del proyecto al 2026-08-07. Reemplaza la versión anterior de este archivo (una guía de deploy a Hostinger de una etapa muy temprana, completamente desactualizada frente a la arquitectura real). Para el historial completo de sprints y el backlog priorizado con detalle línea por línea, ver [`docs/PLAN.md`](docs/PLAN.md) — este documento es la versión ejecutiva: qué está hecho, qué está en curso, qué falta y por qué.*

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

**Esta sesión** (PRs #43–#55):
- **#44** — Adaptador de correo Resend (Railway bloquea SMTP saliente), con fallback Resend → SendGrid → SMTP → LogOnly.
- **#45, #46** — Número real de WhatsApp Business en todos los CTAs del sitio.
- **#47** — Política de Tratamiento de Datos y Términos de Uso v1.0 (páginas nuevas).
- **#48, #49** — Seguidor de Malla Curricular: catálogo de 412 DBA del MEN (Derechos Básicos de Aprendizaje), generación de malla por IA, seguimiento de cobertura por período.
- **#50** — Prueba gratuita self-service de 7 días: registro sin tarjeta, bloqueo automático (402) al vencer vía `verify_trial_active`, aplicado a todos los endpoints de producto (REST + Socket.io del chat en tiempo real).
- **#51** — Integración de pagos Wompi: checkout PSE/Nequi/tarjeta, webhook de confirmación con verificación de firma real (corregida contra la documentación oficial de Wompi, no la que traía el spec original), reactivación automática de cuentas con trial vencido. Incluye el mismo fix aplicado retroactivamente al webhook de Stripe.
- **#52** — Brand kit oficial del diseñador (logo, isotipo, versión blanca) reemplazando los placeholders.
- **#53** — `Cache-Control: no-cache` en `/assets/*` y `/css/*` para que Cloudflare siempre revalide con el origen.
- **#54** — Logo visible en el sidebar oscuro del dashboard (antes invisible), tamaño correcto en todos los nav (antes ínfimo por un bug de sizing por alto en vez de ancho), widget "Plan Pro" del sidebar con contraste corregido y sin emoji suelto.
- **#55** — Datos reales de contacto en las páginas legales (ciudad, correo `legal@usemaestria.co`, razón social/NIT con comentarios HTML de lo que sigue pendiente).

**Tests**: 322 pasando (0 fallos), suite completa corre en CI en cada PR contra `main`.

---

## EN PROGRESO

**Ninguno.** No hay PRs abiertos ni corriendo CI en este momento — todo lo mergeado hasta el PR #55 está en `main`.

---

## PENDIENTE TÉCNICO

En orden de prioridad:

1. **Wompi: pasar de sandbox a producción.** El código está completo desde el #51, pero corre contra el ambiente sandbox de Wompi. Falta: activar las claves reales de producción en Railway, hacer una transacción real de prueba, y confirmar que el webhook llega y se procesa correctamente en producción (no sólo en tests).
2. **Retirar o archivar el código de Stripe** (#39) una vez Wompi esté confirmado en producción — hoy coexisten dos pasarelas de pago, sólo una se va a usar (ver Deuda técnica).
3. **Extender la verificación visual real al resto del frontend.** Hasta el #54 (este mismo sprint) todo el trabajo de UI se validaba sólo leyendo código — recién se demostró que headless Chrome funciona en este entorno y se usó para auditar logo/dashboard con screenshots reales. Faltan por auditar así: `grupo-panel.html`, `cuenta.html`, `panel-docente.html`, `chat.html`, y los breakpoints móviles reales (hoy sólo verificados por lectura de CSS).
4. **Mascota Chispa** — sin ningún asset ni integración en la UI todavía.
5. **Onboarding guiado de primer uso** — no implementado.
6. **Exportación a PDF desde el chat** — hoy sólo DOCX vía PIAR/documento.py.
7. **Programa de referidos** — no implementado.
8. **Dashboard de analítica por estudiante** — no implementado.
9. **Benchmark de modelos IA** (Claude/GPT/Gemini, objetivo de la tesis doctoral) — diseño de perfiles de evaluación existe fuera del repo, pendiente de API keys de OpenAI y Google.
10. **API pública para integraciones** e **integración con SIMAT** — Prioridad de escala, sin empezar.

---

## PENDIENTE NO-TÉCNICO

Bloqueado por decisiones externas, no por código:

- **Constitución de la SAS** — la razón social legal sigue sin definir; las páginas legales muestran "Maestr.ia" como nombre comercial neutro con un comentario HTML `<!-- PENDIENTE: razón social SAS -->` (#55) en vez de inventar un nombre.
- **NIT** — pendiente de asignación (depende de la constitución de la SAS). Se muestra en pantalla como "(en trámite)", con comentario HTML de seguimiento.
- **Revisión legal profesional** de la Política de Tratamiento de Datos y los Términos de Uso — son borradores técnicos redactados sin abogado, nunca revisados formalmente. La "fecha de entrada en vigencia" de ambos documentos sigue en blanco ("pendiente de publicación") hasta que eso pase.
- **Registro ante la SIC** (Superintendencia de Industria y Comercio) — obligatorio porque la plataforma trata datos sensibles de menores con discapacidad (diagnósticos, vía PIAR).
- **Cuenta Wompi de producción verificada** (KYC del comercio + cuenta bancaria asociada) — bloquea el punto 1 de Pendiente Técnico.
- **Facturación electrónica DIAN** — necesaria en cuanto haya cobros reales, no configurada todavía.
- **Licencia de industria y comercio municipal** — pendiente de confirmar.
- **Primeros usuarios beta pagando** — el flujo completo trial→pago (#50 + #51) está construido de punta a punta pero nunca se probó con un usuario real pagando con dinero real.
- **Buzón `legal@usemaestria.co`** — el dominio ya tiene Cloudflare Email Routing activo (usado hoy por `hola@usemaestria.co`); falta solamente agregar la regla de forwarding para `legal@` en el dashboard de Cloudflare (2 clics, sin cambios de DNS) — pendiente de que el usuario lo haga, no depende de código.

---

## DEUDA TÉCNICA

Cosas que funcionan pero están incompletas o frágiles:

- **Dos pasarelas de pago en el código a la vez**: Stripe (#39, nunca operó como procesador local en Colombia) y Wompi (#51, en sandbox). Ambas activan internamente el mismo `Suscripcion.plan="pro"` y ambos webhooks desbloquean el trial — es lógica duplicada que hay que consolidar en una sola vez Wompi esté confirmado en producción.
- **Calidad de datos del catálogo DBA** (#48/#49, 412 registros): el campo `evidencias` viene truncado a ~200 caracteres con viñetas `"m ..."` sin separar, heredado de la fuente original sin limpiar. No bloquea el uso del seguidor de malla curricular, pero degrada la calidad del contenido mostrado.
- **CI de GitHub Actions con fallas de entrega intermitentes**: al menos 2 veces en esta sesión (PR #49, PR #50) los workflows tardaron en dispararse o nunca lo hicieron por un problema de infraestructura de GitHub, no del código. En el caso del PR #50 esto requirió mergear directo vía API sin esperar el check, con autorización explícita del usuario tras confirmar que no era un fallo real.
- **Tests corren 100% contra SQLite en memoria** — nunca se ha corrido la suite contra PostgreSQL real (el motor de producción en Railway), así que diferencias de comportamiento entre motores no están cubiertas por tests.
- **`grupo-panel.html` sigue sin sección de Observaciones ni de PIAR** (deuda heredada del #41) — esas dos features viven en `grupos.html` en su lugar, por una inconsistencia entre lo que pedía el spec original y dónde vive realmente la ficha del estudiante.
- **Rate limiting atado a fecha calendario, no al período académico** (`Grupo.periodo_actual`) — el reset es manual vía endpoint admin (#37), sin cron automático.
- **Sin medición de cobertura de línea** (`coverage.py`) — 322 tests dan buena señal cualitativa de negocio, pero no hay un % de cobertura de código reportado.
- **Envío de correo por Resend** (#44, con fallback SendGrid→SMTP→LogOnly) — nunca confirmado el envío real end-to-end en producción con una bandeja real, sólo a nivel de código y tests mockeados.

---
*Generado por Claude Code el 2026-08-07 — repositorio github.com/Guacen/asistente-pedagogico-ia.*
