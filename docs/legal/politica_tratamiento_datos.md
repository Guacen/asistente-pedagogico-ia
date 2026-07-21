# Política de Tratamiento de Datos Personales — BORRADOR

> ⚠️ **BORRADOR TÉCNICO — REQUIERE REVISIÓN LEGAL** antes de publicarse. No es asesoría jurídica. Preparado como punto de partida basado en Ley 1581 de 2012, Decreto 1377 de 2013 y Circular Externa SIC 002 de 2015. Ver [README](README.md) para lista de puntos que exigen opinión de abogado.

---

**Última actualización del borrador:** [fecha de publicación aprobada]
**Versión:** 1.0 (draft)
**Responsable del tratamiento:** [Razón social a definir], NIT [pendiente], domicilio [pendiente], correo `datos@[dominio.pendiente]`, teléfono [pendiente].

## 1. Objeto y ámbito

Esta Política regula el tratamiento de datos personales recolectados a través de la plataforma **Asistente Pedagógico IA** (en adelante "la Plataforma"), en cumplimiento de la Ley 1581 de 2012, el Decreto 1377 de 2013 y la Circular Externa SIC 002 de 2015 de la Superintendencia de Industria y Comercio de Colombia.

La Plataforma es un asistente digital para docentes que registra grupos escolares, estudiantes, calificaciones, ajustes de PIAR y genera documentos pedagógicos apoyados por inteligencia artificial.

## 2. Definiciones

Se adoptan las definiciones del art. 3 de la Ley 1581 de 2012:
- **Titular**: persona natural cuyos datos son objeto de tratamiento.
- **Responsable**: entidad que decide sobre la base de datos (la Plataforma).
- **Encargado**: quien realiza el tratamiento por cuenta del Responsable (proveedores de infraestructura).
- **Datos sensibles**: los que afectan la intimidad o generan discriminación (art. 5), incluyendo salud, orientación sexual, origen étnico, datos de menores, etc.

## 3. Categorías de datos que trata la Plataforma

### 3.1 Datos del Docente (titular directo, autoriza al registrarse)
- Identificación: nombre completo, correo electrónico.
- Institución donde ejerce, ciudad, departamento.
- Autenticación: contraseña (almacenada con hash bcrypt, nunca en texto plano).
- Datos de suscripción y facturación (si aplica plan Pro).
- Datos de uso: número de mensajes con IA por mes, fechas de acceso.

### 3.2 Datos de Estudiantes (titulares indirectos — menores, en su mayoría)
El Docente registra los siguientes datos de sus estudiantes bajo su responsabilidad y con autorización previa de los padres o representantes legales:
- Código de identificación institucional (asignado por el colegio, **no** cédula ni número de identificación oficial).
- Género (opcional).
- Marca de tener PIAR (Plan Individual de Ajustes Razonables).
- **Datos sensibles de salud**: diagnóstico clínico y ajustes razonables asociados al PIAR.
- Calificaciones y evaluaciones académicas.

### 3.3 Metadatos técnicos
- Dirección IP de acceso (para rate limiting y auditoría de seguridad).
- Fechas y horas de creación/modificación de cada registro.
- Contenido de conversaciones con el asistente de IA (para asistir en la generación pedagógica; puede contener referencias a estudiantes por su código).

## 4. Finalidades del tratamiento

Los datos se tratan exclusivamente para:
1. **Prestación del servicio**: gestión de grupos, estudiantes y libro de calificaciones.
2. **Generación de documentos pedagógicos** (planes de clase, boletines, borradores de PIAR) usando modelos de IA a partir del contexto proporcionado por el Docente.
3. **Comunicación operativa** con el Docente sobre uso, incidentes y actualizaciones.
4. **Facturación** en caso de plan Pro.
5. **Cumplimiento de obligaciones legales**, contables y de seguridad.
6. **Seguridad**: registros de acceso, detección de abuso, auditoría de incidentes.

## 5. Base legal del tratamiento

- **Datos del Docente**: consentimiento expreso al aceptar esta Política durante el registro.
- **Datos de Estudiantes**: autorización obtenida por la institución educativa/Docente ante los padres o representantes legales del menor. La Plataforma actúa como Responsable frente al Docente, y como Encargado frente a la institución educativa cuando esta contrata el servicio para varios docentes.

> ⚠️ Este esquema de doble rol requiere ratificación legal — ver punto 1 y 2 del README.

## 6. Derechos del Titular (art. 8 Ley 1581)

Todo titular puede:
- **Conocer** qué datos suyos trata la Plataforma (acceso).
- **Actualizar y rectificar** datos parciales, inexactos o desactualizados.
- **Solicitar prueba** de la autorización otorgada.
- **Ser informado**, previa solicitud, sobre el uso dado a sus datos.
- **Presentar quejas** ante la Superintendencia de Industria y Comercio.
- **Revocar** la autorización y/o **solicitar la supresión** cuando no medie deber legal o contractual de conservación.
- **Acceder gratuitamente** a los datos objeto de tratamiento.

## 7. Cómo ejercer los derechos

Los titulares o sus representantes pueden ejercer sus derechos mediante:
- **Correo electrónico**: `datos@[dominio.pendiente]` con asunto "Habeas Data".
- **Formulario en la Plataforma**: [pendiente de implementación — ver Fase futura].

La solicitud debe indicar: identificación del titular, descripción concreta del derecho a ejercer, dirección de notificación y documentos que sustenten la petición.

**Plazos legales**:
- Consulta: respondida en máximo **10 días hábiles**, prorrogables por 5 días hábiles.
- Reclamo: respondido en máximo **15 días hábiles**, prorrogables por 8 días hábiles.

Si transcurridos los términos el titular no obtiene respuesta, puede presentar queja ante la SIC.

## 8. Encargados y transferencia de datos

La Plataforma se apoya en encargados para prestar el servicio:
- **Proveedor de hosting**: [Railway / AWS / etc. — a definir]. Ubicación de servidores: [pendiente].
- **Proveedor de correo transaccional**: [pendiente].
- **Proveedor de IA (Claude/Anthropic)**: los contenidos enviados al modelo pueden incluir referencias a estudiantes por su código institucional; **no** se envían nombres completos ni identificadores oficiales.

> ⚠️ Si algún proveedor está fuera de Colombia, aplican reglas de transferencia internacional (art. 26 Ley 1581 + Circular 002/2015). Verificar nivel adecuado de protección o suscribir cláusulas contractuales tipo.

## 9. Medidas de seguridad

- Autenticación con contraseñas cifradas (bcrypt).
- Autorización basada en roles (cada Docente sólo accede a sus grupos, verificado por tests automatizados de aislamiento).
- Comunicaciones cifradas en tránsito (TLS/HTTPS).
- Registros de acceso y modificación con marca de tiempo.
- Copias de seguridad de la base de datos [pendiente definir frecuencia y retención].
- Rate limiting por IP para mitigar abuso.

## 10. Retención

- **Datos activos**: mientras el Docente mantenga cuenta activa.
- **Datos históricos de estudiantes**: [pendiente definir política institucional — ver punto 6 del README].
- **Datos de facturación**: 5 años (obligación tributaria).
- **Logs de acceso y auditoría**: 12 meses.
- **Backups**: 30 días.

Al finalizar la retención, los datos se suprimen de forma irreversible.

## 11. Notificación de incidentes

En caso de violación de seguridad que comprometa datos personales, la Plataforma notificará:
- A los titulares afectados en el menor plazo posible.
- A la Superintendencia de Industria y Comercio conforme al régimen aplicable.

> ⚠️ Definir umbral y canal de notificación con abogado.

## 12. Modificaciones a la política

Cualquier modificación se comunicará por correo electrónico al último correo registrado del Docente y se publicará en la Plataforma. El uso continuado después de la notificación implica aceptación de los cambios.

## 13. Legislación aplicable y jurisdicción

Esta Política se rige por las leyes de la República de Colombia. Cualquier controversia se resolverá ante los jueces competentes de [ciudad a definir].

---

**Fin del borrador.**
