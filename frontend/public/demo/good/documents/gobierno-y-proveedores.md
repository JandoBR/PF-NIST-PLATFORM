# Marco de gobierno de ciberseguridad

## Contexto de la organizacion

La mision de la organizacion es procesar pagos electronicos para comercios medianos de la region con
disponibilidad continua. Las partes interesadas consideradas en la gestion del riesgo son los
comercios clientes, los titulares de las tarjetas, la Superintendencia Financiera, los accionistas y
el equipo interno de operaciones.

Los requisitos legales, regulatorios y contractuales aplicables son la Ley 1581 de proteccion de
datos personales, el estandar PCI DSS para datos de tarjetas y los acuerdos de nivel de servicio
firmados con cada comercio, incluidas sus clausulas de privacidad.

Los servicios criticos de los que dependen nuestros clientes son la plataforma de pagos, el portal
de conciliacion y la emision de reportes regulatorios. A su vez, la operacion depende de terceros:
el proveedor de nube, la pasarela bancaria, el servicio de firma electronica y el proveedor de
monitoreo.

## Programa de proveedores y terceros

Existe un programa de gestion del riesgo de proveedores con politicas aprobadas por el comite de
seguridad. Los roles estan acordados por escrito: cada proveedor critico tiene un responsable
interno y un punto de contacto designado del lado del proveedor, con responsabilidades de reporte de
incidentes.

Se mantiene un inventario de proveedores clasificado por criticidad (alta, media y baja) segun el
dato que procesan y su impacto en los servicios criticos; la revision del inventario es semestral.

Todos los contratos con proveedores de criticidad alta incorporan requisitos de ciberseguridad:
cifrado de datos en transito y en reposo, notificacion de incidentes en 24 horas, derecho de
auditoria y devolucion o borrado certificado de los datos al terminar la relacion.

## Concienciacion y formacion

Existe un programa de concienciacion en seguridad obligatorio para todo el personal, con una
frecuencia anual y una campana de phishing simulado cada trimestre. Ademas, los roles
especializados reciben formacion especifica: el equipo de infraestructura en endurecimiento de
servidores y manejo de secretos, el equipo de desarrollo en codificacion segura y el equipo de
guardia en respuesta a incidentes. La asistencia se registra por persona y rol.
