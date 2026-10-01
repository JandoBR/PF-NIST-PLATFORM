import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  ShieldAlert,
  Radio,
  ArrowRight,
  Clock,
  X,
  CheckCircle2,
  UploadCloud,
  Loader2,
  AlertTriangle,
  Route,
  Stethoscope,
  FlaskConical,
  Info,
} from 'lucide-react';
import { DEMO_EVENT_LOGS, fetchAsFile } from '@/data/demo';
import { ApiError, getIncidentPlans, ingestEvents, listOrgIncidents, pollJob } from '@/lib/api';
import type { IncidentOut, JobEstado, Plan } from '@/lib/types';
import { incidentSeverityMeta } from '@/lib/ui';

interface Props {
  orgId: string | null;
  orgNombre: string | null;
}

export function ThreatSimulation({ orgId, orgNombre }: Props) {
  const [incidents, setIncidents] = useState<IncidentOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [jobEstado, setJobEstado] = useState<JobEstado | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastIngest, setLastIngest] = useState<string | null>(null);
  const [selected, setSelected] = useState<IncidentOut | null>(null);

  const refresh = useCallback(async () => {
    if (!orgId) return [] as IncidentOut[];
    setLoading(true);
    try {
      const fetched = await listOrgIncidents(orgId);
      setIncidents(fetched);
      return fetched;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error desconocido.');
      return [] as IncidentOut[];
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleIngest(file: File) {
    if (!orgId) return;
    setIngesting(true);
    setError(null);
    setLastIngest(null);
    setJobEstado(null);
    const before = incidents.length;
    try {
      // POST /orgs/{id}/events encola en worker-logs y devuelve de inmediato (docs/09 §16):
      // hay que sondear el job, y luego refrescar la lista -- ya no hay un payload sincronico
      // con "nuevos vs actualizados", asi que se aproxima comparando el total antes/despues.
      const accepted = await ingestEvents(orgId, file);
      const job = await pollJob(accepted.job_id, { onTick: (j) => setJobEstado(j.estado) });

      if (job.estado === 'fallido') {
        setError(job.error ?? 'La ingesta de eventos falló en el worker, sin más detalle.');
        return;
      }

      const after = await refresh();
      const nuevos = Math.max(0, after.length - before);
      setLastIngest(
        nuevos > 0
          ? `Eventos procesados · ${nuevos} incidente(s) nuevo(s) · ${after.length} en total`
          : `Eventos procesados · sin incidentes nuevos · ${after.length} en total`
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : err instanceof Error ? err.message : 'Error desconocido.');
    } finally {
      setIngesting(false);
    }
  }

  if (!orgId) {
    return (
      <div className="card flex flex-col items-center justify-center px-6 py-20 text-center">
        <Radio className="mb-4 h-12 w-12 text-slate-700" />
        <h2 className="text-lg font-semibold text-slate-300">Ninguna organización activa</h2>
        <p className="mt-1 max-w-sm text-sm text-slate-500">
          Crea una evaluación primero: los incidentes se asocian a la organización que se crea en ese paso.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Ingesta de eventos */}
      <div className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 ring-1 ring-emerald-500/20">
              <Radio className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Ingesta de Eventos · {orgNombre}</h3>
              <p className="text-xs text-slate-500">Los disparadores deterministas (D1/D3/D4/D5) abren o actualizan incidentes.</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {DEMO_EVENT_LOGS.map((log) => (
              <button
                key={log.id}
                title={log.description}
                disabled={ingesting}
                onClick={async () => handleIngest(await fetchAsFile(log.file))}
                className="btn-ghost border border-white/[0.06] text-xs"
              >
                {ingesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UploadCloud className="h-3.5 w-3.5" />}
                {log.label}
              </button>
            ))}
            <label className="btn-ghost cursor-pointer border border-white/[0.06] text-xs">
              <UploadCloud className="h-3.5 w-3.5" />
              Subir .jsonl
              <input
                type="file"
                accept=".jsonl"
                className="hidden"
                disabled={ingesting}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleIngest(file);
                  e.target.value = '';
                }}
              />
            </label>
          </div>
        </div>
        {ingesting && jobEstado && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {jobEstado === 'pendiente' ? 'En cola…' : 'Procesando eventos…'}
          </p>
        )}
        {lastIngest && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" /> {lastIngest}
          </p>
        )}
        {error && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-rose-300">
            <AlertTriangle className="h-3.5 w-3.5" /> {error}
          </p>
        )}
      </div>

      {/* Registro de incidentes */}
      <div className="card overflow-hidden">
        <div className="flex items-center gap-2 border-b border-white/[0.06] px-5 py-3.5">
          <Activity className="h-4 w-4 text-slate-500" />
          <h3 className="text-sm font-semibold text-white">Incidentes</h3>
          <span className="ml-auto text-xs text-slate-500">
            {loading ? 'Cargando…' : `${incidents.length} incidente(s)`}
          </span>
        </div>
        {incidents.length === 0 && !loading ? (
          <div className="px-5 py-12 text-center text-sm text-slate-500">
            Sin incidentes todavía. Ingiere un log de eventos arriba.
          </div>
        ) : (
          <div className="divide-y divide-white/[0.04]">
            {incidents.map((incident) => {
              const meta = incidentSeverityMeta(incident.severidad);
              return (
                <button
                  key={incident.id}
                  onClick={() => setSelected(incident)}
                  className="group flex w-full items-center gap-4 px-5 py-3.5 text-left transition-colors hover:bg-white/[0.02]"
                >
                  <span className="font-mono text-xs text-slate-600">
                    {new Date(incident.last_event_time).toLocaleString()}
                  </span>
                  <span className={`h-2 w-2 flex-shrink-0 rounded-full ${meta.dot}`} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-200">{incident.titulo}</p>
                    <p className="truncate text-xs text-slate-500">
                      {incident.estado} · {incident.criterios.join(', ')}
                    </p>
                  </div>
                  <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
                  <ArrowRight className="h-4 w-4 flex-shrink-0 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-slate-400" />
                </button>
              );
            })}
          </div>
        )}
      </div>

      {selected && <IncidentDrawer incident={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function IncidentDrawer({ incident, onClose }: { incident: IncidentOut; onClose: () => void }) {
  const meta = incidentSeverityMeta(incident.severidad);
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());

  useEffect(() => {
    let active = true;
    getIncidentPlans(incident.id)
      .then((p) => active && setPlans(p))
      .catch(() => active && setPlans([]));
    return () => {
      active = false;
    };
  }, [incident.id]);

  const toggle = (key: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });

  const totalSteps = (plans ?? []).reduce((n, p) => n + p.pasos.length, 0);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm animate-fade-in" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-lg animate-slide-up flex-col border-l border-white/[0.08] bg-ink-900 shadow-2xl">
        <div className="flex items-start justify-between border-b border-white/[0.06] p-5">
          <div className="flex items-start gap-3">
            <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${meta.bg} ring-1 ${meta.border}`}>
              <ShieldAlert className="h-5 w-5 text-rose-300" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">{incident.titulo}</h3>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
                <span className="flex items-center gap-1 text-xs text-slate-500">
                  <Clock className="h-3 w-3" /> {new Date(incident.last_event_time).toLocaleString()}
                </span>
              </div>
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <div className="rounded-lg border border-white/[0.06] bg-ink-850/60 p-4">
            <p className="text-xs font-medium text-slate-500">Correlation key</p>
            <p className="mt-1 font-mono text-xs text-slate-400">{incident.correlation_key}</p>
            <p className="mt-3 text-xs font-medium text-slate-500">Criterios afectados</p>
            <p className="mt-1 text-sm text-slate-300">{incident.criterios.join(', ')}</p>
          </div>

          <div className="mt-5">
            <h4 className="mb-3 text-sm font-semibold text-white">Línea de Tiempo</h4>
            <div className="space-y-2.5">
              {incident.timeline.map((entry, i) => (
                <div key={i} className="rounded-lg border border-white/[0.06] bg-ink-850/40 p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-cyan-300">{String(entry.disparador ?? '')}</span>
                    <span className="text-xs text-slate-500">
                      {entry.momento ? new Date(String(entry.momento)).toLocaleString() : ''}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-slate-300">{String(entry.titulo ?? '')}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-5">
            <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
              <Route className="h-4 w-4 text-cyan-400" /> Plan de Respuesta
            </h4>
            {plans === null ? (
              <p className="text-xs text-slate-500">Cargando…</p>
            ) : plans.length === 0 ? (
              <p className="text-xs text-slate-500">Sin plan generado para este incidente.</p>
            ) : (
              <div className="space-y-5">
                {plans.map((plan) => (
                  <div key={plan.criterion_id} className="rounded-lg border border-white/[0.06] bg-ink-850/40 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <h5 className="text-sm font-semibold text-slate-100">{plan.titulo}</h5>
                      <span className="font-mono text-[11px] text-slate-600">{plan.criterion_id}</span>
                    </div>

                    {plan.advertencia && (
                      <p className="mt-2 flex items-start gap-1.5 rounded-md border border-amber-500/20 bg-amber-500/[0.06] px-2.5 py-1.5 text-xs text-amber-200">
                        <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                        {plan.advertencia}
                      </p>
                    )}

                    {plan.diagnostico_observable && (
                      <p className="mt-3 flex items-start gap-1.5 text-xs text-slate-400">
                        <Stethoscope className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-slate-500" />
                        <span>
                          <span className="font-medium text-slate-300">Diagnóstico observable: </span>
                          {plan.diagnostico_observable}
                        </span>
                      </p>
                    )}

                    {plan.hipotesis.length > 0 && (
                      <ul className="mt-2 space-y-1 pl-5 text-xs text-slate-400">
                        {plan.hipotesis.map((h, i) => (
                          <li key={i} className="list-disc">
                            {h}
                          </li>
                        ))}
                      </ul>
                    )}

                    {plan.comprobaciones_seguras.length > 0 && (
                      <div className="mt-3">
                        <p className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
                          <FlaskConical className="h-3.5 w-3.5 text-cyan-400" /> Comprobaciones seguras
                        </p>
                        <ul className="mt-1 space-y-1 pl-5 text-xs text-slate-400">
                          {plan.comprobaciones_seguras.map((c, i) => (
                            <li key={i} className="list-disc">
                              {c}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {plan.pasos.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {plan.pasos.map((paso, i) => {
                          const key = `${plan.criterion_id}-${i}`;
                          const done = checked.has(key);
                          return (
                            <button
                              key={key}
                              onClick={() => toggle(key)}
                              className={`flex w-full items-start gap-3 rounded-lg border p-2.5 text-left transition-all ${
                                done ? 'border-emerald-500/20 bg-emerald-500/[0.04]' : 'border-white/[0.06] bg-ink-900/40 hover:border-white/15'
                              }`}
                            >
                              <div
                                className={`mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-md border transition-colors ${
                                  done ? 'border-emerald-500/40 bg-emerald-500/15' : 'border-white/15'
                                }`}
                              >
                                {done && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                              </div>
                              <p className={`text-sm leading-relaxed ${done ? 'text-slate-500 line-through' : 'text-slate-300'}`}>
                                {paso}
                              </p>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-white/[0.06] p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">
              {checked.size} de {totalSteps} pasos completados
            </span>
            <button onClick={onClose} className="btn-ghost border border-white/[0.06]">
              Cerrar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
