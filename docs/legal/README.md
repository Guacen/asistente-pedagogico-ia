# Documentos legales — BORRADORES

> ⚠️ **Estos son borradores técnicos preparados por un asistente de código, NO por un abogado.** Requieren revisión por abogado colombiano con experticia en Ley 1581/2012, hábeas data, y protección de datos de menores antes de publicarse. No usar en producción sin esa revisión.

## Archivos
- **[politica_tratamiento_datos.md](politica_tratamiento_datos.md)** — política de tratamiento de datos personales (Ley 1581/2012 + Decreto 1377/2013 + Circular Externa SIC 002/2015).
- **[terminos_de_uso.md](terminos_de_uso.md)** — términos y condiciones de la plataforma.
- **[consentimiento_registro.md](consentimiento_registro.md)** — texto exacto del checkbox de aceptación al registrarse + evidencia técnica que debe capturarse.

## ¿Por qué es urgente?
La plataforma toca datos sensibles de menores con discapacidad (PIAR, diagnóstico clínico, ajustes razonables). Aunque el tratamiento se hace bajo autorización del docente/institución educativa, la Ley 1581 aplica desde el primer registro real. La Fase A (generador de PIAR) empeora la exposición porque persiste diagnósticos clínicos en la BD y en documentos DOCX descargables.

## Puntos que específicamente necesitan opinión legal
1. **Base legal del tratamiento**: ¿es "consentimiento" (docente autoriza) o "función pública/interés legítimo" (obligación escolar)? Cambia qué información hay que darle al titular.
2. **Datos sensibles de menores**: el art. 7 de la Ley 1581 exige autorización previa y expresa de padres/representante legal para tratamiento de datos de menores. La plataforma la tiene indirecta (a través del colegio). Verificar suficiencia.
3. **PIAR y diagnóstico clínico** son datos sensibles de salud (art. 5 Ley 1581). Reglas más estrictas de tratamiento, encargados, transferencia internacional (si hay cloud fuera de Colombia).
4. **Notificación de incidentes**: SIC exige reportar violaciones de seguridad. Definir umbral, tiempo y canal.
5. **Habeas data**: la plataforma debe permitir al titular ejercer sus derechos (conocer, actualizar, rectificar, revocar). Los borradores lo mencionan pero no está implementado en la aplicación aún.
6. **Retención**: la Ley no fija plazo específico para datos escolares. Definir política institucional (¿5 años tras egresar? ¿durante la vida escolar?).
7. **Transferencia internacional**: si Railway/AWS aloja fuera de Colombia, aplican reglas adicionales (nivel adecuado de protección, cláusulas contractuales).

## Referencias
- [Ley 1581 de 2012](https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=49981)
- [Decreto 1377 de 2013](https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=53646)
- [Circular Externa SIC 002 de 2015](https://www.sic.gov.co/sites/default/files/normatividad/Circular_Externa_002_de_2015.pdf)
- [Guía SIC — Protección de datos personales](https://www.sic.gov.co/proteccion-de-datos-personales)
- [Guía MEN sobre PIAR — Decreto 1421 de 2017](https://www.mineducacion.gov.co/1780/w3-article-360293.html)
