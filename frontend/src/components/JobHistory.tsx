import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowLeft, ExternalLink, Loader2, RefreshCw, RotateCcw } from 'lucide-react';
import { listJobs, retryJob } from '@/lib/api';
import type { JobEstado, JobOut } from '@/lib/types';
import { JOB_ESTADO_META, JOB_TIPO_LABEL } from '@/lib/ui';

interface Props {
  onClose: () => void;
  /** Abre la evaluación ligada a un job (solo si ya está en el historial de evaluaciones). */
  onOpenAssessment: (assessmentId: string) => void;
  openableIds: Set<string>;
}

const POLL_MS = 3000;
const ACTIVE: JobEstado[] = ['pendiente', 'en_progreso'];

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('es');
}

/** Historial de actividad en segundo plano (evaluaciones e ingestas de eventos): qué corrió, en qué
 * estado quedó y por qué falló (FN-01). Se refresca solo mientras haya jobs activos. */
export function JobHistory({ onClose, onOpenAssessment, openableIds }: Props) {
  const [jobs, setJobs] = useState<JobOut[] | null>(null);
  const [estado, setEstado] = useState<JobEstado | 'all'>('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setJobs(await listJobs(estado === 'all' ? {} : { estado }));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo cargar la actividad.');
    } finally {
      setLoading(false);
    }
  }, [estado]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRetry(job: JobOut) {
    if (
      job.usa_ia &&
      !window.confirm(
        'Reintentar volverá a llamar a la IA real y puede generar costo. ¿Quieres continuar?'
      )
    )
      return;
    setRetrying(job.id);
    try {
      await retryJob(job.id, job.usa_ia);
      setError(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo reintentar el trabajo.');
    } finally {
      setRetrying(null);
    }
  }

  const hasActive = jobs?.some((j) => ACTIVE.includes(j.estado)) ?? false;
  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [hasActive, load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <button
            onClick={onClose}
            className="mb-1 flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
          >
            <ArrowLeft className="h-3 w-3" /> Volver
          </button>
          <h2 className="text-base font-semibold text-white">Actividad</h2>
          <p className="text-xs text-slate-500">
            Evaluaciones e ingestas de eventos que corren en segundo plano.
            {hasActive && ' Se actualiza sola mientras haya algo en curso.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={estado}
            onChange={(e) => setEstado(e.target.value as JobEstado | 'all')}
            className="input w-auto"
            aria-label="Filtrar por estado"
          >
            <option value="all">Todos</option>
            {(Object.keys(JOB_ESTADO_META) as JobEstado[]).map((e) => (
              <option key={e} value={e}>
                {JOB_ESTADO_META[e].label}
              </option>
            ))}
          </select>
          <button onClick={() => void load()} disabled={loading} className="btn-ghost" title="Actualizar">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {error && (
        <p className="flex items-center gap-1.5 text-xs text-rose-300">
          <AlertTriangle className="h-3.5 w-3.5" /> {error}
        </p>
      )}

      <div className="card overflow-hidden">
        {jobs === null ? (
          <div className="px-5 py-12 text-center text-sm text-slate-500">Cargando…</div>
        ) : jobs.length === 0 ? (
          <div className="px-5 py-12 text-center text-sm text-slate-500">
            No hay actividad{estado !== 'all' ? ' con ese estado' : ''}.
          </div>
        ) : (
          <div className="divide-y divide-white/[0.04]">
            {jobs.map((job) => {
              const meta = JOB_ESTADO_META[job.estado];
              return (
                <div key={job.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-5 py-3">
                  <div className="min-w-[150px] text-xs text-slate-400">{formatWhen(job.creado_en)}</div>
                  <div className="min-w-[130px] text-sm text-slate-200">
                    {JOB_TIPO_LABEL[job.tipo] ?? job.tipo}
                  </div>
                  <span
                    className={`rounded-md border px-2 py-0.5 text-xs font-medium ${meta.text} ${meta.bg} ${meta.border}`}
                  >
                    {meta.label}
                    {job.estado === 'en_progreso' ? ` · ${job.progreso}%` : ''}
                  </span>
                  <div className="min-w-0 flex-1 text-xs text-rose-300">{job.error}</div>
                  {job.reintentable && (
                    <button
                      onClick={() => void handleRetry(job)}
                      disabled={retrying === job.id}
                      className="flex items-center gap-1 text-xs text-amber-300 hover:text-amber-200 disabled:opacity-50"
                    >
                      {retrying === job.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3 w-3" />
                      )}
                      Reintentar
                    </button>
                  )}
                  {job.assessment_id && job.estado === 'completado' && openableIds.has(job.assessment_id) && (
                    <button
                      onClick={() => onOpenAssessment(job.assessment_id as string)}
                      className="flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200"
                    >
                      Abrir evaluación <ExternalLink className="h-3 w-3" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
