// Paquetes de evidencia de ejemplo, servidos como archivos estaticos desde /public/demo. El
// Terraform, el Ansible y los eventos son copias de backend/tests/fixtures (lo que el motor ya sabe
// evaluar). Los documentos estan escritos para la demo: cubren Gobernar, Identificar, Responder y
// Recuperar, que sin documentos quedan sin evidencia. Solo se leen con la capa de IA activada.

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
      'RDS sin cifrar, SSH root habilitado, firewall apagado. Pensado para mostrar hallazgos y planes.',
    terraform: ['/demo/gaps/terraform/main.tf'],
    ansible: ['/demo/gaps/ansible/hardening.yml'],
    documents: [
      '/demo/gaps/documents/politica-seguridad.md',
      '/demo/gaps/documents/manual-operaciones.md',
      '/demo/gaps/documents/roles.md',
      '/demo/gaps/documents/riesgos-y-respaldos.md',
    ],
  },
  {
    id: 'good',
    label: 'Entorno conforme',
    description:
      'RDS cifrado, backups retenidos, bastionado SSH correcto y políticas completas. Pocas o ninguna brecha.',
    terraform: ['/demo/good/terraform/main.tf'],
    ansible: ['/demo/good/ansible/hardening.yml'],
    documents: [
      '/demo/good/documents/politica-seguridad.md',
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

export const DEMO_EVENT_LOGS: DemoEventLog[] = [
  {
    id: 'incidentes-demo',
    label: 'Con incidentes',
    description:
      'Ráfaga de fallos de autenticación sin alerta, incidente declarado sin escalar a tiempo y un ejercicio de restauración fallido: dispara 3 incidentes (D1, D3, D4).',
    file: '/demo/events/incidentes-demo.jsonl',
  },
  {
    id: 'flujo-correcto-demo',
    label: 'Flujo correcto',
    description: 'Los mismos tipos de evento, pero con alerta, escalamiento y restauración a tiempo: no abre incidentes.',
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
