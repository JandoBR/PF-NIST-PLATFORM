import { useEffect, useMemo, useState } from 'react';
import {
  GitCompare,
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
  AlertTriangle,
  Minus,
  TrendingUp,
  TrendingDown,
} from 'lucide-react';
import { compareAssessments, downloadComparisonReport, listAssessments } from '@/lib/api';
import { DownloadPdfButton } from '@/components/DownloadPdfButton';
import type { AssessmentDetail, ComparisonDiff, ComparisonOut } from '@/lib/types';
import { FUNCTION_NAMES, FUNCTION_ORDER } from '@/lib/types';
import { FUNCTION_ACCENTS } from '@/lib/ui';

interface Props {
  orgId: string;
  currentAssessmentId: string;
}

function label(a: AssessmentDetail): string {
  const when = new Date(a.creado_en).toLocaleString();
  const score = a.score_global != null ? Math.round(a.score_global) : '—';
  return `${when} · ${a.estado} · score ${score}`;
}

function functionOf(criterionId: string): string {
  return criterionId.split('-')[1] ?? '';
}

/** Delta de score de un criterio, o `null` si Falta alguno de los dos puntajes. */
function scoreDelta(d: ComparisonDiff): number | null {
  if (d.score_antes == null || d.score_despues == null) return null;
  return d.score_despues - d.score_antes;
}

type Direction = 'up' | 'down' | 'changed' | 'same';

function direction(d: ComparisonDiff): Direction {
  if (!d.cambio) return 'same';
  const delta = scoreDelta(d);
  if (delta == null || delta === 0) return 'changed';
  return delta > 0 ? 'up' : 'down';
}

const DIRECTION_META: Record<Direction, { text: string; bg: string; border: string }> = {
  up: { text: 'text-emerald-300', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
  down: { text: 'text-rose-300', bg: 'bg-rose-500/10', border: 'border-rose-500/30' },
  changed: { text: 'text-cyan-300', bg: 'bg-cyan-500/10', border: 'border-cyan-500/30' },
  same: { text: 'text-slate-500', bg: 'bg-white/[0.04]', border: 'border-white/10' },
};

export function CompareAssessments({ orgId, currentAssessmentId }: Props) {
  const [assessments, setAssessments] = useState<AssessmentDetail[] | null>(null);
  const [idA, setIdA] = useState('');
  const [idB, setIdB] = useState('');
  const [comparison, setComparison] = useState<ComparisonOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listAssessments()
      .then((all) => {
        if (!active) return;
        const ownComplete = all
          .filter((a) => a.org_id === orgId && a.estado === 'completada')
          .sort((a, b) => new Date(b.creado_en).getTime() - new Date(a.creado_en).getTime());
        setAssessments(ownComplete);
        if (ownComplete.length >= 2) {
          const defaultB = ownComplete.find((a) => a.id === currentAssessmentId) ?? ownComplete[0];
          const defaultA = ownComplete.find((a) => a.id !== defaultB.id) ?? ownComplete[1];
          setIdB(defaultB.id);
          setIdA(defaultA.id);
        }
      })
      .catch((err) => active && setError(err instanceof Error ? err.message : 'Error desconocido.'));
    return () => {
      active = false;
    };
  }, [orgId, currentAssessmentId]);

  const canCompare = idA && idB && idA !== idB;

  async function handleCompare() {
    setLoading(true);
    setError(null);
    try {
      setComparison(await compareAssessments(idA, idB));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error desconocido.');
    } finally {
      setLoading(false);
    }
  }

  const summary = useMemo(() => {
    if (!comparison) return null;
    const mejoras = comparison.diffs.filter((d) => direction(d) === 'up').length;
    const retrocesos = comparison.diffs.filter((d) => direction(d) === 'down').length;
    const sinCambio = comparison.diffs.filter((d) => !d.cambio).length;
    const deltaGlobal =
      comparison.global_antes != null && comparison.global_despues != null
        ? comparison.global_despues - comparison.global_antes
        : null;
    return { mejoras, retrocesos, sinCambio, deltaGlobal };
  }, [comparison]);

  const byFunction = useMemo(() => {
    if (!comparison) return [];
    return FUNCTION_ORDER.map((key) => {
      const diffs = comparison.diffs.filter((d) => functionOf(d.criterion_id) === key);
      if (diffs.length === 0) return null;
      const before = diffs.filter((d) => d.score_antes != null);
      const after = diffs.filter((d) => d.score_despues != null);
      const avg = (xs: ComparisonDiff[], pick: (d: ComparisonDiff) => number | null) =>
        xs.length > 0 ? xs.reduce((n, d) => n + (pick(d) ?? 0), 0) / xs.length : null;
      return {
        key,
        name: FUNCTION_NAMES[key] ?? key,
        accent: FUNCTION_ACCENTS[key] ?? '#94a3b8',
        antes: avg(before, (d) => d.score_antes),
        despues: avg(after, (d) => d.score_despues),
        cambiados: diffs.filter((d) => d.cambio).length,
        total: diffs.length,
      };
    }).filter((x): x is NonNullable<typeof x> => x !== null);
  }, [comparison]);

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
          Necesitas al menos 2 evaluaciones completadas para esta organización. Reevalúa desde el
          resumen de madurez para generar una segunda.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="card p-5">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 ring-1 ring-indigo-500/20">
            <GitCompare className="h-5 w-5 text-indigo-300" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Comparar Evaluaciones</h3>
            <p className="text-xs text-slate-500">Diferencia criterio por criterio entre dos evaluaciones completadas.</p>
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
          <ArrowRight className="mb-2.5 h-4 w-4 flex-shrink-0 text-slate-600" />
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
          <button onClick={handleCompare} disabled={!canCompare || loading} className="btn-primary">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitCompare className="h-4 w-4" />}
            Comparar
          </button>
        </div>

        {error && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-rose-300">
            <AlertTriangle className="h-3.5 w-3.5" /> {error}
          </p>
        )}
      </div>

      {comparison && summary && (
        <>
          <div className="flex justify-end">
            <DownloadPdfButton
              label="Comparación PDF"
              onDownload={() =>
                downloadComparisonReport(comparison.assessment_id_a, comparison.assessment_id_b)
              }
            />
          </div>

          {/* Resumen del cambio */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <DeltaCard
              label="Score global"
              value={`${comparison.global_antes != null ? Math.round(comparison.global_antes) : '—'} → ${
                comparison.global_despues != null ? Math.round(comparison.global_despues) : '—'
              }`}
              delta={summary.deltaGlobal}
            />
            <StatCard
              icon={<TrendingUp className="h-5 w-5" />}
              accent="emerald"
              label="Criterios mejorados"
              value={`${summary.mejoras}`}
            />
            <StatCard
              icon={<TrendingDown className="h-5 w-5" />}
              accent="rose"
              label="Criterios degradados"
              value={`${summary.retrocesos}`}
            />
            <StatCard
              icon={<Minus className="h-5 w-5" />}
              accent="slate"
              label="Sin cambio"
              value={`${summary.sinCambio}`}
            />
          </div>

          {/* Score global antes/después */}
          <div className="card p-5">
            <h3 className="mb-4 text-sm font-semibold text-white">Score global</h3>
            <div className="space-y-3">
              <DoubleBar
                label="Antes"
                value={comparison.global_antes}
                accent="#64748b"
              />
              <DoubleBar
                label="Después"
                value={comparison.global_despues}
                accent={summary.deltaGlobal != null && summary.deltaGlobal < 0 ? '#fb7185' : '#34d399'}
              />
            </div>
          </div>

          {/* Cambio por función */}
          {byFunction.length > 0 && (
            <div className="card p-5">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">Cambio por función CSF</h3>
                <span className="text-xs text-slate-500">Score promedio antes vs. después</span>
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
                    <DoubleBar label="Antes" value={f.antes} accent="#475569" compact />
                    <div className="h-1.5" />
                    <DoubleBar label="Después" value={f.despues} accent={f.accent} compact />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Detalle por criterio */}
          <div className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3.5">
              <h3 className="text-sm font-semibold text-white">Detalle por criterio</h3>
              <span className="text-xs text-slate-500">
                {comparison.diffs.filter((d) => d.cambio).length} de {comparison.diffs.length} criterio(s) con cambio
              </span>
            </div>
            <div className="divide-y divide-white/[0.04]">
              {comparison.diffs.map((d) => {
                const dir = direction(d);
                const meta = DIRECTION_META[dir];
                return (
                  <div
                    key={d.criterion_id}
                    className={`flex items-center gap-4 px-5 py-3 text-sm ${d.cambio ? 'bg-cyan-500/[0.03]' : ''}`}
                  >
                    <span className="w-24 flex-shrink-0 font-mono text-xs text-slate-500">{d.criterion_id}</span>
                    <span className="min-w-0 flex-1 truncate text-slate-300">{d.titulo}</span>
                    <span className="hidden w-32 flex-shrink-0 text-right text-xs text-slate-500 sm:block">
                      {d.estado_antes ?? '—'}
                    </span>
                    <span className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md border ${meta.bg} ${meta.border} ${meta.text}`}>
                      {dir === 'up' ? (
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      ) : dir === 'down' ? (
                        <ArrowDownRight className="h-3.5 w-3.5" />
                      ) : dir === 'changed' ? (
                        <ArrowRight className="h-3.5 w-3.5" />
                      ) : (
                        <Minus className="h-3.5 w-3.5" />
                      )}
                    </span>
                    <span className="hidden w-32 flex-shrink-0 text-xs text-slate-300 sm:block">
                      {d.estado_despues ?? '—'}
                    </span>
                    <span className="w-16 flex-shrink-0 text-right text-xs font-semibold text-slate-400">
                      {d.score_antes != null ? Math.round(d.score_antes) : '—'}
                      {' → '}
                      {d.score_despues != null ? Math.round(d.score_despues) : '—'}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  accent: 'emerald' | 'rose' | 'slate';
}) {
  const colors = {
    emerald: 'text-emerald-300 bg-emerald-500/10 ring-emerald-500/20',
    rose: 'text-rose-300 bg-rose-500/10 ring-rose-500/20',
    slate: 'text-slate-400 bg-white/[0.04] ring-white/10',
  };
  return (
    <div className="card card-hover p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className="mt-1.5 text-2xl font-bold tracking-tight text-white">{value}</p>
        </div>
        <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl ring-1 ${colors[accent]}`}>
          {icon}
        </div>
      </div>
    </div>
  );
}

function DeltaCard({ label, value, delta }: { label: string; value: string; delta: number | null }) {
  const positive = delta != null && delta > 0;
  const negative = delta != null && delta < 0;
  return (
    <div className="card p-5">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <div className="mt-1.5 flex items-baseline gap-2">
        <p className="text-2xl font-bold tracking-tight text-white">{value}</p>
        {delta != null && (
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
            {delta > 0 ? '+' : ''}
            {Math.round(delta)}
          </span>
        )}
      </div>
    </div>
  );
}

function DoubleBar({
  label,
  value,
  accent,
  compact = false,
}: {
  label: string;
  value: number | null;
  accent: string;
  compact?: boolean;
}) {
  const pct = value != null ? Math.max(0, Math.min(100, value)) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className={`flex-shrink-0 text-xs text-slate-500 ${compact ? 'w-14' : 'w-16'}`}>{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, backgroundColor: accent }}
        />
      </div>
      <span className={`flex-shrink-0 text-right text-xs font-semibold text-slate-400 ${compact ? 'w-8' : 'w-10'}`}>
        {value != null ? Math.round(value) : '—'}
      </span>
    </div>
  );
}
