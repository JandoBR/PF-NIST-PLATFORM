# Continuidad y respaldos

## Respaldos

Las bases de datos de produccion se respaldan cada noche. Los respaldos deben conservarse durante
30 dias.

## Recuperacion

Para recuperar una base de datos, la responsable de infraestructura restaura el ultimo respaldo en
una instancia nueva, redirige la aplicacion hacia ella y comprueba que el servicio responde. Tiene
autoridad para aplicar cambios de emergencia durante la recuperacion.
