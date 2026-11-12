# Data handling / Manejo de datos

Nuestra plataforma corre en AWS. La base de datos de producción es una instancia RDS
(aws_db_instance.pagos), el bucket de evidencias es aws_s3_bucket.evidencia y el balanceador es
aws_lb.publico. El rol de extracción es aws_iam_role.etl.

Los datos personales de clientes (nombre, documento, dirección y teléfono) se clasifican como
confidenciales; los registros de auditoría se clasifican como internos. Los datos de tarjetas no se
almacenan; el procesamiento lo hace la pasarela certificada.

El proveedor de identidad es Okta. Tenemos un acuerdo de seguridad firmado que exige notificación
de incidentes en 24 horas y auditoría anual; su desempeño se revisa cada semestre en el comité.
