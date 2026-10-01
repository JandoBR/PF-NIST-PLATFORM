import { useEffect, useMemo, useState } from 'react';
import { GitCompare, ArrowRight, Loader2, AlertTriangle, Minus } from 'lucide-react';
import { compareAssessments, listAssessments } from '@/lib/api';
import type { AssessmentDetail, ComparisonOut } from '@/lib/types';

interface Props {
  orgId: string;
  currentAssessmentId: string;
}

function label(a: AssessmentDetail): string {
  const when = new Date(a.creado_en).toLocaleString();
  const score = a.score_global != null ? Math.round(a.score_global) : '—';
  return `${when} · ${a.estado} · score ${score}`;
}

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

  const changedCount = useMemo(
    () => comparison?.diffs.filter((d) => d.cambio).length ?? 0,
    [comparison]
  );

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

      {comparison && (
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3.5">
            <h3 className="text-sm font-semibold text-white">
              Score global: {comparison.global_antes != null ? Math.round(comparison.global_antes) : '—'}
              {' → '}
              {comparison.global_despues != null ? Math.round(comparison.global_despues) : '—'}
            </h3>
            <span className="text-xs text-slate-500">{changedCount} criterio(s) con cambio</span>
          </div>
          <div className="divide-y divide-white/[0.04]">
            {comparison.diffs.map((d) => (
              <div
                key={d.criterion_id}
                className={`flex items-center gap-4 px-5 py-3 text-sm ${d.cambio ? 'bg-cyan-500/[0.03]' : ''}`}
              >
                <span className="w-24 flex-shrink-0 font-mono text-xs text-slate-500">{d.criterion_id}</span>
                <span className="min-w-0 flex-1 truncate text-slate-300">{d.titulo}</span>
                <span className="w-32 flex-shrink-0 text-right text-xs text-slate-500">
                  {d.estado_antes ?? '—'}
                </span>
                {d.cambio ? (
                  <ArrowRight className="h-3.5 w-3.5 flex-shrink-0 text-cyan-400" />
                ) : (
                  <Minus className="h-3.5 w-3.5 flex-shrink-0 text-slate-700" />
                )}
                <span className="w-32 flex-shrink-0 text-xs text-slate-300">{d.estado_despues ?? '—'}</span>
                <span className="w-16 flex-shrink-0 text-right text-xs font-semibold text-slate-400">
                  {d.score_antes != null ? Math.round(d.score_antes) : '—'}
                  {' → '}
                  {d.score_despues != null ? Math.round(d.score_despues) : '—'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
