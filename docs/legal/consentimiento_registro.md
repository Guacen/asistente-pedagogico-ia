# Consentimiento en el registro — BORRADOR

> ⚠️ **BORRADOR TÉCNICO — REQUIERE REVISIÓN LEGAL.** Ver [README](README.md).

## Texto propuesto del checkbox

En el formulario de registro (registro.html), justo antes del botón "Crear cuenta":

```
☐ He leído y acepto la Política de Tratamiento de Datos y los Términos de Uso.
   Declaro que soy docente en una institución educativa colombiana, que tengo autorización
   previa de los padres o representantes legales de los estudiantes cuyos datos registro
   en la Plataforma, y que uso el servicio con fines pedagógicos legítimos.
```

Con enlaces (`<a target="_blank">`) a:
- [Política de Tratamiento de Datos](politica_tratamiento_datos.md)
- [Términos de Uso](terminos_de_uso.md)

## Evidencia técnica requerida

La Circular SIC 002 de 2015 exige poder probar la autorización. Se debe capturar:

| Campo | Descripción | Origen |
|---|---|---|
| `consentimiento_version` | Versión aceptada (ej. `"policy-1.0/tos-1.0"`) | Constante en backend |
| `consentimiento_aceptado_en` | Timestamp exacto (UTC) del aceptar | Server-side |
| `consentimiento_ip` | IP desde donde se aceptó | `request.client.host` |
| `consentimiento_user_agent` | User-Agent del navegador | Header HTTP |

Estos campos deben persistirse en la tabla `docentes` (o en una tabla `consentimientos` separada si se prefiere auditar históricamente múltiples aceptaciones tras cambios de versión).

## Cambios de código sugeridos (pendientes — no incluidos en este PR)

### Backend
1. Añadir a `models.py::Docente`:
   ```python
   consentimiento_version = Column(String(40))
   consentimiento_aceptado_en = Column(DateTime)
   consentimiento_ip = Column(String(45))
   consentimiento_user_agent = Column(String(500))
   ```
2. Migración idempotente en `migrate.py` para agregar columnas si no existen.
3. Endpoint `POST /api/auth/register` debe:
   - Requerir campo `consentimiento_aceptado: bool` en el body → validar `True`.
   - Rechazar con 400 si `consentimiento_aceptado` es `False` o falta.
   - Guardar los 4 campos de evidencia al crear el `Docente`.

### Frontend
1. `registro.html`: agregar checkbox obligatorio (no submit hasta que esté marcado).
2. Al enviar, enviar `consentimiento_aceptado: true` en el body del POST.
3. Enlaces a `/docs/legal/politica_tratamiento_datos.html` y `.../terminos_de_uso.html` (renderizados en tiempo de build o servidos como Markdown → HTML).

### Docs públicos
- Servir los `.md` como HTML estático desde `/legal/*` (por ejemplo con un microendpoint que renderice el Markdown con `markdown-it`).
- Alternativa mínima: convertir los `.md` a `.html` estáticos y ponerlos en la raíz junto a los otros HTML del proyecto.

## Nota sobre menores
La autorización del padre/representante legal para tratamiento de datos de menores (art. 7 Ley 1581 + Decreto 1377/2013) **no** la captura este checkbox — la captura la institución educativa fuera de la Plataforma. El texto del checkbox le pide al Docente **declarar** que ya la tiene, pero no la sustituye.

Si el modelo comercial cambia a "padres registran directamente a sus hijos", habrá que rediseñar por completo el flujo de autorización para menores.

---

**Fin del borrador.**
