import type {
  AssessmentDetail,
  ComparisonOut,
  CriterionResult,
  EvidenceInstance,
  Finding,
  IncidentOut,
  IngestEventsResponse,
  MethodologyCatalog,
  OrganizationOut,
  Plan,
} from '@/lib/types';

// Base de la API, configurable sin recompilar el codigo fuente -- solo el build (ver
// frontend/.env.example). Vacio o "/api" funciona para un despliegue same-origin detras de
// nginx; una URL completa (http://localhost:8000) para desarrollo local con puertos separados.
const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const API_BASE = RAW_BASE.replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, `No se pudo contactar la API en ${API_BASE}. ¿Esta corriendo?`);
  }

  if (!response.ok) {
    let detail = `Error ${response.status} al llamar ${path}.`;
    try {
      const body = await response.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // cuerpo no-JSON o vacio: nos quedamos con el mensaje generico
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function json(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

// --- Metodologia -----------------------------------------------------------------------

export const getHealth = () => request<{ status: string }>('/health');

export const getMethodology = () => request<MethodologyCatalog>('/methodology');

// --- Organizaciones ----------------------------------------------------------------------

export const createOrganization = (nombre: string) =>
  request<OrganizationOut>('/orgs', json({ nombre }));

export const listOrganizations = () => request<OrganizationOut[]>('/orgs');

export const listOrgIncidents = (orgId: string) =>
  request<IncidentOut[]>(`/orgs/${orgId}/incidents`);

export const ingestEvents = (
  orgId: string,
  file: File,
  opts: { useAi?: boolean; confirmLiveAi?: boolean } = {}
) => {
  const form = new FormData();
  form.append('file', file);
  const params = new URLSearchParams();
  if (opts.useAi) params.set('use_ai', 'true');
  if (opts.confirmLiveAi) params.set('confirm_live_ai', 'true');
  const qs = params.toString() ? `?${params.toString()}` : '';
  return request<IngestEventsResponse>(`/orgs/${orgId}/events${qs}`, {
    method: 'POST',
    body: form,
  });
};

// --- Incidentes ----------------------------------------------------------------------------

export const getIncident = (incidentId: string) =>
  request<IncidentOut>(`/incidents/${incidentId}`);

export const getIncidentPlans = (incidentId: string) =>
  request<Plan[]>(`/incidents/${incidentId}/plans`);

// --- Assessments ---------------------------------------------------------------------------

export interface CreateAssessmentInput {
  orgName: string;
  scope?: string;
  aiAdjust?: boolean;
  useAiForDocuments?: boolean;
  confirmLiveAi?: boolean;
  terraformFiles?: File[];
  ansibleFiles?: File[];
  documentFiles?: File[];
}

export const createAssessment = (input: CreateAssessmentInput) => {
  const form = new FormData();
  form.append('org_name', input.orgName);
  form.append('scope', input.scope ?? 'entorno:produccion');
  form.append('ai_adjust', String(input.aiAdjust ?? false));
  form.append('use_ai_for_documents', String(input.useAiForDocuments ?? false));
  form.append('confirm_live_ai', String(input.confirmLiveAi ?? false));
  for (const f of input.terraformFiles ?? []) form.append('terraform_files', f);
  for (const f of input.ansibleFiles ?? []) form.append('ansible_files', f);
  for (const f of input.documentFiles ?? []) form.append('document_files', f);
  return request<AssessmentDetail>('/assessments', { method: 'POST', body: form });
};

export const listAssessments = () => request<AssessmentDetail[]>('/assessments');

export const getAssessment = (id: string) => request<AssessmentDetail>(`/assessments/${id}`);

export const getCriteria = (id: string) =>
  request<CriterionResult[]>(`/assessments/${id}/criteria`);

export const getEvidence = (id: string) =>
  request<EvidenceInstance[]>(`/assessments/${id}/evidence`);

export const getFindings = (id: string) => request<Finding[]>(`/assessments/${id}/findings`);

export const getPlans = (id: string) => request<Plan[]>(`/assessments/${id}/plans`);

export const createPlans = (id: string, opts: { useAi?: boolean; confirmLiveAi?: boolean } = {}) => {
  const params = new URLSearchParams();
  if (opts.useAi) params.set('use_ai', 'true');
  if (opts.confirmLiveAi) params.set('confirm_live_ai', 'true');
  const qs = params.toString() ? `?${params.toString()}` : '';
  return request<Plan[]>(`/assessments/${id}/plans${qs}`, { method: 'POST' });
};

export const reevaluateAssessment = (
  id: string,
  opts: { aiAdjust?: boolean; context?: object; confirmLiveAi?: boolean } = {}
) => {
  const params = new URLSearchParams();
  if (opts.aiAdjust) params.set('ai_adjust', 'true');
  if (opts.confirmLiveAi) params.set('confirm_live_ai', 'true');
  if (opts.context) params.set('context', JSON.stringify(opts.context));
  const qs = params.toString() ? `?${params.toString()}` : '';
  return request<AssessmentDetail>(`/assessments/${id}/reevaluate${qs}`, { method: 'POST' });
};

export const compareAssessments = (idA: string, idB: string) =>
  request<ComparisonOut>(`/assessments/${idA}/compare/${idB}`);
