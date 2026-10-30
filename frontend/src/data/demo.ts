// Paquetes de evidencia de ejemplo, servidos como archivos estaticos desde /public/demo. Son tres
// momentos de una misma organizacion (con brechas -> en mejora -> conforme), pensados para que cada
// uno muestre tramos distintos de la escala y para que "Comparar" tenga algo que contar. Los
// puntajes tecnicos que producen estan fijados en backend/tests/test_demo_bundles.py. Los
// documentos cubren Gobernar, Identificar, Responder y Recuperar, que sin documentos quedan sin
// evidencia, y solo se leen con la capa de IA activada.

export interface DemoBundle {
  id: string;
  label: string;
  description: string;
  terraform?: string[];
  ansible?: string[];
  documents?: string[];
}

export const DEMO_BUNDLES: DemoBundle[] = [
  {
    id: 'gaps',
    label: 'Entorno con brechas',
    description:
      'SSH y RDP abiertos a Internet, una base de datos pública sin cifrar ni respaldos y login de root habilitado. Hallazgos de severidad alta y media.',
    terraform: [
      '/demo/gaps/terraform/main.tf',
      '/demo/gaps/terraform/plataforma.tf',
      '/demo/gaps/terraform/versiones.tf',
    ],
    ansible: ['/demo/gaps/ansible/hardening.yml'],
    documents: [
      '/demo/gaps/documents/politica-seguridad.md',
      '/demo/gaps/documents/manual-operaciones.md',
      '/demo/gaps/documents/roles.md',
      '/demo/gaps/documents/riesgos-y-respaldos.md',
    ],
  },
  {
    id: 'mid',
    label: 'Entorno en mejora',
    description:
      'Lo grave ya está corregido, pero queda trabajo a medias: una base sin cifrar, un bucket sin bloqueo público, SSH aún con contraseña y respaldos por debajo de la política. Puntajes intermedios y evidencia insuficiente.',
    terraform: [
      '/demo/mid/terraform/main.tf',
      '/demo/mid/terraform/plataforma.tf',
      '/demo/mid/terraform/security.tf',
      '/demo/mid/terraform/versiones.tf',
    ],
    ansible: ['/demo/mid/ansible/hardening.yml'],
    documents: [
      '/demo/mid/documents/politica-seguridad.md',
      '/demo/mid/documents/gobierno-y-proveedores.md',
      '/demo/mid/documents/roles.md',
      '/demo/mid/documents/riesgos-e-inventario.md',
      '/demo/mid/documents/continuidad.md',
      '/demo/mid/documents/respuesta-incidentes.md',
    ],
  },
  {
    id: 'good',
    label: 'Entorno conforme',
    description:
      'Cifrado, respaldos, SSH endurecido, registro multirregión y políticas completas. Queda una brecha menor: el bloqueo público de un bucket está incompleto.',
    terraform: [
      '/demo/good/terraform/main.tf',
      '/demo/good/terraform/plataforma.tf',
      '/demo/good/terraform/versiones.tf',
    ],
    ansible: ['/demo/good/ansible/hardening.yml'],
    documents: [
      '/demo/good/documents/politica-seguridad.md',
      '/demo/good/documents/gobierno-y-proveedores.md',
      '/demo/good/documents/roles-y-responsabilidades.md',
      '/demo/good/documents/gestion-de-riesgos.md',
      '/demo/good/documents/respuesta-incidentes.md',
      '/demo/good/documents/continuidad.md',
    ],
  },
];

export interface DemoEventLog {
  id: string;
  label: string;
  description: string;
  file: string;
}

// Cada log es un escenario distinto del mismo día, no una continuación del anterior: el botón
// limpia los eventos de la organización antes de cargarlo.
export const DEMO_EVENT_LOGS: DemoEventLog[] = [
  {
    id: 'incidentes-demo',
    label: 'Con incidentes',
    description:
      'Ráfaga de fallos de autenticación sin alerta, incidente declarado que nunca se escala y un ejercicio de restauración fallido: abre 3 incidentes (D1, D3, D4).',
    file: '/demo/events/incidentes-demo.jsonl',
  },
  {
    id: 'respuesta-parcial-demo',
    label: 'Respuesta parcial',
    description:
      'Hay alerta y triaje a tiempo, pero el incidente se escala tarde y la restauración verificada nunca se comunica: abre 2 incidentes (D3, D5).',
    file: '/demo/events/respuesta-parcial-demo.jsonl',
  },
  {
    id: 'flujo-correcto-demo',
    label: 'Flujo correcto',
    description:
      'Alerta, triaje, escalamiento, restauración verificada y comunicación, todo a tiempo: no abre incidentes.',
    file: '/demo/events/flujo-correcto-demo.jsonl',
  },
];

export async function fetchAsFile(url: string): Promise<File> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`No se pudo cargar el archivo de ejemplo ${url}`);
  const blob = await response.blob();
  const name = url.split('/').pop() ?? 'archivo';
  return new File([blob], name, { type: blob.type });
}
