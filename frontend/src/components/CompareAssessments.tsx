import { useEffect, useMemo, useState } from 'react';
import {
  GitCompare,
  ArrowRight,
  ArrowLeftRight,
  ArrowUpRight,
  ArrowDownRight,
  ChevronDown,
  Eye,
  EyeOff,
  Loader2,
  AlertTriangle,
  Minus,
} from 'lucide-react';
import { compareAssessments, downloadComparisonReport, listAssessments } from '@/lib/api';
import { DownloadPdfButton } from '@/components/DownloadPdfButton';
import type {
  AssessmentDetail,
  ComparisonDiff,
  ComparisonDirection,
  ComparisonOut,
  Estado,
} from '@/lib/types';
import { FUNCTION_NAMES, FUNCTION_ORDER } from '@/lib/types';
import { ESTADO_META, FUNCTION_ACCENTS } from '@/lib/ui';

interface Props {
  orgId: string;
  currentAssessmentId: string;
}

function label(a: AssessmentDetail): string {
  const when = new Date(a.creado_en).toLocaleString();
  const score = a.score_global != null ? Math.round(a.score_global) : '—';
  return `${when} · score ${score}`;
}

const time = (a: AssessmentDetail) => new Date(a.creado_en).getTime();

const round = (value: number | null | undefined) => (value != null ? `${Math.round(value)}` : '—');

const percent = (value: number | null | undefined) =>
  value != null ? `${Math.round(value * 100)}%` : '—';

function tierText(a: AssessmentDetail): string {
  if (!a.tier.estimable || a.tier.tier == null) return 'No estimable';
  return `Tier ${a.tier.tier}${a.tier.provisional ? ' (prov.)' : ''}`;
}

function estadoLabel(estado: string | null): string {
  if (estado == null) return '—';
  return ESTADO_META[estado as Estado]?.label ?? estado;
}

interface DirectionMeta {
  label: string;
  text: string;
  bg: string;
  border: string;
  icon: React.ReactNode;
}

const DIRECTION_META: Record<ComparisonDirection, DirectionMeta> = {
  mejora: {
    label: 'Mejoró',
    text: 'text-emerald-300',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
    icon: <ArrowUpRight className="h-3.5 w-3.5" />,
  },
  retroceso: {
    label: 'Empeoró',
    text: 'text-rose-300',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
    icon: <ArrowDownRight className="h-3.5 w-3.5" />,
  },
  ahora_evaluado: {
    label: 'Ahora se evalúa',
    text: 'text-cyan-300',
    bg: 'bg-cyan-500/10',
    border: 'border-cyan-500/30',
    icon: <Eye className="h-3.5 w-3.5" />,
  },
  dejo_de_evaluarse: {
    label: 'Dejó de evaluarse',
    text: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    icon: <EyeOff className="h-3.5 w-3.5" />,
  },
  cambio_de_estado: {
    label: 'Cambió de estado',
    text: 'text-slate-300',
    bg: 'bg-white/[0.06]',
    border: 'border-white/15',
    icon: <ArrowRight className="h-3.5 w-3.5" />,
  },
  igual: {
    label: 'Sin cambio',
    text: 'text-slate-500',
    bg: 'bg-white/[0.04]',
    border: 'border-white/10',
    icon: <Minus className="h-3.5 w-3.5" />,
  },
};

/** Orden en que se listan los cambios: primero lo que empeoró. */
const DIRECTION_ORDER: ComparisonDirection[] = [
  'retroceso',
  'dejo_de_evaluarse',
  'mejora',
  'ahora_evaluado',
  'cambio_de_estado',
  'igual',
];

export function CompareAssessments({ orgId, currentAssessmentId }: Props) {
  const [assessments, setAssessments] = useState<AssessmentDetail[] | null>(null);
  const [idA, setIdA] = useState('');
  const [idB, setIdB] = useState('');
  const [comparison, setComparison] = useState<ComparisonOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showUnchanged, setShowUnchanged] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listAssessments()
      .then((all) => {
        if (!active) return;
        const ownComplete = all
          .filter((a) => a.org_id === orgId && a.estado === 'completada')
          .sort((a, b) => time(b) - time(a));
        setAssessments(ownComplete);
        if (ownComplete.length >= 2) {
          // "Después" es la evaluación activa; "Antes", la inmediatamente anterior a ella (o, si
          // la activa es la más antigua, la siguiente).
          const after = ownComplete.find((a) => a.id === currentAssessmentId) ?? ownComplete[0];
          const older = ownComplete.find((a) => time(a) < time(after));
          const before = older ?? ownComplete.find((a) => a.id !== after.id) ?? ownComplete[1];
          setIdB(after.id);
          setIdA(before.id);
        }
      })
      .catch((err) => active && setError(err instanceof Error ? err.message : 'Error desconocido.'));
    return () => {
      active = false;
    };
  }, [orgId, currentAssessmentId]);

  // La comparación se recalcula sola al cambiar cualquiera de las dos evaluaciones.
  useEffect(() => {
    if (!idA || !idB || idA === idB) {
      setComparison(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    setExpanded(null);
    compareAssessments(idA, idB)
      .then((result) => active && setComparison(result))
      .catch((err) => {
        if (!active) return;
        setComparison(null);
        setError(err instanceof Error ? err.message : 'Error desconocido.');
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [idA, idB]);

  const before = assessments?.find((a) => a.id === idA) ?? null;
  const after = assessments?.find((a) => a.id === idB) ?? null;
  const reversed = before != null && after != null && time(before) > time(after);

  const counts = useMemo(() => {
    const result = {} as Record<ComparisonDirection, number>;
    for (const key of DIRECTION_ORDER) result[key] = 0;
    for (const d of comparison?.diffs ?? []) result[d.direccion] += 1;
    return result;
  }, [comparison]);

  // Puntaje y cobertura por función tal como los calcula el backend (ponderados por peso): los
  // mismos números que muestra el Resumen de Madurez.
  const byFunction = useMemo(() => {
    if (!comparison || !before || !after) return [];
    const aggregate = (a: AssessmentDetail, key: string) =>
      a.agregados_funcion.find((f) => f.ref === key) ?? null;
    return FUNCTION_ORDER.map((key) => {
      const antes = aggregate(before, key);
      const despues = aggregate(after, key);
      const diffs = comparison.diffs.filter((d) => d.criterion_id.split('-')[1] === key);
      if (diffs.length === 0) return null;
      return {
        key,
        name: FUNCTION_NAMES[key] ?? key,
        accent: FUNCTION_ACCENTS[key] ?? '#94a3b8',
        antes,
        despues,
        cambiados: diffs.filter((d) => d.cambio).length,
        total: diffs.length,
      };
    }).filter((x): x is NonNullable<typeof x> => x !== null);
  }, [comparison, before, after]);

  const rows = useMemo(() => {
    if (!comparison) return [];
    const order = (d: ComparisonDiff) => DIRECTION_ORDER.indexOf(d.direccion);
    return comparison.diffs
      .filter((d) => showUnchanged || d.cambio)
      .slice()
      .sort((a, b) => order(a) - order(b) || a.criterion_id.localeCompare(b.criterion_id));
  }, [comparison, showUnchanged]);

  if (assessments === null) {
    return (
      <div className="card flex items-center justify-center px-6 py-16 text-sm text-slate-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Cargando evaluaciones…
      </div>
    );
  }

  if (assessments.length < 2) {
    return (
      <div className="card flex flex-col items-center justify-center px-6 py-16 text-center">
        <GitCompare className="mb-3 h-10 w-10 text-slate-700" />
        <h3 className="text-sm font-semibold text-slate-200">Nada que comparar todavía</h3>
        <p className="mt-1 max-w-sm text-xs text-slate-500">
          Necesitas al menos 2 evaluaciones completadas de esta organización. Crea otra desde
          «Nueva Evaluación»: los tres paquetes de ejemplo están pensados para compararse entre sí.
        </p>
      </div>
    );
  }

  const deltaGlobal =
    comparison?.global_antes != null && comparison?.global_despues != null
      ? comparison.global_despues - comparison.global_antes
      : null;
  const deltaCobertura =
    before?.cobertura_global != null && after?.cobertura_global != null
      ? (after.cobertura_global - before.cobertura_global) * 100
      : null;
  const changedCount = comparison?.diffs.filter((d) => d.cambio).length ?? 0;
  const unchangedCount = (comparison?.diffs.length ?? 0) - changedCount;

  return (
    <div className="space-y-6">
      <div className="card p-5">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 ring-1 ring-indigo-500/20">
            <GitCompare className="h-5 w-5 text-indigo-300" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Comparar Evaluaciones</h3>
            <p className="text-xs text-slate-500">Qué cambió entre dos evaluaciones completadas, y por qué.</p>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[220px] flex-1">
            <label className="mb-1.5 block text-xs font-medium text-slate-400">Antes</label>
            <select value={idA} onChange={(e) => setIdA(e.target.value)} className="input">
              {assessments.map((a) => (
                <option key={a.id} value={a.id}>
                  {label(a)}
                </option>
              ))}
            </select>
          </div>
          <button
            title="Intercambiar antes y después"
            onClick={() => {
              setIdA(idB);
              setIdB(idA);
            }}
            className="btn-ghost mb-0.5 border border-white/[0.06] px-2.5"
          >
            <ArrowLeftRight className="h-4 w-4" />
          </button>
          <div className="min-w-[220px] flex-1">
            <label className="mb-1.5 block text-xs font-medium text-slate-400">Después</label>
            <select value={idB} onChange={(e) => setIdB(e.target.value)} className="input">
              {assessments.map((a) => (
                <option key={a.id} value={a.id}>
                  {label(a)}
                </option>
              ))}
            </select>
          </div>
          {loading && <Loader2 className="mb-2.5 h-4 w-4 animate-spin text-slate-500" />}
        </div>

        {idA === idB && (
          <p className="mt-3 text-xs text-slate-500">Elige dos evaluaciones distintas.</p>
        )}
        {reversed && (
          <Notice>
            «Antes» es más reciente que «Después»: la comparación se lee al revés en el tiempo.
          </Notice>
        )}
        {comparison && (!comparison.misma_metodologia || !comparison.mismo_scope) && (
          <Notice>
            Estas evaluaciones usan{' '}
            {[
              !comparison.misma_metodologia && 'versiones distintas de las reglas',
              !comparison.mismo_scope && 'alcances distintos',
            ]
              .filter(Boolean)
              .join(' y ')}
            . Parte de los cambios puede deberse a eso y no a cambios en el entorno.
          </Notice>
        )}
        {error && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-rose-300">
            <AlertTriangle className="h-3.5 w-3.5" /> {error}
          </p>
        )}
      </div>

      {comparison && before && after && (
        <>
          <div className="flex justify-end">
            <DownloadPdfButton
              label="Comparación PDF"
              onDownload={() =>
                downloadComparisonReport(comparison.assessment_id_a, comparison.assessment_id_b)
              }
            />
          </div>

          {/* Resumen: puntaje, cobertura y Tier, siempre juntos (un puntaje sin su cobertura engaña) */}
          <div className="grid gap-4 sm:grid-cols-3">
            <SummaryCard
              label="Score global"
              value={`${round(comparison.global_antes)} → ${round(comparison.global_despues)}`}
              delta={deltaGlobal}
            />
            <SummaryCard
              label="Cobertura de evidencia"
              value={`${percent(before.cobertura_global)} → ${percent(after.cobertura_global)}`}
              delta={deltaCobertura}
              unit=" pts"
            />
            <SummaryCard
              label="Tier estimado"
              value={`${tierText(before)} → ${tierText(after)}`}
              delta={
                before.tier.tier != null && after.tier.tier != null
                  ? after.tier.tier - before.tier.tier
                  : null
              }
            />
          </div>

          {/* Qué pasó con los criterios y con los hallazgos */}
          <div className="card p-5">
            <div className="flex flex-wrap gap-2">
              {DIRECTION_ORDER.filter((key) => counts[key] > 0).map((key) => {
                const meta = DIRECTION_META[key];
                return (
                  <span
                    key={key}
                    className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium ${meta.bg} ${meta.border} ${meta.text}`}
                  >
                    {meta.icon}
                    {counts[key]} · {meta.label.toLowerCase()}
                  </span>
                );
              })}
            </div>
            <p className="mt-3 text-xs leading-relaxed text-slate-400">
              <span className="font-semibold text-slate-300">Hallazgos:</span>{' '}
              {comparison.hallazgos_resueltos.length === 0 && comparison.hallazgos_nuevos.length === 0
                ? 'los mismos criterios tienen brecha en las dos evaluaciones.'
                : [
                    comparison.hallazgos_resueltos.length > 0 &&
                      `${comparison.hallazgos_resueltos.length} ya no aparece(n) (${comparison.hallazgos_resueltos.join(', ')})`,
                    comparison.hallazgos_nuevos.length > 0 &&
                      `${comparison.hallazgos_nuevos.length} nuevo(s) (${comparison.hallazgos_nuevos.join(', ')})`,
                  ]
                    .filter(Boolean)
                    .join(' · ') + '.'}
              {counts.dejo_de_evaluarse > 0 &&
                ' Un hallazgo también deja de aparecer cuando su criterio deja de poder evaluarse: revisa los marcados «dejó de evaluarse».'}
            </p>
          </div>

          {/* Cambio por función */}
          {byFunction.length > 0 && (
            <div className="card p-5">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">Cambio por función CSF</h3>
                <span className="text-xs text-slate-500">Score ponderado y cobertura, antes → después</span>
              </div>
              <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
                {byFunction.map((f) => (
                  <div key={f.key} className="rounded-xl border border-white/[0.06] bg-ink-900/40 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <span
                        className="rounded-md px-2 py-0.5 text-xs font-bold"
                        style={{ backgroundColor: `${f.accent}1a`, color: f.accent }}
                      >
                        {f.key}
                      </span>
                      <span className="text-xs text-slate-500">
                        {f.cambiados}/{f.total} cambiados
                      </span>
                    </div>
                    <p className="mb-2.5 text-xs font-medium text-slate-300">{f.name}</p>
                    <ScoreBar label="Antes" value={f.antes?.score ?? null} accent="#475569" />
                    <div className="h-1.5" />
                    <ScoreBar label="Después" value={f.despues?.score ?? null} accent={f.accent} />
                    <p className="mt-2.5 text-[11px] text-slate-500">
                      Cobertura {percent(f.antes?.cobertura)} → {percent(f.despues?.cobertura)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Detalle por criterio */}
          <div className="card overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] px-5 py-3.5">
              <h3 className="text-sm font-semibold text-white">
                {changedCount} criterio(s) con cambio
              </h3>
              {unchangedCount > 0 && (
                <button
                  onClick={() => setShowUnchanged((v) => !v)}
                  className="text-xs text-slate-400 underline-offset-2 hover:text-slate-200 hover:underline"
                >
                  {showUnchanged ? 'Ocultar' : 'Mostrar'} los {unchangedCount} sin cambio
                </button>
              )}
            </div>
            {rows.length === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-slate-500">
                Ningún criterio cambió entre las dos evaluaciones.
              </p>
            ) : (
              <div className="divide-y divide-white/[0.04]">
                {rows.map((d) => (
                  <CriterionRow
                    key={d.criterion_id}
                    diff={d}
                    open={expanded === d.criterion_id}
                    onToggle={() =>
                      setExpanded((current) => (current === d.criterion_id ? null : d.criterion_id))
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-200">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
      <span>{children}</span>
    </p>
  );
}

function CriterionRow({
  diff,
  open,
  onToggle,
}: {
  diff: ComparisonDiff;
  open: boolean;
  onToggle: () => void;
}) {
  const meta = DIRECTION_META[diff.direccion];
  const sameExplanation = diff.explicacion_antes === diff.explicacion_despues;
  return (
    <div>
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-5 py-3 text-left text-sm transition-colors hover:bg-white/[0.02]"
      >
        <span
          title={meta.label}
          className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md border ${meta.bg} ${meta.border} ${meta.text}`}
        >
          {meta.icon}
        </span>
        <span className="w-24 flex-shrink-0 font-mono text-xs text-slate-500">{diff.criterion_id}</span>
        <span className="min-w-0 flex-1 truncate text-slate-300">{diff.titulo}</span>
        <span className={`hidden flex-shrink-0 text-xs sm:block ${meta.text}`}>{meta.label}</span>
        <span className="w-20 flex-shrink-0 text-right text-xs font-semibold text-slate-300">
          {round(diff.score_antes)} → {round(diff.score_despues)}
        </span>
        <ChevronDown
          className={`h-4 w-4 flex-shrink-0 text-slate-600 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="grid gap-3 bg-ink-900/40 px-5 pb-4 pt-1 sm:grid-cols-2">
          <ExplanationPanel
            title="Antes"
            estado={diff.estado_antes}
            score={diff.score_antes}
            text={diff.explicacion_antes}
          />
          <ExplanationPanel
            title="Después"
            estado={diff.estado_despues}
            score={diff.score_despues}
            text={sameExplanation ? 'La misma explicación que antes.' : diff.explicacion_despues}
            muted={sameExplanation}
          />
        </div>
      )}
    </div>
  );
}

function ExplanationPanel({
  title,
  estado,
  score,
  text,
  muted = false,
}: {
  title: string;
  estado: string | null;
  score: number | null;
  text: string | null;
  muted?: boolean;
}) {
  return (
    <div className="rounded-lg border border-white/[0.06] p-3">
      <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
        <span className="font-semibold text-slate-300">{title}</span>
        <span className="text-slate-500">
          {estadoLabel(estado)} · {round(score)}
        </span>
      </div>
      <p className={`text-xs leading-relaxed ${muted ? 'italic text-slate-500' : 'text-slate-400'}`}>
        {text ?? 'El criterio no existía en esta evaluación.'}
      </p>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  delta,
  unit = '',
}: {
  label: string;
  value: string;
  delta: number | null;
  unit?: string;
}) {
  const rounded = delta != null ? Math.round(delta) : null;
  const positive = rounded != null && rounded > 0;
  const negative = rounded != null && rounded < 0;
  return (
    <div className="card p-5">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2">
        <p className="text-xl font-bold tracking-tight text-white">{value}</p>
        {rounded != null && (
          <span
            className={`flex items-center gap-0.5 text-sm font-semibold ${
              positive ? 'text-emerald-300' : negative ? 'text-rose-300' : 'text-slate-400'
            }`}
          >
            {positive ? (
              <ArrowUpRight className="h-4 w-4" />
            ) : negative ? (
              <ArrowDownRight className="h-4 w-4" />
            ) : (
              <Minus className="h-4 w-4" />
            )}
            {positive ? '+' : ''}
            {rounded}
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

function ScoreBar({ label, value, accent }: { label: string; value: number | null; accent: string }) {
  const pct = value != null ? Math.max(0, Math.min(100, value)) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-14 flex-shrink-0 text-xs text-slate-500">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, backgroundColor: accent }}
        />
      </div>
      <span className="w-8 flex-shrink-0 text-right text-xs font-semibold text-slate-400">
        {value != null ? Math.round(value) : '—'}
      </span>
    </div>
  );
}
