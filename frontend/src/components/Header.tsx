import { ShieldCheck, Settings2, Activity, Brain } from 'lucide-react';

interface HeaderProps {
  activeArchName: string | null;
  onOpenSelector: () => void;
}

export function Header({ activeArchName, onOpenSelector }: HeaderProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-ink-950/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500/20 to-indigo-500/20 ring-1 ring-cyan-500/30">
            <ShieldCheck className="h-5 w-5 text-cyan-300" strokeWidth={2.2} />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-bold tracking-tight text-white sm:text-base">
              Plataforma de Madurez de Seguridad y Recomendaciones NIST CSF 2.0
            </h1>
            <p className="hidden text-xs text-slate-500 sm:block">
              Evaluación de postura híbrida basada en reglas y contextualizada por IA
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <div className="hidden items-center gap-4 rounded-lg border border-white/[0.06] bg-ink-900/60 px-3.5 py-2 md:flex">
            <Stat icon={<Activity className="h-3.5 w-3.5 text-emerald-400" />} label="Motor de Reglas" value="En línea" />
            <span className="h-4 w-px bg-white/10" />
            <Stat icon={<Brain className="h-3.5 w-3.5 text-cyan-400" />} label="Capa de IA" value="Listo" />
          </div>

          <button onClick={onOpenSelector} className="btn-ghost border border-white/[0.06] bg-ink-900/60">
            <Settings2 className="h-4 w-4" />
            <span className="hidden sm:inline">
              {activeArchName ? 'Cambiar Arquitectura' : 'Seleccionar Arquitectura'}
            </span>
            <span className="sm:hidden">Contexto</span>
          </button>
        </div>
      </div>
    </header>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5">
      {icon}
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs font-semibold text-slate-200">{value}</span>
    </div>
  );
}