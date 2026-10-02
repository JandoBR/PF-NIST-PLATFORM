import { useEffect, useState } from 'react';
import { ShieldCheck, Settings2, LogOut, ListChecks, Loader2 } from 'lucide-react';
import { listJobs } from '@/lib/api';
import type { AuthUser } from '@/lib/api';

interface HeaderProps {
  onOpenSelector: () => void;
  user: AuthUser | null;
  onLogout: () => void;
  /** Abre (o cierra) el historial de actividad en segundo plano. */
  onToggleJobs: () => void;
  jobsOpen: boolean;
}

export function Header({ onOpenSelector, user, onLogout, onToggleJobs, jobsOpen }: HeaderProps) {
  const [activeJobs, setActiveJobs] = useState(0);

  // Cuenta lo que está en curso para que el botón avise sin abrir la vista. Si la API no
  // responde se deja el último valor: los errores de conexión ya se muestran donde se usan.
  useEffect(() => {
    if (!user) return;
    let active = true;
    const check = () => {
      listJobs({ limit: 50 })
        .then((jobs) => {
          if (active) setActiveJobs(jobs.filter((j) => j.estado === 'pendiente' || j.estado === 'en_progreso').length);
        })
        .catch(() => undefined);
    };
    check();
    const interval = window.setInterval(check, 10000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [user]);

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
              Evaluación de postura basada en reglas, contextualizada por IA
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <button
            onClick={onToggleJobs}
            title="Actividad en segundo plano"
            aria-pressed={jobsOpen}
            className={`btn-ghost border ${
              jobsOpen
                ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
                : 'border-white/[0.06] bg-ink-900/60'
            }`}
          >
            {activeJobs > 0 ? (
              <Loader2 className="h-4 w-4 animate-spin text-cyan-300" />
            ) : (
              <ListChecks className="h-4 w-4" />
            )}
            <span className="hidden sm:inline">Actividad</span>
            {activeJobs > 0 && (
              <span className="rounded-full bg-cyan-500/20 px-1.5 text-xs font-semibold text-cyan-200">
                {activeJobs}
              </span>
            )}
          </button>

          {user && (
            <div className="hidden items-center gap-2 rounded-lg border border-white/[0.06] bg-ink-900/60 px-3 py-1.5 sm:flex">
              <span className="max-w-[10rem] truncate text-xs font-medium text-slate-200">
                {user.org_nombre}
              </span>
              <span className="text-xs text-slate-500">·</span>
              <span className="text-xs text-slate-400">{user.username}</span>
            </div>
          )}

          <button onClick={onOpenSelector} className="btn-ghost border border-white/[0.06] bg-ink-900/60">
            <Settings2 className="h-4 w-4" />
            <span className="hidden sm:inline">Nueva Evaluación</span>
            <span className="sm:hidden">Evaluar</span>
          </button>

          <button
            onClick={onLogout}
            title="Cerrar sesión"
            className="rounded-lg border border-white/[0.06] bg-ink-900/60 p-2 text-slate-400 transition-colors hover:text-rose-300"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
