import { useMemo, useState } from 'react';
import { Gauge, Target, ShieldQuestion, Filter, Search, ChevronRight, Info } from 'lucide-react';
import type { AssessmentDetail, CriterionResult, Estado } from '@/lib/types';
import { FUNCTION_NAMES, FUNCTION_ORDER, TIER_LABELS } from '@/lib/types';
import { ESTADO_META } from '@/lib/ui';

const FUNCTION_ACCENTS: Record<string, string> = {
  GV: '#a78bfa',
  ID: '#60a5fa',
  PR: '#34d399',
  DE: '#fbbf24',
  RS: '#fb7185',
  RC: '#2dd4bf',
};

interface DashboardProps {
  assessment: AssessmentDetail;
  criteria: CriterionResult[];
}

const FILTERS: { key: Estado | 'all'; label: string }[] = [
  { key: 'all', label: 'Todos' },
  { key: 'evaluado', label: 'Evaluado' },
  { key: 'no_implementado', label: 'No implementado' },
  { key: 'evidencia_insuficiente', label: 'Evidencia insuficiente' },
  { key: 'no_aplicable', label: 'No aplicable' },
  { key: 'error', label: 'Error' },
];

export function MaturityDashboard({ assessment, criteria }: DashboardProps) {
  const [estadoFilter, setEstadoFilter] = useState<Estado | 'all'>('all');
  const [funcFilter, setFuncFilter] = useState<string>('all');
  const [query, setQuery] = useState('');

  const functionScores = useMemo(() => {
    const byRef = new Map(assessment.agregados_funcion.map((a) => [a.ref, a]));
    return FUNCTION_ORDER.filter((key) => byRef.has(key)).map((key) => ({
      key,
      name: FUNCTION_NAMES[key] ?? key,
      accent: FUNCTION_ACCENTS[key] ?? '#94a3b8',
      aggregate: byRef.get(key)!,
    }));
  }, [assessment.agregados_funcion]);

  const filtered = useMemo(() => {
    return criteria.filter((c) => {
      if (estadoFilter !== 'all' && c.estado !== estadoFilter) return false;
      if (funcFilter !== 'all' && !c.criterion_id.includes(`-${funcFilter}-`)) return false;
      if (query) {
        const q = query.toLowerCase();
        if (!c.criterion_id.toLowerCase().includes(q) && !c.explanation.toLowerCase().includes(q))
          return false;
      }
      return true;
    });
  }, [criteria, estadoFilter, funcFilter, query]);

  const tier = assessment.tier;

  return (
    <div className="space-y-6">
      {/* Tarjetas de resumen */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={<Gauge className="h-5 w-5" />}
          accent="cyan"
          label="Score Global"
          value={assessment.score_global != null ? `${Math.round(assessment.score_global)}` : '—'}
          sub="Promedio ponderado por criterio"
        />
        <SummaryCard
          icon={<Target className="h-5 w-5" />}
          accent="indigo"
          label="Cobertura Global"
          value={
            assessment.cobertura_global != null
              ? `${Math.round(assessment.cobertura_global * 100)}%`
              : '—'
          }
          sub="Criterios con evidencia suficiente"
        />
        <SummaryCard
          icon={<ShieldQuestion className="h-5 w-5" />}
          accent="emerald"
          label="Tier Estimado"
          value={tier.tier != null ? `Nivel ${tier.tier}` : 'No estimable'}
          sub={tier.tier != null ? TIER_LABELS[tier.tier - 1] : tier.justificacion}
        />
        <SummaryCard
          icon={<Info className="h-5 w-5" />}
          accent="amber"
          label="Confiabilidad del Tier"
          value={tier.provisional ? 'Provisional' : tier.estimable ? 'Confirmado' : 'N/D'}
          sub={tier.faltantes.length > 0 ? `Falta: ${tier.faltantes.join(', ')}` : tier.justificacion}
        />
      </div>

      {/* Matriz de funciones */}
      <div className="card p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-white">Matriz de Madurez NIST CSF 2.0</h3>
            <p className="text-xs text-slate-500">Puntaje y cobertura por función del marco de trabajo</p>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {functionScores.map((f) => {
            const score = f.aggregate.score;
            return (
              <div
                key={f.key}
                className="rounded-xl border border-white/[0.06] bg-ink-900/40 p-4 transition-colors hover:border-white/15"
              >
                <div className="mb-3 flex items-center justify-between">
                  <span
                    className="rounded-md px-2 py-0.5 text-xs font-bold"
                    style={{ backgroundColor: `${f.accent}1a`, color: f.accent }}
                  >
                    {f.key}
                  </span>
                  <span className="text-lg font-bold text-white">
                    {score != null ? Math.round(score) : '—'}
                  </span>
                </div>
                <p className="mb-2.5 text-xs font-medium text-slate-300">{f.name}</p>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{ width: `${score ?? 0}%`, backgroundColor: f.accent }}
                  />
                </div>
                <p className="mt-2 text-[11px] text-slate-600">
                  Cobertura {f.aggregate.cobertura != null ? `${Math.round(f.aggregate.cobertura * 100)}%` : '—'}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Tabla de criterios */}
      <div className="card overflow-hidden">
        <div className="flex flex-col gap-4 border-b border-white/[0.06] p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-slate-500" />
              <h3 className="text-sm font-semibold text-white">Criterios Evaluados</h3>
            </div>
            <span className="text-xs text-slate-500">
              {filtered.length} de {criteria.length}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex flex-wrap gap-1.5">
              <Chip active={funcFilter === 'all'} onClick={() => setFuncFilter('all')}>
                Todas las Funciones
              </Chip>
              {FUNCTION_ORDER.map((key) => (
                <Chip
                  key={key}
                  active={funcFilter === key}
                  onClick={() => setFuncFilter(key)}
                  accent={FUNCTION_ACCENTS[key]}
                >
                  {key}
                </Chip>
              ))}
            </div>

            <div className="flex flex-wrap gap-1.5">
              {FILTERS.map((f) => (
                <Chip key={f.key} active={estadoFilter === f.key} onClick={() => setEstadoFilter(f.key)}>
                  {f.label}
                </Chip>
              ))}
            </div>

            <div className="relative ml-auto">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-600" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar criterio..."
                className="w-44 rounded-lg border border-white/10 bg-ink-900/60 py-1.5 pl-8 pr-3 text-xs text-slate-200 placeholder-slate-600 outline-none focus:border-cyan-500/50 sm:w-56"
              />
            </div>
          </div>
        </div>

        <div className="divide-y divide-white/[0.04]">
          {filtered.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-slate-500">
              No hay criterios que coincidan con los filtros actuales.
            </div>
          ) : (
            filtered.map((c) => <CriterionRow key={c.criterion_id} criterion={c} />)
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub: string;
  accent: 'cyan' | 'indigo' | 'amber' | 'emerald';
}) {
  const colors = {
    cyan: 'text-cyan-300 bg-cyan-500/10 ring-cyan-500/20',
    indigo: 'text-indigo-300 bg-indigo-500/10 ring-indigo-500/20',
    amber: 'text-amber-300 bg-amber-500/10 ring-amber-500/20',
    emerald: 'text-emerald-300 bg-emerald-500/10 ring-emerald-500/20',
  };
  return (
    <div className="card card-hover p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className="mt-1.5 text-2xl font-bold tracking-tight text-white">{value}</p>
          <p className="mt-0.5 truncate text-xs text-slate-500" title={sub}>
            {sub}
          </p>
        </div>
        <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl ring-1 ${colors[accent]}`}>
          {icon}
        </div>
      </div>
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
  accent,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  accent?: string;
}) {
  return (
    <button
      onClick={onClick}
      style={active && accent ? { color: accent, backgroundColor: `${accent}1a` } : undefined}
      className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
        active ? (accent ? '' : 'bg-white/[0.08] text-white') : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  );
}

function CriterionRow({ criterion }: { criterion: CriterionResult }) {
  const meta = ESTADO_META[criterion.estado];
  const [open, setOpen] = useState(false);
  const score = criterion.final_score;

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-white/[0.02]"
      >
        <span className={`h-2 w-2 flex-shrink-0 rounded-full ${meta.dot}`} />
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="flex-shrink-0 font-mono text-xs font-semibold text-slate-300">
            {criterion.criterion_id}
          </span>
          <span className="truncate text-sm text-slate-400">{criterion.explanation}</span>
        </div>
        <div className="hidden w-32 sm:block">
          <div className="flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
              <div
                className={`h-full rounded-full ${meta.bar} transition-all duration-500`}
                style={{ width: `${score ?? 0}%` }}
              />
            </div>
            <span className="w-8 text-right text-xs font-semibold text-slate-400">
              {score != null ? Math.round(score) : '—'}
            </span>
          </div>
        </div>
        <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
        {criterion.degradado && (
          <span className="chip border border-amber-500/30 bg-amber-500/10 text-amber-300">IA degradada</span>
        )}
        <ChevronRight
          className={`h-4 w-4 flex-shrink-0 text-slate-600 transition-transform ${open ? 'rotate-90' : ''}`}
        />
      </button>
      {open && (
        <div className="animate-fade-in border-t border-white/[0.04] bg-ink-900/30 px-5 py-3 pl-11">
          <p className="text-xs text-slate-500">
            <span className="font-semibold text-slate-400">Score base:</span>{' '}
            {criterion.base_score != null ? Math.round(criterion.base_score) : '—'} &nbsp;·&nbsp;
            <span className="font-semibold text-slate-400">Score final:</span>{' '}
            {score != null ? Math.round(score) : '—'} &nbsp;·&nbsp;
            <span className="font-semibold text-slate-400">Evidencias:</span>{' '}
            {criterion.evidence_ids.length}
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-500">{criterion.explanation}</p>
        </div>
      )}
    </div>
  );
}
