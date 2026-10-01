import { useState } from 'react';
import { LayoutDashboard, Brain, Radar, ShieldCheck, AlertTriangle } from 'lucide-react';
import { Header } from '@/components/Header';
import { ContextSelector } from '@/components/ContextSelector';
import { MaturityDashboard } from '@/components/MaturityDashboard';
import { RecommendationEngine } from '@/components/RecommendationEngine';
import { ThreatSimulation } from '@/components/ThreatSimulation';
import { getCriteria, getFindings, getPlans } from '@/lib/api';
import type { AssessmentDetail, CriterionResult, Finding, Plan } from '@/lib/types';

type Tab = 'dashboard' | 'recommendations' | 'threats';

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'dashboard', label: 'Resumen de Madurez', icon: <LayoutDashboard className="h-4 w-4" /> },
  { key: 'recommendations', label: 'Recomendaciones', icon: <Brain className="h-4 w-4" /> },
  { key: 'threats', label: 'Simulación de Amenazas', icon: <Radar className="h-4 w-4" /> },
];

function App() {
  const [assessment, setAssessment] = useState<AssessmentDetail | null>(null);
  const [criteria, setCriteria] = useState<CriterionResult[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [selectorOpen, setSelectorOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('dashboard');

  async function handleCreated(detail: AssessmentDetail) {
    setAssessment(detail);
    setCriteria([]);
    setFindings([]);
    setPlans([]);
    setDetailError(null);
    setTab('dashboard');
    try {
      const [c, f, p] = await Promise.all([
        getCriteria(detail.id),
        getFindings(detail.id),
        getPlans(detail.id),
      ]);
      setCriteria(c);
      setFindings(f);
      setPlans(p);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'No se pudieron cargar los detalles.');
    }
  }

  return (
    <div className="min-h-screen grid-bg">
      <Header onOpenSelector={() => setSelectorOpen(true)} />

      {assessment && (
        <div className="border-b border-white/[0.06] bg-ink-900/40">
          <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-4 py-2.5 sm:px-6">
            <ShieldCheck className="h-4 w-4 text-cyan-400" />
            <span className="text-xs font-medium text-slate-400">Organización activa:</span>
            <span className="text-xs font-semibold text-white">{assessment.org_nombre}</span>
            <span className="hidden text-xs text-slate-600 sm:inline">
              · assessment {assessment.id.slice(0, 8)} · {assessment.scope}
            </span>
          </div>
        </div>
      )}

      <div className="sticky top-[57px] z-20 border-b border-white/[0.06] bg-ink-950/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1400px] gap-1 px-4 sm:px-6">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`relative flex items-center gap-2 px-4 py-3.5 text-sm font-medium transition-colors ${
                tab === t.key ? 'text-white' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {t.icon}
              <span className="hidden sm:inline">{t.label}</span>
              <span className="sm:hidden">{t.label.split(' ')[0]}</span>
              {tab === t.key && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-cyan-400" />}
            </button>
          ))}
        </div>
      </div>

      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 sm:py-8">
        {detailError && (
          <div className="card mb-4 flex items-center gap-2 border-rose-500/30 bg-rose-500/[0.07] p-3.5 text-sm text-rose-200">
            <AlertTriangle className="h-4 w-4 flex-shrink-0" />
            {detailError}
          </div>
        )}

        {!assessment ? (
          <div className="card flex flex-col items-center justify-center px-6 py-20 text-center">
            <ShieldCheck className="mb-4 h-12 w-12 text-slate-700" />
            <h2 className="text-lg font-semibold text-slate-300">Ninguna evaluación activa</h2>
            <p className="mt-1 max-w-sm text-sm text-slate-500">
              Crea una evaluación con datos de ejemplo o tus propios archivos de Terraform/Ansible/documentos
              para empezar.
            </p>
            <button onClick={() => setSelectorOpen(true)} className="btn-primary mt-5">
              Nueva Evaluación
            </button>
          </div>
        ) : tab === 'dashboard' ? (
          <MaturityDashboard assessment={assessment} criteria={criteria} />
        ) : tab === 'recommendations' ? (
          <RecommendationEngine
            assessmentId={assessment.id}
            findings={findings}
            plans={plans}
            onPlansUpdated={setPlans}
          />
        ) : (
          <ThreatSimulation orgId={assessment.org_id} orgNombre={assessment.org_nombre} />
        )}
      </main>

      <ContextSelector open={selectorOpen} onClose={() => setSelectorOpen(false)} onCreated={handleCreated} />

      <footer className="mx-auto max-w-[1400px] px-4 pb-8 pt-4 sm:px-6">
        <p className="text-center text-xs text-slate-700">
          Prototipo académico · Evaluación determinista + IA opcional · Referencia NIST CSF 2.0 · No apto para uso en producción
        </p>
      </footer>
    </div>
  );
}

export default App;
