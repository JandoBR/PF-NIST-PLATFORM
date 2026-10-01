// Espejo de los esquemas Pydantic reales de la API (backend/app/evaluation/schemas.py,
// backend/app/recommendations/*, backend/app/schemas/evidence.py, backend/app/api/schemas.py).
// No son datos simulados: estas formas son las que la API devuelve de verdad.

export type Estado =
  | 'evaluado'
  | 'no_implementado'
  | 'evidencia_insuficiente'
  | 'no_aplicable'
  | 'error';

export interface CriterionResult {
  criterion_id: string;
  criterion_version: number;
  estado: Estado;
  base_score: number | null;
  final_score: number | null;
  explanation: string;
  evidence_ids: string[];
  degradado: boolean;
}

export type Nivel = 'subcategoria' | 'categoria' | 'funcion' | 'global';

export interface Aggregate {
  nivel: Nivel;
  ref: string;
  score: number | null;
  cobertura: number | null;
  conteo_estados: Record<string, number>;
}

export interface TierEstimate {
  tier: number | null;
  nombre: string | null;
  provisional: boolean;
  estimable: boolean;
  justificacion: string;
  faltantes: string[];
}

export interface Finding {
  criterion_id: string;
  titulo: string;
  tipo: string;
  severidad: 'alta' | 'media' | 'baja';
  score: number;
  evidence_ids: string[];
}

export interface Plan {
  criterion_id: string;
  titulo: string;
  prioridad: string;
  objetivo: string;
  pasos: string[];
  verificacion: string;
  dependencias: string[];
  generado_por: string;
  origen: 'criterio' | 'evento';
  diagnostico_observable: string | null;
  hipotesis: string[];
  comprobaciones_seguras: string[];
  advertencia: string | null;
}

export type Modality = 'declarada' | 'documental' | 'operativa' | 'contexto';

export interface Locator {
  file: string | null;
  line_start: number | null;
  line_end: number | null;
  page: number | null;
  section: string | null;
  event_id: string | null;
}

export interface EvidenceInstance {
  id: string;
  type_id: string;
  type_version: number;
  subject_type: string;
  subject_ref: string;
  scope: string;
  value: unknown;
  source_id: string;
  locator: Locator;
  observed_at: string;
  modality: Modality;
  limitations: string | null;
  created_by: string;
}

export interface OrganizationOut {
  id: string;
  nombre: string;
}

export interface AssessmentSummary {
  id: string;
  org_id: string;
  org_nombre: string;
  estado: string;
  scope: string;
  methodology_version: string;
  creado_en: string;
  error: string | null;
  score_global: number | null;
  cobertura_global: number | null;
}

export interface AssessmentDetail extends AssessmentSummary {
  agregados_categoria: Aggregate[];
  agregados_funcion: Aggregate[];
  tier: TierEstimate;
}

export interface IncidentOut {
  id: string;
  org_id: string;
  scope: string;
  correlation_key: string;
  titulo: string;
  estado: string;
  severidad: string;
  first_event_time: string;
  last_event_time: string;
  event_ids: string[];
  criterios: string[];
  timeline: Record<string, unknown>[];
  creado_en: string;
  actualizado_en: string;
}

export interface IngestEventsResponse {
  org_id: string;
  eventos_ingeridos: number;
  nuevos_incidentes: IncidentOut[];
  incidentes_actualizados: IncidentOut[];
}

export interface ComparisonDiff {
  criterion_id: string;
  titulo: string;
  estado_antes: string | null;
  estado_despues: string | null;
  score_antes: number | null;
  score_despues: number | null;
  cambio: boolean;
}

export interface ComparisonOut {
  assessment_id_a: string;
  assessment_id_b: string;
  diffs: ComparisonDiff[];
  global_antes: number | null;
  global_despues: number | null;
}

export type JobEstado = 'pendiente' | 'en_progreso' | 'completado' | 'fallido';

export interface JobOut {
  id: string;
  tipo: string;
  estado: JobEstado;
  progreso: number;
  error: string | null;
  assessment_id: string | null;
  org_id: string | null;
  creado_en: string;
  tomado_en: string | null;
  actualizado_en: string;
}

export interface AssessmentAccepted {
  assessment_id: string;
  org_id: string;
  org_nombre: string;
  job_id: string;
}

export interface EventsAccepted {
  org_id: string;
  job_id: string;
}

export interface CriterionDefinition {
  id: string;
  version: number;
  titulo: string;
  tipo: 'tecnico' | 'proceso' | 'mixto';
  funcion: string;
  categorias: string[];
  subcategorias: string[];
  peso: number;
  ai_adjustable: boolean;
  evidencias: string[];
  recomendacion: string;
}

export interface MethodologyCatalog {
  methodology_version: number;
  criterios: CriterionDefinition[];
  tipos_evidencia: string[];
}

export const FUNCTION_NAMES: Record<string, string> = {
  GV: 'Gobernar',
  ID: 'Identificar',
  PR: 'Proteger',
  DE: 'Detectar',
  RS: 'Responder',
  RC: 'Recuperar',
};

export const FUNCTION_ORDER = ['GV', 'ID', 'PR', 'DE', 'RS', 'RC'];

export const TIER_LABELS = [
  'Nivel 1 · Parcial',
  'Nivel 2 · Informado sobre riesgos',
  'Nivel 3 · Repetible',
  'Nivel 4 · Adaptativo',
];
