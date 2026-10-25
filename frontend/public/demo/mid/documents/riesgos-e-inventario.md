# Riesgos e inventario

## Objetivos de riesgo

El objetivo de riesgo de la organizacion es mantener disponible la plataforma de clientes y evitar
la perdida de sus datos. La tolerancia aceptada es de hasta un dia de interrupcion al mes.

Cuando un riesgo se identifica, el responsable de seguridad decide si se mitiga, se acepta o se
traslada al proveedor. Todavia no hay un metodo unico de calculo ni lineas de comunicacion del
riesgo definidas por escrito.

## Proceso de evaluacion de riesgos

Una vez al ano el responsable de seguridad identifica las amenazas principales con cada area, estima
su impacto y acuerda las medidas a tomar.

## Inventario de activos

El inventario de activos incluye: aws_db_instance (bases de datos de clientes y de reportes) y
aws_s3_bucket (documentos y exportes).

## Inventario de datos

La base de datos de clientes contiene nombres, correos y direcciones de entrega. La base de reportes
contiene cifras de ventas.
