import { useMemo, useState } from 'react';
import {
  Gauge,
  Target,
  TrendingDown,
  Filter,
  Search,
  ChevronRight,
} from 'lucide-react';
import {
  FUNCTIONS,
  SUBCATEGORIES,
  TIER_LABELS,
  type Architecture,
  type Subcategory,
  type Status,
} from '@/data/mockData';
import { STATUS_META } from '@/lib/ui';

interface DashboardProps {
  arch: Architecture;
}

const FILTERS: { key: Status | 'all'; label: string }[] = [
  { key: 'all', label: 'Todos' },
  { key: 'compliant', label: 'Conforme' },
  { key: 'partial', label: 'Brecha Parcial' },
  { key: 'critical', label: 'Brecha Crítica' },
];

export function MaturityDashboard({ arch }: DashboardProps) {
  const [statusFilter, setStatusFilter] = useState<Status | 'all'>('all');
  const [funcFilter, setFuncFilter] = useState<string>('all');
  const [query, setQuery] = useState('');

  const functionScores = useMemo(() => {
    const map = new Map<string, { total: number; count: number }>();
    for (const s of SUBCATEGORIES) {
      const cur = map.get(s.function) ?? { total: 0, count: 0 };
      cur.total += s.score;
      cur.count += 1;
      map.set(s.function, cur);
    }
    return FUNCTIONS.map((f) => ({
      ...f,
      score: Math.round((map.get(f.key)?.total ?? 0) / (map.get(f.key)?.count ?? 1)),
    }));
  }, []);

  const overallScore = Math.round(
    functionScores.reduce((a, f) => a + f.score, 0) / functionScores.length
  );
  const gapScore = 100 - overallScore;

  const filtered = useMemo(() => {
    return SUBCATEGORIES.filter((s) => {
      if (statusFilter !== 'all' && s.status !== statusFilter) return false;
      if (funcFilter !== 'all' && s.function !== funcFilter) return false;
      if (query) {
        const q = query.toLowerCase();
        if (!s.id.toLowerCase().includes(q) && !s.label.toLowerCase().includes(q))
          return false;
      }
      return true;
    });
  }, [statusFilter, funcFilter, query]);

  return (
    <div className="space-y-6">
      {/* Tarjetas de resumen */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={<Gauge className="h-5 w-5" />}
          accent="cyan"
          label="Nivel Actual"
          value={`Nivel ${arch.currentTier}`}
          sub={TIER_LABELS[arch.currentTier - 1]}
        />
        <SummaryCard
          icon={<Target className="h-5 w-5" />}
          accent="indigo"
          label="Nivel Objetivo"
          value={`Nivel ${arch.targetTier}`}
          sub={TIER_LABELS[arch.targetTier - 1]}
        />
        <SummaryCard
          icon={<TrendingDown className="h-5 w-5" />}
          accent="amber"
          label="Puntaje Total de Brecha"
          value={`${gapScore}`}
          sub={`${overallScore}/100 actual`}
        />
        <SummaryCard
          icon={<Gauge className="h-5 w-5" />}
          accent="emerald"
          label="Madurez General"
          value={`${overallScore}%`}
          sub="En 6 funciones"
        />
      </div>

      {/* Matriz de funciones */}
      <div className="card p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-white">Matriz de Madurez NIST CSF 2.0</h3>
            <p className="text-xs text-slate-500">Postura a nivel de función a lo largo del marco de trabajo</p>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {functionScores.map((f) => (
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
                <span className="text-lg font-bold text-white">{f.score}</span>
              </div>
              <p className="mb-2.5 text-xs font-medium text-slate-300">{f.name}</p>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{ width: `${f.score}%`, backgroundColor: f.accent }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tabla de subcategorías */}
      <div className="card overflow-hidden">
        <div className="flex flex-col gap-4 border-b border-white/[0.06] p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-slate-500" />
              <h3 className="text-sm font-semibold text-white">Subcategorías Evaluadas</h3>
            </div>
            <span className="text-xs text-slate-500">{filtered.length} de {SUBCATEGORIES.length}</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Filtro por función */}
            <div className="flex flex-wrap gap-1.5">
              <Chip active={funcFilter === 'all'} onClick={() => setFuncFilter('all')}>
                Todas las Funciones
              </Chip>
              {FUNCTIONS.map((f) => (
                <Chip
                  key={f.key}
                  active={funcFilter === f.key}
                  onClick={() => setFuncFilter(f.key)}
                  accent={f.accent}
                >
                  {f.key}
                </Chip>
              ))}
            </div>

            {/* Filtro por estado */}
            <div className="flex flex-wrap gap-1.5">
              {FILTERS.map((f) => (
                <Chip key={f.key} active={statusFilter === f.key} onClick={() => setStatusFilter(f.key)}>
                  {f.label}
                </Chip>
              ))}
            </div>

            {/* Búsqueda */}
            <div className="relative ml-auto">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-600" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar subcategoría..."
                className="w-44 rounded-lg border border-white/10 bg-ink-900/60 py-1.5 pl-8 pr-3 text-xs text-slate-200 placeholder-slate-600 outline-none focus:border-cyan-500/50 sm:w-56"
              />
            </div>
          </div>
        </div>

        <div className="divide-y divide-white/[0.04]">
          {filtered.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-slate-500">
              No hay subcategorías que coincidan con los filtros actuales.
            </div>
          ) : (
            filtered.map((s) => <SubcategoryRow key={s.id} sub={s} />)
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
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className="mt-1.5 text-2xl font-bold tracking-tight text-white">{value}</p>
          <p className="mt-0.5 text-xs text-slate-500">{sub}</p>
        </div>
        <div className={`flex h-10 w-10 items-center justify-center rounded-xl ring-1 ${colors[accent]}`}>
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
        active
          ? accent
            ? ''
            : 'bg-white/[0.08] text-white'
          : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  );
}

function SubcategoryRow({ sub }: { sub: Subcategory }) {
  const meta = STATUS_META[sub.status];
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-white/[0.02]"
      >
        <span className={`h-2 w-2 flex-shrink-0 rounded-full ${meta.dot}`} />
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="flex-shrink-0 font-mono text-xs font-semibold text-slate-300">{sub.id}</span>
          <span className="truncate text-sm text-slate-400">{sub.label}</span>
        </div>
        <div className="hidden w-32 sm:block">
          <div className="flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
              <div
                className={`h-full rounded-full ${meta.bar} transition-all duration-500`}
                style={{ width: `${sub.score}%` }}
              />
            </div>
            <span className="w-8 text-right text-xs font-semibold text-slate-400">{sub.score}</span>
          </div>
        </div>
        <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
        <ChevronRight
          className={`h-4 w-4 flex-shrink-0 text-slate-600 transition-transform ${open ? 'rotate-90' : ''}`}
        />
      </button>
      {open && (
        <div className="animate-fade-in border-t border-white/[0.04] bg-ink-900/30 px-5 py-3 pl-11">
          <p className="text-xs text-slate-500">
            <span className="font-semibold text-slate-400">Función:</span> {sub.function} &nbsp;·&nbsp;
            <span className="font-semibold text-slate-400">Puntaje:</span> {sub.score}/100 &nbsp;·&nbsp;
            <span className="font-semibold text-slate-400">Estado:</span> {meta.label}
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
            {sub.status === 'compliant'
              ? 'La evidencia del control se mantiene y valida constantemente. Continúe con la revisión periódica para mantener la postura.'
              : sub.status === 'partial'
              ? 'El control está implementado parcialmente. Existen brechas de evidencia; priorice la remediación para cerrarlas.'
              : 'El control está ausente o es ineficaz. Se requiere remediación inmediata para reducir el riesgo organizacional.'}
          </p>
        </div>
      )}
    </div>
  );
}