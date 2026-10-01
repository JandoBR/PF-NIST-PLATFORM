import { useState } from 'react';
import {
  Brain,
  Cpu,
  ArrowLeftRight,
  Sparkles,
  Route,
  ListChecks,
  CircleDot,
} from 'lucide-react';
import { RECOMMENDATIONS, type Recommendation, type Priority } from '@/data/mockData';
import { PRIORITY_META } from '@/lib/ui';

type View = 'compare' | 'roadmap';

export function RecommendationEngine() {
  const [view, setView] = useState<View>('compare');
  const [priorityFilter, setPriorityFilter] = useState<Priority | 'all'>('all');

  const roadmap = RECOMMENDATIONS.filter(
    (r) => priorityFilter === 'all' || r.priority === priorityFilter
  );
  const priorityOrder: Priority[] = ['high', 'medium', 'low'];

  return (
    <div className="space-y-6">
      {/* Encabezado de sección + selector de vista */}
      <div className="card p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500/15 to-indigo-500/15 ring-1 ring-cyan-500/20">
              <Brain className="h-5 w-5 text-cyan-300" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Motor de Recomendaciones Híbrido</h3>
              <p className="text-xs text-slate-500">
                Base basada en reglas enriquecida con orientación contextualizada por IA
              </p>
            </div>
          </div>

          <div className="flex rounded-lg border border-white/[0.06] bg-ink-900/60 p-1">
            <ToggleBtn active={view === 'compare'} onClick={() => setView('compare')}>
              <ArrowLeftRight className="h-3.5 w-3.5" />
              Base vs IA
            </ToggleBtn>
            <ToggleBtn active={view === 'roadmap'} onClick={() => setView('roadmap')}>
              <Route className="h-3.5 w-3.5" />
              Plan de Acción
            </ToggleBtn>
          </div>
        </div>
      </div>

      {view === 'compare' ? (
        <CompareView />
      ) : (
        <div className="space-y-4">
          {/* Filtro de prioridad */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex items-center gap-1.5 text-xs text-slate-500">
              <ListChecks className="h-3.5 w-3.5" /> Filtrar:
            </span>
            {(['all', 'high', 'medium', 'low'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPriorityFilter(p)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  priorityFilter === p
                    ? 'bg-white/[0.08] text-white'
                    : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-300'
                }`}
              >
                {p === 'all' ? 'Todas' : PRIORITY_META[p].label}
              </button>
            ))}
          </div>

          {roadmap.length === 0 ? (
            <div className="card px-5 py-12 text-center text-sm text-slate-500">
              No hay recomendaciones en este nivel de prioridad.
            </div>
          ) : (
            roadmap
              .sort((a, b) => priorityOrder.indexOf(a.priority) - priorityOrder.indexOf(b.priority))
              .map((r, i) => <RoadmapCard key={r.subcategory} rec={r} index={i + 1} />)
          )}
        </div>
      )}
    </div>
  );
}

function CompareView() {
  const [selected, setSelected] = useState(0);
  const rec = RECOMMENDATIONS[selected];

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      {/* Lista */}
      <div className="card max-h-[560px] overflow-y-auto p-2">
        {RECOMMENDATIONS.map((r, i) => (
          <button
            key={r.subcategory}
            onClick={() => setSelected(i)}
            className={`mb-1 flex w-full items-start gap-3 rounded-lg p-3 text-left transition-colors ${
              selected === i
                ? 'bg-white/[0.06] ring-1 ring-cyan-500/30'
                : 'hover:bg-white/[0.03]'
            }`}
          >
            <CircleDot
              className={`mt-0.5 h-3.5 w-3.5 flex-shrink-0 ${
                r.priority === 'high'
                  ? 'text-rose-400'
                  : r.priority === 'medium'
                  ? 'text-amber-400'
                  : 'text-sky-400'
              }`}
            />
            <div className="min-w-0">
              <p className="font-mono text-[10px] text-slate-500">{r.subcategory}</p>
              <p className="text-xs font-medium leading-snug text-slate-200">{r.title}</p>
            </div>
          </button>
        ))}
      </div>

      {/* Comparativa */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Base */}
        <div className="card flex flex-col p-5">
          <div className="mb-4 flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-500/10 ring-1 ring-slate-500/20">
              <Cpu className="h-4 w-4 text-slate-400" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-slate-200">Recomendación Base (Reglas)</h4>
              <p className="text-xs text-slate-500">Determinista · genérica</p>
            </div>
          </div>
          <p className="font-mono text-[11px] text-slate-600">{rec.subcategory}</p>
          <p className="mt-1 text-sm font-medium text-slate-300">{rec.title}</p>
          <div className="mt-3 flex-1 rounded-lg border border-white/[0.04] bg-ink-900/40 p-4">
            <p className="text-sm leading-relaxed text-slate-400">{rec.base}</p>
          </div>
        </div>

        {/* IA */}
        <div className="card relative flex flex-col overflow-hidden p-5">
          <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-cyan-500/[0.07] blur-3xl" />
          <div className="mb-4 flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/10 ring-1 ring-cyan-500/30">
              <Sparkles className="h-4 w-4 text-cyan-300" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white">Recomendación Contextualizada por IA</h4>
              <p className="text-xs text-cyan-400/70">Enriquecida con RAG · adaptada a la arquitectura</p>
            </div>
          </div>
          <p className="font-mono text-[11px] text-slate-600">{rec.subcategory}</p>
          <p className="mt-1 text-sm font-medium text-slate-200">{rec.title}</p>
          <div className="mt-3 flex-1 rounded-lg border border-cyan-500/15 bg-cyan-500/[0.03] p-4">
            <p className="text-sm leading-relaxed text-slate-200">{rec.ai}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function RoadmapCard({ rec, index }: { rec: Recommendation; index: number }) {
  const meta = PRIORITY_META[rec.priority];
  return (
    <div className="card card-hover animate-slide-up p-5" style={{ animationDelay: `${index * 40}ms` }}>
      <div className="flex items-start gap-4">
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-white/[0.04] text-sm font-bold text-slate-400">
          {index}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
            <span className="font-mono text-xs text-slate-600">{rec.subcategory}</span>
          </div>
          <h4 className="mt-2 text-sm font-semibold text-white">{rec.title}</h4>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">{rec.ai}</p>
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