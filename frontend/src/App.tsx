import { useState } from 'react';
import { LayoutDashboard, Brain, Radar, ShieldCheck } from 'lucide-react';
import { Header } from '@/components/Header';
import { ContextSelector } from '@/components/ContextSelector';
import { MaturityDashboard } from '@/components/MaturityDashboard';
import { RecommendationEngine } from '@/components/RecommendationEngine';
import { ThreatSimulation } from '@/components/ThreatSimulation';
import { ARCHITECTURES, type Architecture } from '@/data/mockData';

type Tab = 'dashboard' | 'recommendations' | 'threats';

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'dashboard', label: 'Resumen de Madurez', icon: <LayoutDashboard className="h-4 w-4" /> },
  { key: 'recommendations', label: 'Recomendaciones', icon: <Brain className="h-4 w-4" /> },
  { key: 'threats', label: 'Simulación de Amenazas', icon: <Radar className="h-4 w-4" /> },
];

function App() {
  const [arch, setArch] = useState<Architecture | null>(ARCHITECTURES[0]);
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('dashboard');

  return (
    <div className="min-h-screen grid-bg">
      <Header
        activeArchName={arch?.name ?? null}
        onOpenSelector={() => setSelectorOpen(true)}
      />

      {/* Barra de contexto activo */}
      {arch && (
        <div className="border-b border-white/[0.06] bg-ink-900/40">
          <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-4 py-2.5 sm:px-6">
            <ShieldCheck className="h-4 w-4 text-cyan-400" />
            <span className="text-xs font-medium text-slate-400">Contexto activo:</span>
            <span className="text-xs font-semibold text-white">{arch.name}</span>
            <span className="hidden text-xs text-slate-600 sm:inline">· {arch.summary}</span>
          </div>
        </div>
      )}

      {/* Pestañas (Tabs) */}
      <div className="sticky top-[57px] z-20 border-b border-white/[0.06] bg-ink-950/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1400px] gap-1 px-4 sm:px-6">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`relative flex items-center gap-2 px-4 py-3.5 text-sm font-medium transition-colors ${
                tab === t.key
                  ? 'text-white'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {t.icon}
              <span className="hidden sm:inline">{t.label}</span>
              <span className="sm:hidden">{t.label.split(' ')[0]}</span>
              {tab === t.key && (
                <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-cyan-400" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Contenido principal */}
      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 sm:py-8">
        {!arch ? (
          <div className="card flex flex-col items-center justify-center px-6 py-20 text-center">
            <ShieldCheck className="mb-4 h-12 w-12 text-slate-700" />
            <h2 className="text-lg font-semibold text-slate-300">Ninguna arquitectura seleccionada</h2>
            <p className="mt-1 max-w-sm text-sm text-slate-500">
              Selecciona una arquitectura empresarial de ejemplo o pega tu propia descripción para comenzar la evaluación de madurez.
            </p>
            <button onClick={() => setSelectorOpen(true)} className="btn-primary mt-5">
              Seleccionar Arquitectura
            </button>
          </div>
        ) : tab === 'dashboard' ? (
          <MaturityDashboard arch={arch} />
        ) : tab === 'recommendations' ? (
          <RecommendationEngine />
        ) : (
          <ThreatSimulation />
        )}
      </main>

      <ContextSelector
        open={selectorOpen}
        onClose={() => setSelectorOpen(false)}
        onAnalyze={(a) => {
          setArch(a);
          setSelectorOpen(false);
          setTab('dashboard');
        }}
      />

      <footer className="mx-auto max-w-[1400px] px-4 pb-8 pt-4 sm:px-6">
        <p className="text-center text-xs text-slate-700">
          Prototipo conceptual · Datos simulados · Referencia NIST CSF 2.0 · No apto para uso en producción
        </p>
      </footer>
    </div>
  );
}

export default App;