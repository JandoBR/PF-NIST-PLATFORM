export type Status = 'compliant' | 'partial' | 'critical';
export type Priority = 'high' | 'medium' | 'low';

export type FunctionKey = 'GV' | 'ID' | 'PR' | 'DE' | 'RS' | 'RC';

export interface Subcategory {
  id: string;
  function: FunctionKey;
  label: string;
  status: Status;
  score: number;
}

export interface FunctionMeta {
  key: FunctionKey;
  name: string;
  color: string;
  accent: string;
}

export const FUNCTIONS: FunctionMeta[] = [
  { key: 'GV', name: 'Gobernar', color: 'violet', accent: '#a78bfa' },
  { key: 'ID', name: 'Identificar', color: 'blue', accent: '#60a5fa' },
  { key: 'PR', name: 'Proteger', color: 'emerald', accent: '#34d399' },
  { key: 'DE', name: 'Detectar', color: 'amber', accent: '#fbbf24' },
  { key: 'RS', name: 'Responder', color: 'rose', accent: '#fb7185' },
  { key: 'RC', name: 'Recuperar', color: 'teal', accent: '#2dd4bf' },
];

export interface Architecture {
  id: string;
  name: string;
  summary: string;
  context: string;
  currentTier: number;
  targetTier: number;
}

export const ARCHITECTURES: Architecture[] = [
  {
    id: 'fintech',
    name: 'Infraestructura Cloud Fintech',
    summary: 'Plataforma de pagos multi-nube bajo el alcance de PCI-DSS',
    context:
      'Plataforma de procesamiento de pagos multi-nube (AWS + GCP) que maneja datos de titulares de tarjetas en 3 regiones. Utiliza federación IAM, claves gestionadas con KMS y un modelo de responsabilidad compartida. El SIEM agrega CloudTrail y VPC Flow Logs. El monolito heredado se está descomponiendo en microservicios con mTLS. Acreditación PCI-DSS 4.0 en progreso; se mantiene SOC 2 Tipo II. Sin programa formal de riesgo en la cadena de suministro. Existen guías paso a paso (runbooks) para respuesta a incidentes, pero no se prueban trimestralmente.',
    currentTier: 2,
    targetTier: 4,
  },
  {
    id: 'ecommerce',
    name: 'Sistema de Comercio Electrónico',
    summary: 'Tienda global en Kubernetes con borde CDN',
    context:
      'Tienda global de comercio electrónico sobre EKS con borde en CloudFront, procesando PII para 12 millones de clientes. WAF y mitigación de bots implementados. Secretos en Vault. CI/CD mediante GitHub Actions con controles SAST/DAST. Datos cifrados en reposo con AES-256. Sin práctica dedicada de modelado de amenazas. La detección depende de reglas gestionadas; analítica personalizada limitada. Recuperación ante desastres probada anualmente, RTO de 8 horas.',
    currentTier: 2,
    targetTier: 3,
  },
  {
    id: 'healthcare',
    name: 'Plataforma SaaS de Salud',
    summary: 'EHR compatible con HIPAA y residencia de datos híbrida',
    context:
      'SaaS de registro médico electrónico compatible con HIPAA con residencia de datos híbrida (on-premise y Azure). PHI segmentado por cliente (tenant). APIs FHIR detrás de API gateway con OAuth 2.0. Registros de auditoría inmutables en almacenamiento WORM. Gestión de vulnerabilidades mensual; pruebas de penetración anuales. Registro de riesgos mantenido pero no vinculado a las subcategorías del CSF. Capacidad limitada de ingeniería de detección; sin ejercicios de purple-team.',
    currentTier: 3,
    targetTier: 4,
  },
];

export const TIER_LABELS = [
  'Parcial',
  'Informado sobre riesgos',
  'Repetible',
  'Adaptativo',
];

export const SUBCATEGORIES: Subcategory[] = [
  { id: 'GV.PO-01', function: 'GV', label: 'Contexto organizacional comprendido', status: 'partial', score: 60 },
  { id: 'GV.PO-02', function: 'GV', label: 'Roles y responsabilidades definidos', status: 'compliant', score: 92 },
  { id: 'GV.PO-03', function: 'GV', label: 'Política de ciberseguridad establecida', status: 'partial', score: 68 },
  { id: 'GV.RM-01', function: 'GV', label: 'Estrategia de gestión de riesgos definida', status: 'partial', score: 55 },
  { id: 'GV.RM-06', function: 'GV', label: 'Evaluaciones de riesgo realizadas', status: 'critical', score: 20 },
  { id: 'GV.OV-01', function: 'GV', label: 'Resultados de ciberseguridad supervisados', status: 'partial', score: 58 },
  { id: 'ID.AM-01', function: 'ID', label: 'Inventario de activos mantenido', status: 'compliant', score: 88 },
  { id: 'ID.AM-02', function: 'ID', label: 'Plataformas de software inventariadas', status: 'partial', score: 64 },
  { id: 'ID.AM-03', function: 'ID', label: 'Datos organizacionales clasificados', status: 'partial', score: 70 },
  { id: 'ID.RA-01', function: 'ID', label: 'Vulnerabilidades identificadas', status: 'partial', score: 62 },
  { id: 'ID.RA-03', function: 'ID', label: 'Amenazas identificadas', status: 'critical', score: 28 },
  { id: 'ID.RA-08', function: 'ID', label: 'Riesgo de la cadena de suministro comprendido', status: 'critical', score: 15 },
  { id: 'PR.PS-01', function: 'PR', label: 'Líneas base de configuración aplicadas', status: 'compliant', score: 90 },
  { id: 'PR.PS-04', function: 'PR', label: 'Control de acceso aplicado', status: 'compliant', score: 85 },
  { id: 'PR.PS-05', function: 'PR', label: 'Activos protegidos contra daños', status: 'partial', score: 66 },
  { id: 'PR.DS-01', function: 'PR', label: 'Datos en reposo protegidos', status: 'compliant', score: 94 },
  { id: 'PR.DS-02', function: 'PR', label: 'Datos en tránsito protegidos', status: 'compliant', score: 91 },
  { id: 'PR.AA-04', function: 'PR', label: 'Identidad verificada', status: 'partial', score: 72 },
  { id: 'DE.CM-01', function: 'DE', label: 'Tráfico de red supervisado', status: 'partial', score: 61 },
  { id: 'DE.CM-03', function: 'DE', label: 'Actividad del personal supervisada', status: 'critical', score: 22 },
  { id: 'DE.CM-06', function: 'DE', label: 'Entorno físico supervisado', status: 'partial', score: 58 },
  { id: 'DE.AE-02', function: 'DE', label: 'Anomalías detectadas', status: 'partial', score: 49 },
  { id: 'DE.AE-04', function: 'DE', label: 'Actividad anómala analizada', status: 'critical', score: 30 },
  { id: 'RS.MA-01', function: 'RS', label: 'Incidentes reportados', status: 'compliant', score: 82 },
  { id: 'RS.AN-01', function: 'RS', label: 'Incidentes analizados', status: 'partial', score: 57 },
  { id: 'RS.MI-02', function: 'RS', label: 'Incidentes mitigados', status: 'partial', score: 63 },
  { id: 'RS.RP-01', function: 'RS', label: 'Plan de respuesta ejecutado', status: 'critical', score: 35 },
  { id: 'RS.RP-07', function: 'RS', label: 'Plan de respuesta probado', status: 'critical', score: 18 },
  { id: 'RC.RP-01', function: 'RC', label: 'Plan de recuperación ejecutado', status: 'partial', score: 52 },
  { id: 'RC.RP-04', function: 'RC', label: 'Recuperación probada', status: 'critical', score: 25 },
  { id: 'RC.RP-07', function: 'RC', label: 'Plan de recuperación actualizado', status: 'partial', score: 48 },
  { id: 'RC.CO-03', function: 'RC', label: 'Comunicación de recuperación gestionada', status: 'partial', score: 54 },
];

export interface Recommendation {
  subcategory: string;
  title: string;
  base: string;
  ai: string;
  priority: Priority;
}

export const RECOMMENDATIONS: Recommendation[] = [
  {
    subcategory: 'ID.RA-08',
    title: 'Establecer un programa de gestión de riesgos en la cadena de suministro',
    base: 'Crear y mantener un programa documentado de gestión de riesgos en la cadena de suministro. Revisar la postura de seguridad de los proveedores anualmente y exigir cláusulas contractuales de seguridad.',
    ai: 'Para su plataforma de pagos multi-nube, configure un flujo de riesgo de proveedores basado en SBOM: ingiera SBOMs CycloneDX desde la compilación de cada microservicio, verifíquelos contra OSV/GRYP en CI y bloquee despliegues ante nuevos avisos de severidad alta. Priorice primero a los proveedores bajo el alcance de PCI-DSS (pasarelas de pago, proveedores de HSM en KMS); exija SOC 2 Tipo II + PCI AOC al renovar contratos y evidencia continua a través de Drata/Vanta. Vincule las puntuaciones de riesgo del proveedor con GV.RM-06 para que el registro de riesgos refleje la exposición real y no fotos fijas anuales.',
    priority: 'high',
  },
  {
    subcategory: 'DE.AE-04',
    title: 'Desplegar analítica de anomalías con UEBA',
    base: 'Implementar analítica del comportamiento de usuarios y entidades para detectar actividad anómala. Definir líneas base y alertar sobre desviaciones.',
    ai: 'Su SIEM ya ingiere CloudTrail y VPC Flow Logs; añada un modelo UEBA en identidades de roles de servicio en lugar de usuarios humanos, ya que el 80% de su tráfico este-oeste es entre servicios. Establezca una línea base de frecuencia de llamadas a la API y localidad regional por rol; alerte sobre el uso de tokens entre regiones y nuevas acciones API dentro de la 1 hora posterior a la asunción de un rol IAM. Envíe los eventos enriquecidos a la ruta actual de PagerDuty utilizada para SEV-2. Esto cubre DE.AE-04 y proporciona a RS.AN-01 cronologías de incidentes estructuradas sin costo adicional.',
    priority: 'high',
  },
  {
    subcategory: 'RS.RP-07',
    title: 'Operativizar las pruebas de respuesta a incidentes',
    base: 'Probar el plan de respuesta a incidentes de forma regular. Actualizar el plan según las lecciones aprendidas.',
    ai: 'Sustituya la simulación teórica anual por simulacros trimestrales de purple-team enfocados en la migración de monolito a microservicios: inyecte una credencial de rol de servicio comprometida, una imagen de contenedor maliciosa y un escenario de desviación de políticas en claves KMS. Capture métricas de detección a respuesta en la gestión de casos del SIEM actual e integre las deltas de MTTD/MTTR en la revisión ejecutiva de GV.OV-01. Los runbooks en la wiki actual deben versionarse como código (markdown en el repositorio de la plataforma) para que las actualizaciones se desplieguen mediante la misma revisión CI/CD que los cambios en las aplicaciones.',
    priority: 'high',
  },
  {
    subcategory: 'ID.RA-03',
    title: 'Construir una práctica continua de inteligencia de amenazas',
    base: 'Identificar amenazas para la organización. Mantener y consultar una lista de amenazas.',
    ai: 'Suscríbase a fuentes de inteligencia de amenazas relevantes para fintech (FS-ISAC, CISA KEV, avisos de proveedores cloud) y correlaciónelas automáticamente con su inventario de activos de ID.AM-01. Etiquete cada amenaza con la cuenta cloud afectada y su clasificación de datos para priorizar las reglas de detección según el alcance de PCI. Establezca una reunión semanal de 30 minutos sobre amenazas con los líderes de plataforma y AppSec para revisar coincidencias correlacionadas e integrar 1 o 2 en el backlog de ingeniería de detección en cada ciclo.',
    priority: 'medium',
  },
  {
    subcategory: 'DE.CM-03',
    title: 'Ampliar la supervisión de la actividad del personal',
    base: 'Supervisar la actividad del personal para detectar eventos de ciberseguridad. Revisar los registros de acceso periódicamente.',
    ai: 'Dado su modelo de IAM federado, enfoque la supervisión en el uso de roles de acceso de emergencia (break-glass), inicios de sesión en consola desde rangos CIDR no corporativos y escaladas de privilegios mediante cambios en grupos SSO. Envíe estos eventos al SIEM con una ventana de anomalía de 72 horas en lugar de tiempo real para reducir la fatiga por alertas. Combine esto con una campaña trimestral de recertificación de accesos vinculada a PR.AA-04 para que la supervisión refleje las definiciones de roles actuales y no permisos obsoletos.',
    priority: 'medium',
  },
  {
    subcategory: 'GV.RM-06',
    title: 'Formalizar evaluaciones de riesgo vinculadas al CSF',
    base: 'Realizar evaluaciones de riesgo de forma recurrente. Documentar y compartir los resultados.',
    ai: 'Adopte un registro de riesgos mapeado con el CSF: cada una de las 32 subcategorías evaluadas se convierte en una fila con propietario, probabilidad, impacto y puntuación actual. Actualice trimestralmente extrayendo evidencias de controles desde sus herramientas de cumplimiento (Drata/Vanta) en lugar de encuestas manuales. Presente los 5 principales cambios de riesgo en la revisión ejecutiva de GV.OV-01 para que el CISO pueda mostrar a la junta una trayectoria de madurez defendible hacia el Nivel 4.',
    priority: 'medium',
  },
  {
    subcategory: 'PR.PS-05',
    title: 'Fortalecer la postura de bastionado de activos',
    base: 'Proteger los activos contra daños. Aplicar configuraciones de bastionado (hardening) y gestión de parches.',
    ai: 'Extienda sus líneas base de configuración actuales (CIS para EKS, AWS Foundational Security Best Practices) a una puntuación continua de cumplimiento con autoremediación para desviaciones en cuentas que no son de producción. Para cuentas en el alcance de PCI, aplique un SLO de parcheo de 7 días en CVEs críticas con reversión mediante despliegue canary. Publique la puntuación de cumplimiento por microservicio en el panel de la plataforma para que los propietarios de los servicios asuman la responsabilidad de su postura.',
    priority: 'low',
  },
  {
    subcategory: 'ID.AM-02',
    title: 'Automatizar el inventario de plataformas de software',
    base: 'Mantener un inventario de plataformas y aplicaciones de software. Actualizar con una frecuencia definida.',
    ai: 'Genere SBOMs en tiempo de compilación (CycloneDX mediante su CI/CD actual) y almacénelos junto con el resumen (digest) de cada imagen de contenedor. Esto le brindará un inventario activo y consultable de cada dependencia en todos los microservicios sin hojas de cálculo manuales. Consulte el repositorio de SBOMs desde su flujo de trabajo de gestión de vulnerabilidades para que ID.AM-02 e ID.RA-01 compartan una única fuente de verdad.',
    priority: 'low',
  },
  {
    subcategory: 'RC.RP-04',
    title: 'Operativizar las pruebas de recuperación y resiliencia',
    base: 'Probar el plan de recuperación de forma regular. Actualizar el plan según las lecciones aprendidas.',
    ai: 'Vaya más allá de las simulaciones teóricas anuales de DR e implemente simulacros trimestrales de ingeniería del caos enfocados en su plataforma de pagos: inyecte una caída a nivel de Zona de Disponibilidad (AZ), un estado corrupto en las claves KMS y un escenario de cifrado de datos tipo ransomware. Mida el RTO/RPO respecto a sus compromisos de PCI-DSS y publique los resultados en la revisión ejecutiva de GV.OV-01. Automatice la restauración de infraestructura mediante Terraform + CI/CD para que los runbooks de recuperación se prueben como código y no como documentos. Vincule los resultados de los simulacros con RC.RP-07 para que el plan de recuperación evolucione con cada ejercicio.',
    priority: 'high',
  },
];

export interface ThreatEvent {
  id: string;
  time: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  source: string;
  detail: string;
  mitre: string;
  steps: string[];
}

export const THREAT_EVENTS: ThreatEvent[] = [
  {
    id: 'evt-001',
    time: '14:32:07',
    severity: 'critical',
    title: 'Pico de tráfico anómalo detectado',
    source: 'VPC Flow Logs / eu-west-1',
    detail: 'El tráfico saliente desde payment-api-prod hacia la red desconocida 198.51.100.0/24 aumentó un 3400% respecto a la línea base en 90 segundos. Correlacionado con la asunción de un nuevo rol IAM 4 minutos antes.',
    mitre: 'T1048 — Exfiltración a través de protocolo alternativo',
    steps: [
      'Aislar el grupo de seguridad de payment-api-prod mediante el libro de jugadas de respuesta automatizada; bloquear la salida hacia 198.51.100.0/24.',
      'Revocar los tokens de sesión del rol IAM asumido recientemente y forzar la reautenticación de la cuenta de servicio.',
      'Capturar la memoria volátil y una instantánea forense del disco del pod afectado antes de su terminación.',
      'Consultar CloudTrail para ver todas las acciones realizadas por el rol asumido en los últimos 60 minutos; mapear con MITRE ATT&CK.',
      'Notificar al oficial de cumplimiento de PCI: posible brecha en el alcance de datos de titulares de tarjetas; iniciar la respuesta a brechas de PCI-DSS en un plazo de 1 hora.',
      'Actualizar el caso en el SIEM con la cronología; programar una revisión posterior al incidente dentro de las 72 horas vinculada a RS.RP-07.',
    ],
  },
  {
    id: 'evt-002',
    time: '14:18:52',
    severity: 'high',
    title: 'Rol privilegiado asumido fuera del horario laboral',
    source: 'CloudTrail / IAM',
    detail: 'Rol de emergencia "org-admin-emergency" asumido por una identidad de servicio a las 02:14 UTC, fuera de la ventana de cambios aprobada. No se encontró ningún ticket de incidente asociado.',
    mitre: 'T1078.004 — Cuentas válidas: Cuentas cloud',
    steps: [
      'Confirmar la legitimidad con el SRE de guardia a través de PagerDuty; si no se verifica, revocar la sesión de inmediato.',
      'Auditar todas las acciones de la API realizadas bajo el rol de emergencia en las últimas 2 horas.',
      'Requerir un ticket de cambio retroactivo y adjuntarlo al caso en el SIEM para el registro de auditoría.',
      'Revisar la política de uso de acceso de emergencia y añadir una alerta automatizada para asunciones fuera de ventana.',
    ],
  },
  {
    id: 'evt-003',
    time: '13:55:31',
    severity: 'medium',
    title: 'Volumen de datos inusual hacia almacenamiento de objetos',
    source: 'S3 Access Logs / data-lake-prod',
    detail: 'Una identidad de servicio descargó 412 GB del bucket data-lake-prod, 18 veces el promedio móvil de 30 días para esa identidad.',
    mitre: 'T1530 — Datos desde objeto de almacenamiento en la nube',
    steps: [
      'Verificar si la descarga coincide con una tarea analítica programada; comprobar cambios recientes en el programador de tareas.',
      'Restringir temporalmente la política del bucket a identidades de servicio analíticas conocidas.',
      'Habilitar la revisión de hallazgos de S3 Access Analyzer para el bucket afectado.',
      'Registrar el evento en el registro de riesgos bajo ID.RA-01 para análisis de tendencias.',
    ],
  },
  {
    id: 'evt-004',
    time: '13:41:09',
    severity: 'low',
    title: 'Desviación de configuración en la política de clave KMS',
    source: 'Config Rule / kms-prod',
    detail: 'La política de la clave KMS "payments-cmk-prod" fue modificada para incluir un principal de otra cuenta. Cambio detectado 6 minutos después de ocurrir.',
    mitre: 'T1098 — Manipulación de cuentas',
    steps: [
      'Revisar el evento en CloudTrail para identificar al principal que realizó el cambio y la justificación del negocio.',
      'Si no está justificado, revertir la política de la clave a la última versión válida conocida desde el historial de políticas de KMS.',
      'Añadir una SCP preventiva a nivel de organización para denegar concesiones cruzadas de políticas de claves KMS entre cuentas.',
      'Rastrear la desviación en la puntuación de cumplimiento continuo para las cuentas bajo el alcance de PCI.',
    ],
  },
];