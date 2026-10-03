import { useMemo, useState } from 'react';
import {
  Brain,
  Sparkles,
  ListChecks,
  AlertTriangle,
  Loader2,
  ShieldAlert,
  CheckCircle2,
  Link2,
  ChevronRight,
  Info,
} from 'lucide-react';
import { ApiError, createPlans, updatePlanEstado } from '@/lib/api';
import type { Finding, Plan, PlanEstado } from '@/lib/types';
import { PLAN_ESTADOS, PLAN_ESTADO_META, SEVERITY_META } from '@/lib/ui';

interface Props {
  assessmentId: string;
  findings: Finding[];
  plans: Plan[];
  onPlansUpdated: (plans: Plan[]) => void;
}

const SEVERITY_ORDER: Finding['severidad'][] = ['alta', 'media', 'baja'];

export function RecommendationEngine({
  assessmentId,
  findings: allFindings,
  plans,
  onPlansUpdated,
}: Props) {
  // Las contradicciones (docs/02 §5) y las limitaciones (OP-04) no puntúan ni generan plan: se
  // muestran aparte de las brechas.
  const findings = useMemo(() => allFindings.filter((f) => f.tipo === 'brecha'), [allFindings]);
  const contradictions = useMemo(
    () => allFindings.filter((f) => f.tipo === 'contradiccion'),
    [allFindings]
  );
  const limitations = useMemo(() => allFindings.filter((f) => f.tipo === 'limitacion'), [allFindings]);
  const [priorityFilter, setPriorityFilter] = useState<string>('all');
  const [generating, setGenerating] = useState<'plantilla' | 'ia' | null>(null);
  const [savingPlan, setSavingPlan] = useState<string | null>(null);
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

  async function setEstado(plan: Plan, estado: PlanEstado) {
    setSavingPlan(plan.id);
    setError(null);
    try {
      const updated = await updatePlanEstado(assessmentId, plan.id, estado);
      onPlansUpdated(plans.map((p) => (p.id === updated.id ? updated : p)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo actualizar el seguimiento.');
    } finally {
      setSavingPlan(null);
    }
  }

  const hasPlans = plans.length > 0;
  const done = plans.filter((p) => p.estado === 'hecho').length;

  const orderedFindings = useMemo(
    () =>
      [...findings].sort(
        (a, b) => SEVERITY_ORDER.indexOf(a.severidad) - SEVERITY_ORDER.indexOf(b.severidad)
      ),
    [findings]
  );

  const visibleFindings =
    priorityFilter === 'all'
      ? orderedFindings
      : orderedFindings.filter((f) => f.severidad === priorityFilter);

  return (
    <div className="space-y-6">
      {contradictions.length > 0 && <ContradictionsCard items={contradictions} />}
      {limitations.length > 0 && <LimitationsCard items={limitations} />}
      <div className="card p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500/15 to-indigo-500/15 ring-1 ring-cyan-500/20">
              <Brain className="h-5 w-5 text-cyan-300" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Motor de Recomendaciones</h3>
              <p className="text-xs text-slate-500">
                {findings.length} hallazgo{findings.length === 1 ? '' : 's'} por debajo del umbral · {done} de{' '}
                {plans.length} plan{plans.length === 1 ? '' : 'es'} marcado{done === 1 ? '' : 's'} como hecho
              </p>
            </div>
          </div>
        </div>

        {findings.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-white/[0.06] pt-4">
            <button
              onClick={() => handleGenerate(true)}
              disabled={generating !== null}
              className="btn-ghost border border-cyan-500/20 text-xs text-cyan-300 hover:text-cyan-200"
              title="Recalcula el plan con la capa de IA (requiere DEEPSEEK_API_KEY configurada)."
            >
              {generating === 'ia' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              {hasPlans ? 'Regenerar con IA' : 'Generar plan con IA'}
            </button>
            <span className="text-xs text-slate-600">
              El plan se genera automáticamente desde la plantilla determinista; con IA se recalcula.
            </span>
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/[0.07] p-3.5 text-xs text-amber-200">
            <div className="mb-1 flex items-center gap-2 font-medium">
              <AlertTriangle className="h-3.5 w-3.5" />
              {needsConfirm ? 'Confirmación requerida' : 'No se pudo completar la acción'}
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

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs text-slate-500">
            <ListChecks className="h-3.5 w-3.5" /> Prioridad:
          </span>
          {['all', 'alta', 'media', 'baja'].map((p) => (
            <button
              key={p}
              onClick={() => setPriorityFilter(p)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                priorityFilter === p
                  ? 'bg-white/[0.08] text-white'
                  : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-300'
              }`}
            >
              {p === 'all' ? 'Todas' : SEVERITY_META[p as keyof typeof SEVERITY_META].label}
            </button>
          ))}
          <span className="ml-auto text-xs text-slate-600">
            {visibleFindings.length} de {findings.length} hallazgo(s)
          </span>
        </div>

        <FindingsList
          findings={visibleFindings}
          plans={plans}
          savingPlan={savingPlan}
          onSetEstado={setEstado}
        />
      </div>
    </div>
  );
}

function FindingsList({
  findings,
  plans,
  savingPlan,
  onSetEstado,
}: {
  findings: Finding[];
  plans: Plan[];
  savingPlan: string | null;
  onSetEstado: (plan: Plan, estado: PlanEstado) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const planByCriterion = new Map(plans.map((p) => [p.criterion_id, p]));

  if (findings.length === 0) {
    return (
      <div className="card flex flex-col items-center justify-center px-6 py-16 text-center">
        <CheckCircle2 className="mb-3 h-10 w-10 text-emerald-400" />
        <h3 className="text-sm font-semibold text-slate-200">Sin hallazgos</h3>
        <p className="mt-1 max-w-sm text-xs text-slate-500">
          Ningún criterio coincide con este nivel de prioridad, o no quedó ninguno por debajo del umbral.
        </p>
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="divide-y divide-white/[0.04]">
        {findings.map((f) => {
          const meta = SEVERITY_META[f.severidad];
          const open = expanded === f.criterion_id;
          const plan = planByCriterion.get(f.criterion_id);
          const planMeta = plan ? PLAN_ESTADO_META[plan.estado] : null;
          return (
            <div key={f.criterion_id}>
              <button
                onClick={() => setExpanded(open ? null : f.criterion_id)}
                className="flex w-full items-center gap-4 px-5 py-3.5 text-left transition-colors hover:bg-white/[0.02]"
              >
                <ChevronRight
                  className={`h-4 w-4 flex-shrink-0 text-slate-600 transition-transform ${open ? 'rotate-90' : ''}`}
                />
                <ShieldAlert className="h-4 w-4 flex-shrink-0 text-slate-500" />
                <span className="flex-shrink-0 font-mono text-xs font-semibold text-slate-300">{f.criterion_id}</span>
                <span className="min-w-0 flex-1 truncate text-sm text-slate-300">{f.titulo}</span>
                {plan && planMeta && plan.estado !== 'pendiente' && (
                  <span className={`chip hidden border sm:inline-flex ${planMeta.bg} ${planMeta.text} ${planMeta.border}`}>
                    {planMeta.label}
                  </span>
                )}
                <span className="flex items-center gap-1 text-xs text-slate-500">
                  <Link2 className="h-3 w-3" /> {f.evidence_ids.length}
                </span>
                <span className="w-10 flex-shrink-0 text-right text-xs font-semibold text-slate-400">
                  {f.score != null ? Math.round(f.score) : '—'}
                </span>
                <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
              </button>

              {open && (
                <div className="animate-fade-in border-t border-white/[0.04] bg-ink-900/30 px-5 py-4 pl-14">
                  {plan ? (
                    <PlanBody
                      plan={plan}
                      saving={savingPlan === plan.id}
                      onSetEstado={onSetEstado}
                    />
                  ) : (
                    <p className="text-xs text-slate-500">
                      Este hallazgo no tiene plan: la evaluación es anterior a la generación automática.
                      Reevalúa para generarlo.
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Cuerpo de un plan, desplegado inline bajo el hallazgo (docs/11 UI-04) con su seguimiento. */
function PlanBody({
  plan,
  saving,
  onSetEstado,
}: {
  plan: Plan;
  saving: boolean;
  onSetEstado: (plan: Plan, estado: PlanEstado) => void;
}) {
  const meta = SEVERITY_META[plan.prioridad as keyof typeof SEVERITY_META] ?? SEVERITY_META.media;
  const isAi = plan.generado_por.startsWith('ai:');
  return (
    <div>
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

      {/* Seguimiento del plan (docs/05 §4.4): informativo, NO cambia el puntaje del criterio. */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-3">
        <span className="text-xs text-slate-500">Seguimiento:</span>
        {PLAN_ESTADOS.map((e) => {
          const em = PLAN_ESTADO_META[e];
          const active = plan.estado === e;
          return (
            <button
              key={e}
              onClick={() => onSetEstado(plan, e)}
              disabled={saving || active}
              className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-default ${
                active ? `${em.bg} ${em.text} ${em.border}` : 'border-white/[0.06] text-slate-500 hover:text-slate-300'
              }`}
            >
              {em.label}
            </button>
          );
        })}
        {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-500" />}
        <span className="text-[11px] text-slate-600">No cambia el puntaje del criterio.</span>
      </div>
    </div>
  );
}

function ContradictionsCard({ items }: { items: Finding[] }) {
  return (
    <div className="card border-amber-500/20 p-5">
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-300" />
        <h3 className="text-sm font-semibold text-white">
          Contradicciones entre fuentes ({items.length})
        </h3>
      </div>
      <p className="mb-3 text-xs text-slate-500">
        Lo declarado en un documento no coincide con lo observado en la configuración (o con otro
        documento). Prevalece la observación técnica y la afirmación documental contradicha no cuenta para el puntaje; el criterio se evalúa como si no existiera.
      </p>
      <ul className="space-y-3">
        {items.map((f) => {
          const meta = SEVERITY_META[f.severidad];
          return (
            <li
              key={`${f.criterion_id}-${f.titulo}`}
              className="rounded-lg border border-white/[0.06] bg-ink-900/40 p-3.5"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-slate-200">{f.titulo}</span>
                <span className={`chip border text-[10px] ${meta.bg} ${meta.border} ${meta.text}`}>
                  {meta.label}
                </span>
                <span className="text-[11px] text-slate-600">{f.criterion_id}</span>
              </div>
              {f.detalle && <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{f.detalle}</p>}
              <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-slate-600">
                <Link2 className="h-3 w-3" />
                {f.evidence_ids.length} evidencia(s) citadas (ambos lados)
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function LimitationsCard({ items }: { items: Finding[] }) {
  return (
    <div className="card border-sky-500/20 p-5">
      <div className="mb-3 flex items-center gap-2">
        <Info className="h-4 w-4 text-sky-300" />
        <h3 className="text-sm font-semibold text-white">Limitaciones del análisis ({items.length})</h3>
      </div>
      <p className="mb-3 text-xs text-slate-500">
        Lo que el análisis no pudo determinar: no son brechas ni cambian el puntaje, pero esos criterios hay que
        leerlos con cautela. El puntaje solo refleja lo que sí se pudo resolver.
      </p>
      <ul className="space-y-2">
        {items.map((f) => (
          <li
            key={`${f.criterion_id}-${f.titulo}`}
            className="rounded-lg border border-white/[0.06] bg-ink-900/40 p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-slate-200">{f.titulo}</span>
              <span className="text-[11px] text-slate-600">{f.criterion_id}</span>
            </div>
            {f.detalle && <p className="mt-1 text-xs leading-relaxed text-slate-400">{f.detalle}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
