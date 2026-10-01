import { useState } from 'react';
import {
  Activity,
  ShieldAlert,
  Radio,
  ArrowRight,
  Crosshair,
  Clock,
  X,
  CheckCircle2,
} from 'lucide-react';
import { THREAT_EVENTS, type ThreatEvent } from '@/data/mockData';
import { SEVERITY_META } from '@/lib/ui';

export function ThreatSimulation() {
  const [selected, setSelected] = useState<ThreatEvent | null>(null);

  return (
    <div className="space-y-6">
      {/* Banner en vivo */}
      <div className="card flex items-center justify-between p-4">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 ring-1 ring-emerald-500/20">
            <Radio className="h-5 w-5 text-emerald-400" />
            <span className="absolute inset-0 rounded-xl ring-2 ring-emerald-400/40 animate-pulse-ring" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Flujo de Eventos Simulados</h3>
            <p className="text-xs text-slate-500">Telemetría de detección en tiempo real · últimas 24h</p>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] px-3 py-1.5">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          <span className="text-xs font-medium text-emerald-300">Monitoreando</span>
        </div>
      </div>

      {/* Registro de eventos */}
      <div className="card overflow-hidden">
        <div className="flex items-center gap-2 border-b border-white/[0.06] px-5 py-3.5">
          <Activity className="h-4 w-4 text-slate-500" />
          <h3 className="text-sm font-semibold text-white">Registro de Detección</h3>
          <span className="ml-auto text-xs text-slate-500">{THREAT_EVENTS.length} eventos</span>
        </div>
        <div className="divide-y divide-white/[0.04]">
          {THREAT_EVENTS.map((evt) => {
            const meta = SEVERITY_META[evt.severity];
            return (
              <button
                key={evt.id}
                onClick={() => setSelected(evt)}
                className="group flex w-full items-center gap-4 px-5 py-3.5 text-left transition-colors hover:bg-white/[0.02]"
              >
                <span className="font-mono text-xs text-slate-600">{evt.time}</span>
                <span className={`h-2 w-2 flex-shrink-0 rounded-full ${meta.dot}`} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-200">{evt.title}</p>
                  <p className="truncate text-xs text-slate-500">{evt.source}</p>
                </div>
                <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
                <ArrowRight className="h-4 w-4 flex-shrink-0 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-slate-400" />
              </button>
            );
          })}
        </div>
      </div>

      {/* Panel lateral de respuesta a incidentes */}
      {selected && (
        <IncidentDrawer event={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function IncidentDrawer({ event, onClose }: { event: ThreatEvent; onClose: () => void }) {
  const meta = SEVERITY_META[event.severity];
  const [checked, setChecked] = useState<Set<number>>(new Set());

  const toggle = (i: number) =>
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm animate-fade-in" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-lg animate-slide-up flex-col border-l border-white/[0.08] bg-ink-900 shadow-2xl">
        {/* Encabezado */}
        <div className="flex items-start justify-between border-b border-white/[0.06] p-5">
          <div className="flex items-start gap-3">
            <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${meta.bg} ring-1 ${meta.border}`}>
              <ShieldAlert className="h-5 w-5 text-rose-300" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">{event.title}</h3>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span className={`chip ${meta.bg} ${meta.text} ${meta.border} border`}>{meta.label}</span>
                <span className="flex items-center gap-1 text-xs text-slate-500">
                  <Clock className="h-3 w-3" /> {event.time}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Cuerpo */}
        <div className="flex-1 overflow-y-auto p-5">
          {/* Detalles */}
          <div className="rounded-lg border border-white/[0.06] bg-ink-850/60 p-4">
            <p className="text-xs font-medium text-slate-500">Detalle de la Detección</p>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-300">{event.detail}</p>
            <div className="mt-3 flex items-center gap-2 border-t border-white/[0.06] pt-3">
              <Crosshair className="h-3.5 w-3.5 text-rose-400" />
              <span className="text-xs text-slate-500">MITRE ATT&amp;CK</span>
              <span className="font-mono text-xs text-slate-300">{event.mitre}</span>
            </div>
          </div>

          {/* Pasos de respuesta */}
          <div className="mt-5">
            <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
              Estrategia Guiada de Respuesta a Incidentes
            </h4>
            <div className="space-y-2.5">
              {event.steps.map((step, i) => {
                const done = checked.has(i);
                return (
                  <button
                    key={i}
                    onClick={() => toggle(i)}
                    className={`flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-all ${
                      done
                        ? 'border-emerald-500/20 bg-emerald-500/[0.04]'
                        : 'border-white/[0.06] bg-ink-850/40 hover:border-white/15'
                    }`}
                  >
                    <div
                      className={`mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-md border transition-colors ${
                        done
                          ? 'border-emerald-500/40 bg-emerald-500/15'
                          : 'border-white/15'
                      }`}
                    >
                      {done && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                    </div>
                    <p
                      className={`text-sm leading-relaxed ${
                        done ? 'text-slate-500 line-through' : 'text-slate-300'
                      }`}
                    >
                      {step}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Pie de página */}
        <div className="border-t border-white/[0.06] p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">
              {checked.size} de {event.steps.length} pasos completados
            </span>
            <button onClick={onClose} className="btn-ghost border border-white/[0.06]">
              Cerrar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}