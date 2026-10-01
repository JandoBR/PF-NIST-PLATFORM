import { useState } from 'react';
import {
  Brain,
  Sparkles,
  Route,
  ListChecks,
  AlertTriangle,
  Loader2,
  ShieldAlert,
  CheckCircle2,
  Link2,
} from 'lucide-react';
import { ApiError, createPlans } from '@/lib/api';
import type { Finding, Plan } from '@/lib/types';
import { SEVERITY_META } from '@/lib/ui';

type View = 'findings' | 'plan';

interface Props {
  assessmentId: string;
  findings: Finding[];
  plans: Plan[];
  onPlansUpdated: (plans: Plan[]) => void;
}

export function RecommendationEngine({ assessmentId, findings, plans, onPlansUpdated }: Props) {
  const [view, setView] = useState<View>('findings');
  const [priorityFilter, setPriorityFilter] = useState<string>('all');
  const [generating, setGenerating] = useState<'plantilla' | 'ia' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsConfirm, setNeedsConfirm] = useState(false);

  async function handleGenerate(useAi: boolean, confirmLiveAi = false) {
    setGenerating(useAi ? 'ia' : 'plantilla');
    setError(null);
    try {
      const updated = await createPlans(assessmentId, { useAi, confirmLiveAi });
      onPlansUpdated(updated);
      setNeedsConfirm(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNeedsConfirm(true);
        setError(err.detail);
      } else {
        setError(err instanceof Error ? err.message : 'Error desconocido.');
      }
    } finally {
      setGenerating(null);
    }
  }

  const roadmap = plans.filter((p) => priorityFilter === 'all' || p.prioridad === priorityFilter);
  const priorityOrder = ['alta', 'media', 'baja'];

  return (
    <div className="space-y-6">
      <div className="card p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500/15 to-indigo-500/15 ring-1 ring-cyan-500/20">
              <Brain className="h-5 w-5 text-cyan-300" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Motor de Recomendaciones</h3>
              <p className="text-xs text-slate-500">
                {findings.length} hallazgo{findings.length === 1 ? '' : 's'} por debajo del umbral · {plans.length}{' '}
                plan{plans.length === 1 ? '' : 'es'} generado{plans.length === 1 ? '' : 's'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-white/[0.06] bg-ink-900/60 p-1">
              <ToggleBtn active={view === 'findings'} onClick={() => setView('findings')}>
                <ListChecks className="h-3.5 w-3.5" />
                Hallazgos
              </ToggleBtn>
              <ToggleBtn active={view === 'plan'} onClick={() => setView('plan')}>
                <Route className="h-3.5 w-3.5" />
                Plan de Acción
              </ToggleBtn>
            </div>
          </div>
        </div>

        {findings.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-4">
            <button
              onClick={() => handleGenerate(false)}
              disabled={generating !== null}
              className="btn-ghost border border-white/[0.06] text-xs"
            >
              {generating === 'plantilla' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Route className="h-3.5 w-3.5" />
              )}
              {plans.length > 0 ? 'Regenerar plan (plantilla)' : 'Generar plan (plantilla)'}
            </button>
            <button
              onClick={() => handleGenerate(true)}
              disabled={generating !== null}
              className="btn-ghost border border-cyan-500/20 text-xs text-cyan-300 hover:text-cyan-200"
            >
              {generating === 'ia' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              Generar plan con IA
            </button>
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/[0.07] p-3.5 text-xs text-amber-200">
            <div className="mb-1 flex items-center gap-2 font-medium">
              <AlertTriangle className="h-3.5 w-3.5" />
              {needsConfirm ? 'Confirmación requerida' : 'No se pudo generar el plan'}
            </div>
            <p className="whitespace-pre-line leading-relaxed">{error}</p>
            {needsConfirm && (
              <button
                onClick={() => handleGenerate(true, true)}
                disabled={generating !== null}
                className="btn-primary mt-2 text-xs"
              >
                Confirmar llamadas reales a IA y reintentar
              </button>
            )}
          </div>
        )}
      </div>

      {view === 'findings' ? (
        <FindingsList findings={findings} />
      ) : plans.length === 0 ? (
        <div className="card px-5 py-12 text-center text-sm text-slate-500">
          Aún no hay un plan generado. Usa los botones de arriba.
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex items-center gap-1.5 text-xs text-slate-500">
              <ListChecks className="h-3.5 w-3.5" /> Filtrar:
            </span>
            {['all', 'alta', 'media', 'baja'].map((p) => (
              <button
                key={p}
                onClick={() => setPriorityFilter(p)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  priorityFilter === p ? 'bg-white/[0.08] text-white' : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-300'
                }`}
              >
                {p === 'all' ? 'Todas' : SEVERITY_META[p as keyof typeof SEVERITY_META].label}
              </button>
            ))}
          </div>

          {roadmap.length === 0 ? (
            <div className="card px-5 py-12 text-center text-sm text-slate-500">
              No hay planes en este nivel de prioridad.
            </div>
          ) : (
            roadmap
              .sort((a, b) => priorityOrder.indexOf(a.prioridad) - priorityOrder.indexOf(b.prioridad))
              .map((p, i) => <PlanCard key={p.criterion_id} plan={p} index={i + 1} />)
          )}
        </div>
      )}
    </div>
  );
}

function FindingsList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return (
      <div className="card flex flex-col items-center justify-center px-6 py-16 text-center">
        <CheckCircle2 className="mb-3 h-10 w-10 text-emerald-400" />
        <h3 className="text-sm font-semibold text-slate-200">Sin hallazgos</h3>
        <p className="mt-1 max-w-sm text-xs text-slate-500">
          Ningún criterio evaluado quedó por debajo del umbral de brecha configurado.
        </p>
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="divide-y divide-white/[0.04]">
        {findings.map((f) => {
          const meta = SEVERITY_META[f.severidad];
          return (
            <div key={f.criterion_id} className="flex items-center gap-4 px-5 py-3.5">
              <ShieldAlert className="h-4 w-4 flex-shrink-0 text-slate-500" />
              <span className="flex-shrink-0 font-mono text-xs font-semibold text-slate-300">{f.criterion_id}</span>
              <span className="min-w-0 flex-1 truncate text-sm text-slate-300">{f.titulo}</span>
              <span className="flex items-center gap-1 text-xs text-slate-500">
                <Link2 className="h-3 w-3" /> {f.evidence_ids.length}
              </span>
              <span className="w-10 flex-shrink-0 text-right text-xs font-semibold text-slate-400">
                {Math.round(f.score)}
              </span>
              <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PlanCard({ plan, index }: { plan: Plan; index: number }) {
  const meta = SEVERITY_META[plan.prioridad as keyof typeof SEVERITY_META] ?? SEVERITY_META.media;
  const isAi = plan.generado_por.startsWith('ai:');
  return (
    <div className="card card-hover animate-slide-up p-5" style={{ animationDelay: `${index * 40}ms` }}>
      <div className="flex items-start gap-4">
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-white/[0.04] text-sm font-bold text-slate-400">
          {index}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
            <span className="font-mono text-xs text-slate-600">{plan.criterion_id}</span>
            <span
              className={`chip border text-xs ${
                isAi ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300' : 'border-white/10 bg-white/[0.04] text-slate-400'
              }`}
            >
              {isAi ? 'Generado por IA' : 'Plantilla'}
            </span>
          </div>
          <h4 className="mt-2 text-sm font-semibold text-white">{plan.titulo}</h4>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">{plan.objetivo}</p>

          {plan.pasos.length > 0 && (
            <ol className="mt-3 space-y-1.5">
              {plan.pasos.map((paso, i) => (
                <li key={i} className="flex gap-2 text-sm text-slate-300">
                  <span className="text-slate-600">{i + 1}.</span>
                  {paso}
                </li>
              ))}
            </ol>
          )}

          <div className="mt-3 rounded-lg border border-white/[0.04] bg-ink-900/40 p-3 text-xs text-slate-500">
            <span className="font-semibold text-slate-400">Verificación: </span>
            {plan.verificacion}
          </div>

          {plan.dependencias.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {plan.dependencias.map((d) => (
                <span key={d} className="chip border border-white/10 bg-white/[0.03] text-slate-500">
                  {d}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ToggleBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
        active ? 'bg-white/[0.08] text-white' : 'text-slate-500 hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  );
}
