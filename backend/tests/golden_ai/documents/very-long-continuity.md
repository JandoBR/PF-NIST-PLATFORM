# Plan de Continuidad del Negocio — Compañía Regional de Servicios Públicos

## 1. Introducción

El presente Plan de Continuidad del Negocio (PCN) establece cómo la Compañía Regional de Servicios
Públicos (CRSP) mantiene y restablece sus servicios críticos ante interrupciones de distinta
naturaleza. Fue aprobado por el Comité de Continuidad el 9 de octubre de 2025 y sustituye la
versión de 2021.

## 2. Objetivo y alcance

El objetivo es reducir el impacto de una interrupción sobre la facturación, la atención al usuario
y la operación de la red de distribución. El alcance cubre los procesos de facturación, recaudo,
gestión de órdenes de servicio y monitoreo de la red, junto con los sistemas y proveedores que los
soportan.

Quedan fuera del alcance los procesos de talento humano, compras y comunicaciones corporativas, que
cuentan con planes propios.

## 3. Política de continuidad

La continuidad se gestiona como un proceso permanente y no como un documento anual. La Dirección
de Operaciones es la dueña del proceso y la Oficina de Riesgos mantiene la metodología común de
análisis de impacto (BIA). Los resultados del BIA se revisan cada semestre y alimentan el registro
de riesgos corporativo.

## 4. Gobierno y responsabilidades

El Comité de Continuidad está presidido por la Gerente de Operaciones, Ana Lucía Ferrer, y sesiona
trimestralmente. El Coordinador de Continuidad es el jefe de la Oficina de Riesgos, Hernán Quiroga.
Cada proceso crítico tiene un dueño que valida los tiempos objetivo y participa en los simulacros.

La Dirección de Tecnología es responsable de la infraestructura primaria y alterna, y la Dirección
Financiera de aprobar el presupuesto de continuidad. La Oficina Jurídica verifica el cumplimiento
de las obligaciones regulatorias de reporte.

## 5. Análisis de impacto

El BIA vigente identifica cuatro servicios críticos: facturación, recaudo, atención al usuario y
monitoreo de la red. Para cada uno se definieron tiempos objetivos de recuperación y puntos
objetivos de recuperación. La facturación tolera una interrupción máxima de cuatro horas; el
recaudo, de dos horas; la atención al usuario, de ocho horas; y el monitoreo, de una hora.

Los impactos se valoran en una escala de uno a cinco en dimensiones financiera, operativa, legal y
reputacional. La metodología es única para toda la compañía y se documenta en el manual de riesgos.

## 6. Estrategias de continuidad

La estrategia para los sistemas de facturación y recaudo es la replicación en un sitio alterno
ubicado en otra ciudad, con conmutación automática y validación manual. Para la atención al usuario
se dispone de un centro de contactos alterno y de procedimientos manuales de registro de casos.

Para el monitoreo de la red se mantiene un centro de control secundario con acceso a los mismos
tableros y a los registros históricos. La estrategia de personal contempla turnos rotativos y
teletrabajo para los roles que no requieren presencia física.

Las estrategias se prueban al menos una vez al año mediante una conmutación controlada fuera de
horario. El ejercicio incluye la validación de la replicación, la restauración de una muestra de
datos y la medición de los tiempos reales frente a los objetivos definidos. Los resultados se
presentan al Comité de Continuidad y las desviaciones generan un plan de acción con responsable y
fecha. Cuando una estrategia no alcanza el objetivo, se revisa el diseño técnico o se acepta el
riesgo de forma documentada.

La organización no depende de un único proveedor para la conectividad: cuenta con dos enlaces de
fibra de operadores distintos y un enlace satelital de respaldo para el centro de control. La
selección de proveedores de infraestructura considera su capacidad de recuperación y sus
certificaciones vigentes.

## 7. Respaldos

Los respaldos de las bases de datos de facturación y recaudo se ejecutan a diario y se conservan
durante 45 días. Los respaldos de los servidores de aplicación se ejecutan semanalmente y se
conservan 30 días. La integridad de los respaldos se verifica trimestralmente mediante una
restauración completa en el ambiente de pruebas, y el resultado se registra en el informe de
continuidad.

Las copias se almacenan cifradas en dos ubicaciones geográficamente separadas. El acceso a los
respaldos requiere doble aprobación y queda registrado en la bitácora de operaciones.

Las claves de cifrado se custodian en un módulo de hardware administrado por la Dirección de
Tecnología y se rotan cada año. Los medios físicos que se retiran se destruyen y se deja constancia
del procedimiento. Cada trimestre se concilia el inventario de respaldos contra el inventario de
bases de datos para detectar sistemas sin protección.

## 8. Recuperación

En caso de indisponibilidad del sitio principal, el equipo de infraestructura declara la situación
y activa el plan en el siguiente orden: confirmar el alcance de la falla, intentar la conmutación
automática, validar la integridad de los datos replicados y, si es necesario, restaurar el último
respaldo validado. Los servicios se validan con una lista de comprobación por proceso antes de
devolver el tráfico a los usuarios.

El plan se activa cuando el sitio principal permanece caído más de treinta minutos o cuando el
impacto estimado supera el umbral definido por el Comité. El responsable de ejecutar la
recuperación es el Jefe de Infraestructura, Ricardo Peña, con apoyo del equipo de guardia.

La recuperación se da por terminada cuando los servicios críticos están operando en el sitio
alterno, los datos reconciliados y el Comité de Continuidad aprueba el retorno gradual.

Durante la recuperación, el Jefe de Infraestructura puede tomar decisiones técnicas sin consulta
previa, siempre que no comprometan la integridad de los datos. Cualquier cambio de alcance, costo
relevante o comunicación externa requiere aprobación del Comité de Crisis. Las decisiones se
registran en la bitácora con hora, responsable y justificación, y se revisan en el informe posterior
al incidente.

## 9. Comunicaciones y notificación

Las interrupciones que afecten a más de mil usuarios se comunican a la Superintendencia de
Servicios Públicos dentro de las 72 horas siguientes a la confirmación. Los usuarios se informan
por la página web, el centro de contacto y los mensajes masivos, con una frecuencia inicial de cada
dos horas.

La comunicación interna se canaliza a través del Comité de Crisis, que reúne a Operaciones,
Tecnología, Jurídica y Comunicaciones. El vocero oficial es la Dirección de Comunicaciones; ningún
otro colaborador está autorizado para declarar ante medios.

Los reportes a la Superintendencia se presentan por el canal oficial con copia a la Oficina
Jurídica y deben incluir la descripción del evento, los servicios afectados, el número estimado de
usuarios y las acciones adoptadas. Si la información no está completa al vencer el plazo, se
presenta un reporte preliminar y se complementa dentro de los cinco días hábiles siguientes.

## 10. Formación y simulacros

Todo el personal recibe formación anual en continuidad del negocio y en su rol durante una
emergencia. Los equipos de respuesta reciben formación especializada en recuperación de sistemas y
en manejo de crisis. Se realiza un simulacro general al año y simulacros parciales por proceso cada
semestre.

Después de cada simulacro o incidente real se elabora un informe con hallazgos, acciones y
responsables, y los ajustes se incorporan al plan y a los procedimientos asociados.

## 11. Proveedores críticos

La operación depende del proveedor de centro de datos, del proveedor de comunicaciones y de la
pasarela de pagos. Cada proveedor crítico tiene un acuerdo de nivel de servicio con tiempos de
respuesta y recuperación, y participa en los simulacros anuales. Los contratos incluyen
notificación de incidentes en 24 horas y derecho de auditoría.

## 12. Anexo A — Inventario de sedes

| Sede | Ciudad | Rol | Personas | Generador |
|---|---|---|---|---|
| Sede principal | Bogotá | Operación y datacenter primario | 420 | Sí |
| Sede alterna | Medellín | Datacenter secundario y centro de contacto | 180 | Sí |
| Centro de control | Barranquilla | Monitoreo de red | 45 | Sí |
| Bodega norte | Bucaramanga | Logística de medidores | 30 | No |
| Oficina sur | Cali | Atención comercial | 60 | No |

## 13. Anexo B — Glosario

- BIA: análisis de impacto en el negocio.
- RTO: tiempo objetivo de recuperación.
- RPO: punto objetivo de recuperación.
- Sitio primario: instalación donde opera normalmente el servicio.
- Sitio alterno: instalación preparada para asumir la operación.
- Conmutación: cambio controlado de la operación al sitio alterno.
- Simulacro: ejercicio planificado para probar el plan.
- Incidente: evento que interrumpe o degrada un servicio crítico.
- Continuidad: capacidad de mantener las funciones esenciales.
- Resiliencia: capacidad de absorber y recuperarse de una perturbación.
- Comité de Crisis: instancia de decisión durante una emergencia.
- Vocero: persona autorizada para comunicar oficialmente.
- Registro de riesgos: inventario de riesgos con su tratamiento.
- Riesgo residual: riesgo que permanece tras aplicar controles.
- Tercero crítico: proveedor cuya falla afecta un servicio crítico.
- Plan de recuperación: documento con los pasos para restablecer un servicio.
- Prueba de restauración: ejercicio de recuperación de un respaldo.
- Bitácora: registro cronológico de eventos y acciones.
- Umbral: valor a partir del cual se activa una decisión.
- Lección aprendida: conclusión registrada tras un incidente o simulacro.

## 14. Anexo C — Declaración de crisis

La crisis se declara cuando concurren al menos dos de estas condiciones: interrupción de un
servicio crítico por más de cuatro horas, afectación a más de cinco mil usuarios, impacto
reputacional en medios nacionales o requerimiento expreso de la Superintendencia. La declaración
la hace la Gerente de Operaciones o, en su ausencia, el Jefe de Infraestructura.

Declarada la crisis, el Comité de Crisis se instala en la sala de mando o por videoconferencia y
sesiona como mínimo cada cuatro horas. Se activa el registro único de decisiones y se designa un
responsable de comunicaciones. La crisis se cierra cuando los servicios críticos están restablecidos
y el Comité aprueba el informe preliminar.

Las bases de datos de la compañía no se exponen directamente a Internet: todo acceso externo pasa
por la zona desmilitarizada y requiere autenticación. El escalamiento durante una crisis sigue tres
niveles: jefe de turno, Jefe de Infraestructura y Gerente de Operaciones.

## 15. Anexo D — Control de cambios del plan

| Versión | Fecha | Cambio | Aprobado por |
|---|---|---|---|
| 1.0 | 2019-06-30 | Versión inicial | Gerencia General |
| 2.0 | 2021-11-15 | Se incorpora el sitio alterno | Comité de Continuidad |
| 3.0 | 2025-10-09 | Se actualizan RTO, BIA y proveedores críticos | Comité de Continuidad |

El plan se revisa cada año y después de cada incidente relevante. Las versiones anteriores se
conservan por cinco años en el gestor documental.
