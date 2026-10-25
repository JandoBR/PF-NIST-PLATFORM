import { useEffect, useMemo, useState } from 'react';
import {
  Gauge,
  Target,
  ShieldQuestion,
  Filter,
  Search,
  ChevronRight,
  Info,
  Lock,
  Library,
} from 'lucide-react';
import { downloadExecutiveReport, getMethodology } from '@/lib/api';
import type {
  AssessmentDetail,
  CriterionResult,
  Estado,
  ImplementationCoverage,
} from '@/lib/types';
import { DownloadPdfButton } from '@/components/DownloadPdfButton';
import { FUNCTION_NAMES, FUNCTION_ORDER, TIER_LABELS } from '@/lib/types';
import {
  ESTADO_META,
  FUNCTION_ACCENTS,
  PRIVACY_CRITERIA,
  PRIVACY_RELATION,
  PRIVACY_SCOPE_NOTE,
} from '@/lib/ui';

type TableMode = 'criteria' | 'privacy';

interface DashboardProps {
  assessment: AssessmentDetail;
  criteria: CriterionResult[];
}

const FILTERS: { key: Estado | 'all'; label: string }[] = [
  { key: 'all', label: 'Todos' },
  { key: 'evaluado', label: 'Evaluado' },
  { key: 'no_implementado', label: 'Ausente o fallido' },
  { key: 'evidencia_insuficiente', label: 'Evidencia insuficiente' },
  { key: 'no_aplicable', label: 'No aplicable' },
  { key: 'error', label: 'Error' },
];

export function MaturityDashboard({ assessment, criteria }: DashboardProps) {
  const [estadoFilter, setEstadoFilter] = useState<Estado | 'all'>('all');
  const [funcFilter, setFuncFilter] = useState<string>('all');
  const [query, setQuery] = useState('');
  const [tableMode, setTableMode] = useState<TableMode>('criteria');
  // Cobertura DEL CATALOGO (AMP-04): metadato del producto, constante para esta version de
  // metodologia, asi que se pide una sola vez y no depende de la evaluacion que se este viendo.
  // Si falla, la seccion no se pinta: es metadato y nunca debe tumbar la matriz.
  const [coverage, setCoverage] = useState<ImplementationCoverage | null>(null);

  useEffect(() => {
    let vigente = true;
    getMethodology()
      .then((m) => vigente && setCoverage(m.cobertura_implementacion))
      .catch(() => undefined);
    return () => {
      vigente = false;
    };
  }, []);

  // Las 6 funciones de CSF 2.0 siempre se muestran: una sin criterios implementados aparece como
  // "sin criterios" en vez de desaparecer (docs/11 §C, cobertura IDENTIFY = 0).
  const functionScores = useMemo(() => {
    const byRef = new Map(assessment.agregados_funcion.map((a) => [a.ref, a]));
    return FUNCTION_ORDER.map((key) => ({
      key,
      name: FUNCTION_NAMES[key] ?? key,
      accent: FUNCTION_ACCENTS[key] ?? '#94a3b8',
      aggregate: byRef.get(key) ?? null,
    }));
  }, [assessment.agregados_funcion]);

  const privacy = useMemo(() => criteria.filter((c) => PRIVACY_CRITERIA.has(c.criterion_id)), [criteria]);

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
      <div className="flex items-start justify-between gap-4">
        <p className="text-xs text-slate-500">
          {assessment.estado === 'en_progreso' || assessment.estado === 'pendiente'
            ? 'Evaluación en curso…'
            : `Evaluación ${assessment.estado}`}
          {assessment.reproducibility && (
            <span className="ml-2 text-slate-600">
              ·{' '}
              {assessment.reproducibility.ai
                ? `IA: ${Object.entries(assessment.reproducibility.ai)
                    .map(([k, v]) => (k === 'modelo' ? v : `${k} ${v}`))
                    .join(' · ')}`
                : 'Sin IA (determinista)'}
            </span>
          )}
        </p>
        <DownloadPdfButton
          label="Informe PDF"
          onDownload={() => downloadExecutiveReport(assessment.id)}
          disabled={assessment.estado !== 'completada'}
          disabledReason="El informe está disponible cuando la evaluación termina."
        />
      </div>

      {/* Tarjetas de resumen */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={<Gauge className="h-5 w-5" />}
          accent="cyan"
          label="Score Global"
          value={assessment.score_global != null ? `${Math.round(assessment.score_global)}` : '—'}
          sub={
            assessment.provisional_global
              ? 'Provisional: cobertura baja, no representa a toda la organización'
              : 'Promedio ponderado por criterio'
          }
        />
        <SummaryCard
          icon={<Target className="h-5 w-5" />}
          accent="indigo"
          label="Cobertura de evidencia"
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
            const score = f.aggregate?.score ?? null;
            const isEmpty = f.aggregate === null;
            return (
              <div
                key={f.key}
                className={`rounded-xl border border-white/[0.06] bg-ink-900/40 p-4 transition-colors ${
                  isEmpty ? 'border-dashed' : 'hover:border-white/15'
                }`}
              >
                <div className="mb-3 flex items-center justify-between">
                  <span
                    className="rounded-md px-2 py-0.5 text-xs font-bold"
                    style={{ backgroundColor: `${f.accent}1a`, color: f.accent }}
                  >
                    {f.key}
                  </span>
                  {isEmpty ? (
                    <span className="chip border border-white/10 bg-white/[0.03] text-[11px] text-slate-500">
                      Sin criterios
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5">
                      {f.aggregate!.provisional && (
                        <span
                          className="chip border border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300"
                          title="Cobertura baja: el score solo describe los criterios con evidencia suficiente"
                        >
                          Provisional
                        </span>
                      )}
                      <span className="text-lg font-bold text-white">
                        {score != null ? Math.round(score) : '—'}
                      </span>
                    </span>
                  )}
                </div>
                <p className="mb-2.5 text-xs font-medium text-slate-300">{f.name}</p>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                  {!isEmpty && (
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{ width: `${score ?? 0}%`, backgroundColor: f.accent }}
                    />
                  )}
                </div>
                <p className="mt-2 text-[11px] text-slate-600">
                  {isEmpty
                    ? 'Aún sin criterios implementados'
                    : `Cobertura ${f.aggregate!.cobertura != null ? `${Math.round(f.aggregate!.cobertura * 100)}%` : '—'}`}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Cobertura del catalogo (AMP-04, docs/01 §7): mide la herramienta, no esta evaluacion */}
      {coverage && <CatalogCoverage coverage={coverage} />}

      {/* Criterios evaluados, con una vista alterna de privacidad (docs/03 §7) */}
      <div className="card overflow-hidden">
        <div className="flex flex-col gap-4 border-b border-white/[0.06] p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              {tableMode === 'criteria' ? (
                <Filter className="h-4 w-4 text-slate-500" />
              ) : (
                <Lock className="h-4 w-4 text-teal-300" />
              )}
              <h3 className="text-sm font-semibold text-white">
                {tableMode === 'criteria' ? 'Criterios Evaluados' : 'Privacidad relacionada con ciberseguridad'}
              </h3>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500">
                {tableMode === 'criteria' ? `${filtered.length} de ${criteria.length}` : `${privacy.length} del cruce`}
              </span>
              <ViewSwitch mode={tableMode} onChange={setTableMode} />
            </div>
          </div>

          {tableMode === 'criteria' && (
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
          )}
        </div>

        {tableMode === 'criteria' ? (
          <div className="divide-y divide-white/[0.04]">
            {filtered.length === 0 ? (
              <div className="px-5 py-12 text-center text-sm text-slate-500">
                No hay criterios que coincidan con los filtros actuales.
              </div>
            ) : (
              filtered.map((c) => <CriterionRow key={c.criterion_id} criterion={c} />)
            )}
          </div>
        ) : (
          <PrivacyView criteria={privacy} />
        )}
      </div>
    </div>
  );
}

function ViewSwitch({ mode, onChange }: { mode: TableMode; onChange: (mode: TableMode) => void }) {
  return (
    <div className="flex rounded-lg border border-white/[0.06] bg-ink-900/60 p-1">
      <button
        onClick={() => onChange('criteria')}
        className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
          mode === 'criteria' ? 'bg-white/[0.08] text-white' : 'text-slate-500 hover:text-slate-300'
        }`}
      >
        Criterios
      </button>
      <button
        onClick={() => onChange('privacy')}
        className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
          mode === 'privacy' ? 'bg-teal-500/15 text-teal-200' : 'text-slate-500 hover:text-slate-300'
        }`}
      >
        <Lock className="h-3.5 w-3.5" />
        Privacidad
      </button>
    </div>
  );
}

/** Vista alterna de la tabla de criterios: el cruce con privacidad (docs/03 §7). No es un filtro:
 * cambia las columnas para mostrar la relación con el Privacy Framework y la nota de alcance. */
function PrivacyView({ criteria }: { criteria: CriterionResult[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const evaluados = criteria.filter((c) => c.estado === 'evaluado').length;
  const scored = criteria.filter((c) => c.final_score != null);
  const avg = scored.length > 0 ? scored.reduce((n, c) => n + (c.final_score ?? 0), 0) / scored.length : null;
  const cobertura = criteria.length > 0 ? evaluados / criteria.length : null;

  if (criteria.length === 0) {
    return (
      <div className="px-5 py-12 text-center text-sm text-slate-500">
        Ninguno de los criterios del cruce con privacidad está presente en esta evaluación todavía.
      </div>
    );
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-white/[0.06] bg-teal-500/[0.03] px-5 py-3.5">
        <div className="flex items-center gap-2">
          <PrivacyStat label="Score" value={avg != null ? `${Math.round(avg)}` : '—'} />
          <PrivacyStat label="Cobertura" value={cobertura != null ? `${Math.round(cobertura * 100)}%` : '—'} />
          <PrivacyStat label="Criterios" value={`${criteria.length}`} />
        </div>
        <p className="flex min-w-[240px] flex-1 items-start gap-1.5 text-xs text-slate-500">
          <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-teal-400/70" />
          {PRIVACY_SCOPE_NOTE}
        </p>
      </div>

      <div className="flex items-center gap-4 border-b border-white/[0.04] px-5 py-2 text-[11px] font-medium uppercase tracking-wide text-slate-600">
        <span className="w-24 flex-shrink-0">Criterio</span>
        <span className="w-40 flex-shrink-0">Relación PF/CSF</span>
        <span className="flex-1">Detalle</span>
        <span className="w-10 flex-shrink-0 text-right">Score</span>
        <span className="w-28 flex-shrink-0 text-right">Estado</span>
      </div>
      <div className="divide-y divide-white/[0.04]">
        {criteria.map((c) => {
          const meta = ESTADO_META[c.estado];
          const expanded = open === c.criterion_id;
          return (
            <div key={c.criterion_id}>
              <button
                onClick={() => setOpen(expanded ? null : c.criterion_id)}
                className="flex w-full items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-white/[0.02]"
              >
                <span className="w-24 flex-shrink-0 font-mono text-xs font-semibold text-slate-300">
                  {c.criterion_id}
                </span>
                <span className="w-40 flex-shrink-0">
                  <span className="chip border border-teal-500/30 bg-teal-500/10 text-teal-300">
                    {PRIVACY_RELATION[c.criterion_id] ?? 'Privacidad'}
                  </span>
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-slate-400">{c.explanation}</span>
                <span className="w-10 flex-shrink-0 text-right text-xs font-semibold text-slate-400">
                  {c.final_score != null ? Math.round(c.final_score) : '—'}
                </span>
                <span className="w-28 flex-shrink-0 text-right">
                  <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
                </span>
                <ChevronRight
                  className={`h-4 w-4 flex-shrink-0 text-slate-600 transition-transform ${expanded ? 'rotate-90' : ''}`}
                />
              </button>
              {expanded && (
                <div className="animate-fade-in border-t border-white/[0.04] bg-ink-900/30 px-5 py-3">
                  <p className="text-xs leading-relaxed text-slate-400">{c.explanation}</p>
                  <p className="mt-2 text-xs text-slate-500">
                    <span className="font-semibold text-slate-400">Score base:</span>{' '}
                    {c.base_score != null ? Math.round(c.base_score) : '—'} &nbsp;·&nbsp;
                    <span className="font-semibold text-slate-400">Score final:</span>{' '}
                    {c.final_score != null ? Math.round(c.final_score) : '—'} &nbsp;·&nbsp;
                    <span className="font-semibold text-slate-400">Evidencias:</span> {c.evidence_ids.length}
                    {c.degradado && <span className="text-amber-300"> &nbsp;·&nbsp; IA degradada</span>}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

function PrivacyStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-ink-900/40 px-3 py-1.5 text-center">
      <p className="text-sm font-bold text-white">{value}</p>
      <p className="text-[11px] text-slate-500">{label}</p>
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

function CatalogCoverage({ coverage }: { coverage: ImplementationCoverage }) {
  const pct = Math.round(coverage.ratio * 100);
  const completo = coverage.categorias_sin_criterio.length === 0;

  return (
    <div className="card p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-violet-500/10 text-violet-300 ring-1 ring-violet-500/20">
            <Library className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Cobertura del catálogo NIST CSF 2.0</h3>
            <p className="max-w-xl text-xs leading-relaxed text-slate-500">
              Qué parte del marco tiene al menos un criterio que la evalúe. Describe la{' '}
              <span className="text-slate-400">herramienta</span>, no esta evaluación: la cobertura
              de esta corrida es la tarjeta «Cobertura de evidencia», y las dos no se mezclan.
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold tracking-tight text-white">{pct}%</p>
          <p
            className="text-[11px] text-slate-500"
            title="Subcategorías del CSF 2.0 con al menos un criterio en el catálogo"
          >
            {coverage.subcategorias_cubiertas} de {coverage.subcategorias_totales} subcategorías
          </p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {FUNCTION_ORDER.map((key) => {
          const [cubiertas, totales] = coverage.por_funcion[key] ?? [0, 0];
          const accent = FUNCTION_ACCENTS[key] ?? '#94a3b8';
          const ancho = totales > 0 ? (cubiertas / totales) * 100 : 0;
          const funcionCompleta = totales > 0 && cubiertas === totales;
          return (
            <div
              key={key}
              className={`rounded-lg border bg-ink-900/40 p-3 ${
                funcionCompleta ? 'border-emerald-500/30' : 'border-white/[0.06]'
              }`}
              title={
                funcionCompleta
                  ? `Función ${key} completa: sus ${totales} subcategorías tienen criterio`
                  : `${totales - cubiertas} subcategorías de ${key} todavía sin criterio`
              }
            >
              <div className="mb-2 flex items-baseline justify-between">
                <span className="text-xs font-bold" style={{ color: accent }}>
                  {key}
                </span>
                <span
                  className={`text-xs ${funcionCompleta ? 'text-emerald-300' : 'text-slate-400'}`}
                >
                  {cubiertas}/{totales}
                </span>
              </div>
              <div className="h-1 w-full overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{ width: `${ancho}%`, backgroundColor: accent }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-4">
        <span className="text-xs text-slate-500">
          Categorías con criterio:{' '}
          <span className="font-semibold text-slate-300">
            {coverage.categorias_cubiertas} de {coverage.categorias_totales}
          </span>
        </span>
        <span
          className="text-xs text-slate-500"
          title="Categorías con TODAS sus subcategorías declaradas, no solo con alguna"
        >
          · completas:{' '}
          <span className="font-semibold text-slate-300">
            {coverage.categorias_completas} de {coverage.categorias_totales}
          </span>
        </span>
        {completo ? (
          <span className="chip border border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
            Las {coverage.categorias_totales} categorías del marco están representadas
          </span>
        ) : (
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-slate-500">· sin ningún criterio todavía:</span>
            {coverage.categorias_sin_criterio.map((c) => (
              <span
                key={c}
                className="chip border border-white/10 bg-white/[0.03] font-mono text-[11px] text-slate-400"
              >
                {c}
              </span>
            ))}
          </span>
        )}
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
          {PRIVACY_CRITERIA.has(criterion.criterion_id) && (
            <span
              className="chip flex-shrink-0 border border-teal-500/30 bg-teal-500/10 text-teal-300"
              title="Criterio del cruce con privacidad (docs/03 §7)"
            >
              Privacidad
            </span>
          )}
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
