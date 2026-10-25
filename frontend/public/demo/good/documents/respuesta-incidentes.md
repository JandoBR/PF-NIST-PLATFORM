# Plan de respuesta a incidentes

## Proceso de respuesta

El plan de respuesta a incidentes define el triaje inicial, la categorizacion por tipo de incidente y
la priorizacion por impacto en los activos criticos. Los responsables de ejecutarlo son el equipo de
guardia y el CISO.

## Declaracion de incidentes

Se declara un incidente cuando una alerta confirma acceso no autorizado, perdida de disponibilidad de
la plataforma de pagos o exposicion de datos. El equipo de guardia analiza cada alerta y documenta la
decision de declarar o descartar.

## Escalamiento

Si el equipo de guardia no contiene el incidente en una hora, se escala al CISO; si no se resuelve en
cuatro horas, a la Direccion General.

## Cierre de la respuesta e inicio de la recuperacion

La respuesta se da por cerrada y se inicia la recuperacion cuando se cumplen los tres criterios: la
contencion esta confirmada, no quedan indicadores de compromiso activos y el CISO autoriza el
restablecimiento del servicio. A partir de ese momento aplica el procedimiento de recuperacion
descrito en el plan de continuidad.

## Notificacion

Ante un incidente confirmado se notifica de inmediato al CISO, al Jefe de Infraestructura y al area
legal. Los clientes afectados se notifican dentro de las 72 horas siguientes a la confirmacion.

## Analisis posterior

Despues de cada incidente se realiza un analisis de causa raiz y se preservan los registros y la
evidencia en un repositorio de solo lectura durante un ano.

## Contencion y erradicacion

El procedimiento de contencion sigue tres pasos: aislar el recurso afectado de la red, revocar las
credenciales involucradas y bloquear el origen del ataque en el grupo de seguridad. La erradicacion
se considera completa cuando se elimina el artefacto malicioso, se aplica el parche correspondiente
y el equipo de guardia confirma que el indicador de compromiso ya no aparece. El responsable de
ejecutar la contencion es el equipo de guardia, con el visto bueno del CISO.

## Mejora continua

Despues de cada incidente y de cada ejercicio de restauracion se celebra una reunion de lecciones
aprendidas. Los pasos son: revisar lo ocurrido, identificar las mejoras y registrarlas con un
responsable y una fecha. El seguimiento se hace con metricas trimestrales (tiempo medio de deteccion
y de contencion, y porcentaje de mejoras cerradas) y los ajustes que resultan se incorporan al plan
de respuesta y al de continuidad.
