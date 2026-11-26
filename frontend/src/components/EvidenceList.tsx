import { useState } from 'react';
import { AlertTriangle, ChevronRight, FileSearch, Loader2 } from 'lucide-react';
import { getCriterionEvidence } from '@/lib/api';
import type { CriterionEvidence, EvidenceLocator, EvidenceModality } from '@/lib/types';

const MODALITY_META: Record<EvidenceModality, { label: string; className: string }> = {
  declarada: { label: 'Declarada', className: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300' },
  documental: { label: 'Documental', className: 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300' },
  operativa: { label: 'Operativa', className: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' },
  contexto: { label: 'Contexto', className: 'border-white/10 bg-white/[0.04] text-slate-400' },
};

const MAX_VALUE_CHARS = 160;
const MAX_FIELDS = 8;

function shorten(text: string): string {
  return text.length > MAX_VALUE_CHARS ? `${text.slice(0, MAX_VALUE_CHARS - 1)}…` : text;
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(formatScalar).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function valueFields(value: unknown): { key: string | null; text: string }[] {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return [{ key: null, text: formatScalar(value) }];
  }
  return Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .slice(0, MAX_FIELDS)
    .map(([key, v]) => ({ key, text: formatScalar(v) }));
}

function formatLocator(locator: EvidenceLocator): string | null {
  const parts: string[] = [];
  if (locator.file) {
    let ref = locator.file.replace(/^.*\/uploads\/[^/]+\//, '');
    if (locator.line_start != null) {
      ref += `:${locator.line_start}`;
      if (locator.line_end != null && locator.line_end !== locator.line_start) ref += `-${locator.line_end}`;
    }
    parts.push(ref);
  }
  if (locator.page != null) parts.push(`pág. ${locator.page}`);
  if (locator.section) parts.push(`§ ${locator.section}`);
  if (parts.length === 0 && locator.event_id) parts.push(locator.event_id);
  return parts.length > 0 ? parts.join(' · ') : null;
}

/** Evidencia de un criterio, desplegable y cargada al abrirla. Los alias `e1`... son los que cita
 * la explicación del criterio (docs/09 §118). */
export function EvidenceList({
  assessmentId,
  criterionId,
  count,
}: {
  assessmentId: string;
  criterionId: string;
  count: number;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<CriterionEvidence[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (count === 0) return null;

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next || items !== null || loading) return;
    setLoading(true);
    setError(null);
    try {
      setItems(await getCriterionEvidence(assessmentId, criterionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo cargar la evidencia.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-2.5">
      <button
        onClick={() => void toggle()}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-xs font-medium text-cyan-300 transition-colors hover:text-cyan-200"
      >
        <ChevronRight className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-90' : ''}`} />
        <FileSearch className="h-3.5 w-3.5" />
        {open ? 'Ocultar evidencia' : `Ver evidencia (${count})`}
      </button>

      {open && (
        <div className="mt-2 animate-fade-in space-y-2">
          {loading && (
            <p className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Cargando evidencia…
            </p>
          )}
          {error && (
            <p className="flex items-start gap-2 text-xs text-rose-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" /> {error}
            </p>
          )}
          {items !== null && items.length === 0 && (
            <p className="text-xs text-slate-500">La evidencia de este criterio ya no está disponible.</p>
          )}
          {items?.map(({ alias, evidence }) => {
            const modality = MODALITY_META[evidence.modality] ?? MODALITY_META.contexto;
            const locator = formatLocator(evidence.locator);
            const locatorTitle = evidence.locator.file ?? locator ?? undefined;
            return (
              <div key={evidence.id} className="rounded-lg border border-white/[0.06] bg-ink-900/40 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-slate-200">{alias}</span>
                  <span className="font-mono text-xs text-slate-400">{evidence.type_id}</span>
                  <span className={`chip border text-[10px] ${modality.className}`}>{modality.label}</span>
                  {locator && (
                    <span className="ml-auto break-all font-mono text-[11px] text-slate-500" title={locatorTitle}>
                      {locator}
                    </span>
                  )}
                </div>
                <dl className="mt-1.5 space-y-0.5 text-xs text-slate-400">
                  {valueFields(evidence.value).map(({ key, text }, index) => (
                    <div key={key ?? index} className="flex gap-1.5">
                      {key && <dt className="flex-shrink-0 text-slate-500">{key}:</dt>}
                      <dd className="min-w-0 break-words" title={text.length > MAX_VALUE_CHARS ? text : undefined}>
                        {shorten(text)}
                      </dd>
                    </div>
                  ))}
                </dl>
                {evidence.limitations && (
                  <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-amber-300">
                    <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
                    {evidence.limitations}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
