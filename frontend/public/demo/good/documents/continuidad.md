# Plan de continuidad

## Respaldos

Todas las bases de datos de produccion se respaldan cada noche. Los respaldos se conservan durante
7 dias y su integridad se verifica semanalmente mediante una restauracion de prueba.

## Recuperacion ante desastres

En caso de caida del sitio principal, el equipo de infraestructura activa el sitio secundario,
restaura el ultimo respaldo verificado y valida los servicios criticos. El responsable de ejecutar la
recuperacion es el Jefe de Infraestructura. El procedimiento se activa cuando el sitio principal
permanece caido mas de dos horas.

## Exposicion de datos

Queda prohibido exponer bases de datos a Internet. Todo acceso a las bases de datos debe pasar por la
red privada.
