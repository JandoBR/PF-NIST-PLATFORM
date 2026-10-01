import { useState, useEffect, useCallback } from 'react';
import {
  X,
  Cloud,
  ShoppingBag,
  HeartPulse,
  FileText,
  Cpu,
  CheckCircle2,
  Loader2,
  Sparkles,
  ArrowRight,
} from 'lucide-react';
import { ARCHITECTURES, type Architecture } from '@/data/mockData';

interface ContextSelectorProps {
  open: boolean;
  onClose: () => void;
  onAnalyze: (arch: Architecture) => void;
}

const ARCH_ICONS: Record<string, React.ReactNode> = {
  fintech: <Cloud className="h-5 w-5" />,
  ecommerce: <ShoppingBag className="h-5 w-5" />,
  healthcare: <HeartPulse className="h-5 w-5" />,
};

const PIPELINE = [
  { id: 'rules', label: 'Evaluación de Reglas', desc: 'Mapeando 32 subcategorías CSF 2.0 con la evidencia de controles' },
  { id: 'ai', label: 'Enriquecimiento Contextual por IA', desc: 'Adaptando recomendaciones al contexto de la arquitectura' },
];

export function ContextSelector({ open, onClose, onAnalyze }: ContextSelectorProps) {
  const [selectedId, setSelectedId] = useState<string | null>('fintech');
  const [customText, setCustomText] = useState('');
  const [mode, setMode] = useState<'preset' | 'custom'>('preset');
  const [analyzing, setAnalyzing] = useState(false);
  const [step, setStep] = useState(0);

  const handleAnalyze = useCallback(() => {
    const arch =
      mode === 'custom'
        ? {
            ...ARCHITECTURES[0],
            id: 'custom',
            name: 'Arquitectura Personalizada',
            summary: 'Descripción del entorno proporcionada por el usuario',
            context: customText.trim() || 'No se proporcionó contexto.',
          }
        : ARCHITECTURES.find((a) => a.id === selectedId) ?? ARCHITECTURES[0];

    setAnalyzing(true);
    setStep(0);
    const t1 = window.setTimeout(() => setStep(1), 1100);
    const t2 = window.setTimeout(() => {
      setAnalyzing(false);
      setStep(0);
      onAnalyze(arch);
    }, 2400);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [mode, selectedId, customText, onAnalyze]);

  useEffect(() => {
    if (!open) {
      setAnalyzing(false);
      setStep(0);
    }
  }, [open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !analyzing && onClose();
    if (open) window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, analyzing, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm animate-fade-in"
        onClick={() => !analyzing && onClose()}
      />
      <div className="relative z-10 w-full max-w-2xl animate-scale-in">
        <div className="card overflow-hidden shadow-2xl shadow-black/50">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/[0.06] px-6 py-4">
            <div className="flex items-center gap-2.5">
              <Cpu className="h-5 w-5 text-cyan-400" />
              <h2 className="text-base font-semibold text-white">Contexto de la Arquitectura</h2>
            </div>
            <button
              onClick={onClose}
              disabled={analyzing}
              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white disabled:opacity-40"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Mode tabs */}
          <div className="flex gap-1 px-6 pt-4">
            <TabBtn active={mode === 'preset'} onClick={() => setMode('preset')}>
              Arquitecturas de Ejemplo
            </TabBtn>
            <TabBtn active={mode === 'custom'} onClick={() => setMode('custom')}>
              Pegar Descripción
            </TabBtn>
          </div>

          {/* Body */}
          <div className="px-6 py-5">
            {mode === 'preset' ? (
              <div className="grid gap-3 sm:grid-cols-3">
                {ARCHITECTURES.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => setSelectedId(a.id)}
                    className={`group rounded-xl border p-4 text-left transition-all duration-200 ${
                      selectedId === a.id
                        ? 'border-cyan-500/50 bg-cyan-500/[0.07] glow-cyan'
                        : 'border-white/[0.06] bg-ink-900/40 hover:border-white/15 hover:bg-ink-900/70'
                    }`}
                  >
                    <div
                      className={`mb-2.5 flex h-10 w-10 items-center justify-center rounded-lg transition-colors ${
                        selectedId === a.id
                          ? 'bg-cyan-500/15 text-cyan-300'
                          : 'bg-white/[0.04] text-slate-400 group-hover:text-slate-200'
                      }`}
                    >
                      {ARCH_ICONS[a.id]}
                    </div>
                    <h3 className="text-sm font-semibold text-slate-100">{a.name}</h3>
                    <p className="mt-1 text-xs leading-relaxed text-slate-500">{a.summary}</p>
                  </button>
                ))}
              </div>
            ) : (
              <div>
                <label className="mb-2 block text-xs font-medium text-slate-400">
                  Pega la descripción de tu entorno, políticas o notas de arquitectura
                </label>
                <textarea
                  value={customText}
                  onChange={(e) => setCustomText(e.target.value)}
                  rows={6}
                  placeholder="Ej. Operamos una plataforma Kubernetes multirregión en AWS con federación IAM, registros CloudTrail a un SIEM central y escaneos trimestrales de vulnerabilidades. Actualmente no contamos con un programa formal de riesgo en la cadena de suministro..."
                  className="input resize-none font-mono text-xs leading-relaxed"
                />
                <div className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
                  <FileText className="h-3.5 w-3.5" />
                  {customText.trim().split(/\s+/).filter(Boolean).length} palabras
                </div>
              </div>
            )}

            {/* Selected context preview */}
            {mode === 'preset' && selectedId && (
              <div className="mt-4 rounded-lg border border-white/[0.06] bg-ink-900/40 p-3.5">
                <p className="line-clamp-3 text-xs leading-relaxed text-slate-400">
                  {ARCHITECTURES.find((a) => a.id === selectedId)?.context}
                </p>
              </div>
            )}
          </div>

          {/* Pipeline / footer */}
          <div className="border-t border-white/[0.06] px-6 py-4">
            {analyzing ? (
              <div className="space-y-3">
                {PIPELINE.map((p, i) => {
                  const done = i < step;
                  const active = i === step;
                  return (
                    <div key={p.id} className="flex items-center gap-3">
                      <div className="flex-shrink-0">
                        {done ? (
                          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                        ) : active ? (
                          <Loader2 className="h-5 w-5 animate-spin text-cyan-400" />
                        ) : (
                          <div className="h-5 w-5 rounded-full border-2 border-white/10" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <p
                          className={`text-sm font-medium ${
                            done || active ? 'text-slate-200' : 'text-slate-600'
                          }`}
                        >
                          {p.label}
                        </p>
                        <p
                          className={`text-xs ${
                            done || active ? 'text-slate-500' : 'text-slate-700'
                          }`}
                        >
                          {p.desc}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="flex items-center justify-between gap-4">
                <p className="text-xs text-slate-500">
                  {mode === 'preset'
                    ? 'El análisis mapea 32 subcategorías CSF 2.0 y genera una hoja de ruta priorizada.'
                    : 'El contexto personalizado se evaluará frente al conjunto completo de controles CSF 2.0.'}
                </p>
                <button
                  onClick={handleAnalyze}
                  disabled={mode === 'custom' && customText.trim().length < 10}
                  className="btn-primary"
                >
                  <Sparkles className="h-4 w-4" />
                  Analizar Arquitectura
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function TabBtn({
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
      className={`rounded-lg px-3.5 py-2 text-sm font-medium transition-colors ${
        active
          ? 'bg-white/[0.06] text-white'
          : 'text-slate-500 hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  );
}