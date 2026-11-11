import type {
  AssessmentAccepted,
  AssessmentDetail,
  ComparisonOut,
  CriterionResult,
  EventsAccepted,
  EventSourceOut,
  Finding,
  IncidentOut,
  JobEstado,
  JobOut,
  MethodologyCatalog,
  Plan,
  PlanEstado,
} from '@/lib/types';

// Base de la API, configurable sin recompilar el codigo fuente -- solo el build (ver
// frontend/.env.example). Vacio o "/api" funciona para un despliegue same-origin detras de
// nginx; una URL completa (http://localhost:8000) para desarrollo local con puertos separados.
const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const API_BASE = RAW_BASE.replace(/\/$/, '');

// --- Sesión (doc 10): el token vive en localStorage y se manda en cada request ---------------

const TOKEN_KEY = 'pf.token';

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY);
export const setToken = (token: string): void => localStorage.setItem(TOKEN_KEY, token);
export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY);
export const hasToken = (): boolean => getToken() !== null;

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError(0, `No se pudo contactar la API en ${API_BASE}. ¿Esta corriendo?`);
  }

  if (response.status === 401) {
    // Sesión inválida/expirada: se limpia y se avisa a la app para volver al login.
    clearToken();
    window.dispatchEvent(new Event('pf:unauthorized'));
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
  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Descarga un PDF (informes, AMP-02). Va por `fetch` y no por un `<a href>` porque la API exige
 * el token en la cabecera `Authorization`. */
export async function downloadPdf(path: string, filename: string): Promise<void> {
  const blob = await (await send(path)).blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const downloadExecutiveReport = (assessmentId: string) =>
  downloadPdf(`/assessments/${assessmentId}/report.pdf`, `informe-ejecutivo-${assessmentId.slice(0, 8)}.pdf`);

export const downloadComparisonReport = (idA: string, idB: string) =>
  downloadPdf(
    `/assessments/${idA}/compare/${idB}/report.pdf`,
    `comparacion-${idA.slice(0, 8)}-${idB.slice(0, 8)}.pdf`
  );

function json(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

// --- Metodologia -----------------------------------------------------------------------

export const getMethodology = () => request<MethodologyCatalog>('/methodology');

// --- Sesión ------------------------------------------------------------------------------

export interface AuthUser {
  id: string;
  username: string;
  org_id: string;
  org_nombre: string;
  role: string;
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const result = await request<{ token: string; user: AuthUser }>(
    '/auth/login',
    json({ username, password })
  );
  setToken(result.token);
  return result.user;
}

export const getMe = () => request<AuthUser>('/auth/me');

export function logout(): void {
  clearToken();
}

// --- Organizaciones ----------------------------------------------------------------------

export const listOrgIncidents = (orgId: string) =>
  request<IncidentOut[]>(`/orgs/${orgId}/incidents`);

/** Orígenes de eventos de la organización: la evaluación elige cuáles consume (docs/09 §98). */
export const listEventSources = (orgId: string, scope?: string) =>
  request<EventSourceOut[]>(
    `/orgs/${orgId}/event-sources${scope ? `?scope=${encodeURIComponent(scope)}` : ''}`
  );

export const ingestEvents = (orgId: string, file: File) => {
  const form = new FormData();
  form.append('file', file);
  return request<EventsAccepted>(`/orgs/${orgId}/events?confirm_live_ai=true`, {
    method: 'POST',
    body: form,
  });
};

// --- Incidentes ----------------------------------------------------------------------------

/** Borra eventos, patrones e incidentes de la organización: los logs de ejemplo empiezan de cero. */
export const clearOrgEvents = (orgId: string) =>
  request<{ eventos: number; patrones: number; incidentes: number; planes: number }>(
    `/orgs/${orgId}/events`,
    { method: 'DELETE' }
  );

/** Cambia el estado del incidente. Cerrar exige `motivo` (OP-11). */
export const updateIncident = (incidentId: string, estado: string, motivo?: string) =>
  request<IncidentOut>(`/incidents/${incidentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ estado, motivo }),
  });

export const getIncidentPlans = (incidentId: string) =>
  request<Plan[]>(`/incidents/${incidentId}/plans`);

// --- Assessments ---------------------------------------------------------------------------

export interface CreateAssessmentInput {
  scope?: string;
  terraformFiles?: File[];
  ansibleFiles?: File[];
  documentFiles?: File[];
  /** Orígenes de eventos a consumir; `undefined` = todos los del org+scope, `[]` = ninguno. */
  eventSourceIds?: string[];
}

export const createAssessment = (input: CreateAssessmentInput) => {
  // La organizacion sale de la sesion (doc 10): no se manda org_name.
  const form = new FormData();
  form.append('scope', input.scope ?? 'entorno:produccion');
  form.append('ai_adjust', 'true');
  form.append('use_ai_for_documents', String((input.documentFiles?.length ?? 0) > 0));
  form.append('confirm_live_ai', 'true');
  if (input.eventSourceIds !== undefined) {
    form.append('event_source_ids', JSON.stringify(input.eventSourceIds));
  }
  for (const f of input.terraformFiles ?? []) form.append('terraform_files', f);
  for (const f of input.ansibleFiles ?? []) form.append('ansible_files', f);
  for (const f of input.documentFiles ?? []) form.append('document_files', f);
  return request<AssessmentAccepted>('/assessments', { method: 'POST', body: form });
};

export const listAssessments = () => request<AssessmentDetail[]>('/assessments');

export const getAssessment = (id: string) => request<AssessmentDetail>(`/assessments/${id}`);

export const getCriteria = (id: string) =>
  request<CriterionResult[]>(`/assessments/${id}/criteria`);

export const getFindings = (id: string) => request<Finding[]>(`/assessments/${id}/findings`);

export const getPlans = (id: string) => request<Plan[]>(`/assessments/${id}/plans`);

export const updatePlanEstado = (assessmentId: string, planId: string, estado: PlanEstado) =>
  request<Plan>(`/assessments/${assessmentId}/plans/${planId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ estado }),
  });

export const createPlans = (id: string) =>
  request<Plan[]>(`/assessments/${id}/plans?use_ai=true&confirm_live_ai=true`, { method: 'POST' });

export const compareAssessments = (idA: string, idB: string) =>
  request<ComparisonOut>(`/assessments/${idA}/compare/${idB}`);

// --- Jobs (POST /assessments, /assessments/{id}/reevaluate y /orgs/{id}/events son
// asincronicos: devuelven un job_id que hay que sondear -- ver docs/09 §16) -------------------

export const listJobs = (filters: { estado?: JobEstado; tipo?: string; limit?: number } = {}) => {
  const params = new URLSearchParams();
  if (filters.estado) params.set('estado', filters.estado);
  if (filters.tipo) params.set('tipo', filters.tipo);
  if (filters.limit) params.set('limit', String(filters.limit));
  const qs = params.toString();
  return request<JobOut[]>(`/jobs${qs ? `?${qs}` : ''}`);
};

export const retryJob = (jobId: string) =>
  request<JobOut>(`/jobs/${jobId}/retry?confirm_live_ai=true`, {
    method: 'POST',
  });

export const getJob = (jobId: string, signal?: AbortSignal) =>
  request<JobOut>(`/jobs/${jobId}`, signal ? { signal } : undefined);

const TERMINAL_JOB_STATES: JobOut['estado'][] = ['completado', 'fallido'];

export class JobTimeoutError extends Error {}

export function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === 'AbortError';
}

/** `true` si el error es un `AbortError` (p. ej. lanzado por `AbortSignal.abort()`). */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/** Sondea `GET /jobs/{id}` hasta que el job termine (completado o fallido). `onTick` se llama
 * en cada lectura, incluida la final, para que la UI pueda mostrar progreso en vivo.
 *
 * Tiene **timeout** (por defecto 180 s) y acepta un `AbortSignal`: sin esto, un job que nunca
 * llega a estado terminal (p. ej. el stack sin `worker-core`, que lo deja `pendiente`) colgaba al
 * cliente para siempre. Lanza `JobTimeoutError` al agotarse el tiempo. */
export async function pollJob(
  jobId: string,
  opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal; onTick?: (job: JobOut) => void } = {}
): Promise<JobOut> {
  const intervalMs = opts.intervalMs ?? 800;
  const timeoutMs = opts.timeoutMs ?? 180_000;
  const startedAt = Date.now();
  while (true) {
    if (opts.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const job = await getJob(jobId, opts.signal);
    opts.onTick?.(job);
    if (TERMINAL_JOB_STATES.includes(job.estado)) return job;
    if (Date.now() - startedAt > timeoutMs) {
      throw new JobTimeoutError(
        `El job ${jobId} sigue en "${job.estado}" tras ${Math.round(timeoutMs / 1000)}s. ` +
          'Revisa que worker-core/worker-logs estén corriendo, o vuelve a intentarlo.'
      );
    }
    await sleep(intervalMs, opts.signal);
  }
}
