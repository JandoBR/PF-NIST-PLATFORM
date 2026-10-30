# Gestion de riesgos tecnologicos

## Objetivos y tolerancia

La Direccion General establece como objetivo de riesgo mantener la disponibilidad de la plataforma de
pagos por encima del 99,5 % y no exponer datos personales de clientes. La tolerancia es de hasta
cuatro horas de interrupcion por mes y ninguna exposicion de datos personales. La responsable de
estos objetivos es la Gerente de Operaciones.

El riesgo de ciberseguridad no se gestiona por separado: se consolida en el registro de riesgo
empresarial que revisa la Junta cada trimestre. La estrategia establece las cuatro opciones de
respuesta admitidas para cada riesgo -- mitigar, transferir, aceptar o evitar -- y quien puede
decidir cada una. El metodo de calculo es unico para toda la organizacion: una matriz de impacto por
probabilidad de cinco niveles, con los mismos criterios de categorizacion y priorizacion para todas
las areas. Las lineas de comunicacion del riesgo estan definidas: cada area reporta a su responsable
de riesgo, este al CISO y el CISO al comite de seguridad, con un informe trimestral a la Junta.

## Proceso de evaluacion de riesgos

El proceso de evaluacion de riesgos se ejecuta cada semestre: se identifican amenazas por activo, se
estima impacto y probabilidad, y se priorizan los riesgos por su nivel. Los riesgos quedan en un
registro de riesgos con su responsable y plan de tratamiento. El responsable del proceso es el CISO.

## Inventario de activos

El inventario de activos incluye: aws_db_instance (base de datos de clientes), aws_s3_bucket
(repositorio de documentos), aws_security_group (reglas de red de la aplicacion), aws_cloudtrail
(registro de auditoria), aws_iam_role (identidad de la aplicacion en produccion), aws_iam_policy
(politicas de acceso, incluida la que exige MFA) y aws_autoscaling_group (capacidad de la capa de
aplicacion). La base de datos de clientes tiene criticidad alta; el repositorio de documentos,
criticidad media.

## Inventario de datos

La base de datos de clientes contiene datos personales (nombre, documento de identidad, correo) y
datos de pago; reside en la base de datos principal y se clasifica como confidencial. El repositorio
de documentos guarda contratos y politicas internas, clasificados como de uso interno.
