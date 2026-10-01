import { useCallback, useEffect, useState } from 'react';
import {
  LayoutDashboard,
  Brain,
  Radar,
  GitCompare,
  ShieldCheck,
  AlertTriangle,
  RefreshCw,
  History,
} from 'lucide-react';
import { Header } from '@/components/Header';
import { Login } from '@/components/Login';
import { ContextSelector } from '@/components/ContextSelector';
import { MaturityDashboard } from '@/components/MaturityDashboard';
import { RecommendationEngine } from '@/components/RecommendationEngine';
import { ThreatSimulation } from '@/components/ThreatSimulation';
import { CompareAssessments } from '@/components/CompareAssessments';
import {
  getAssessment,
  getCriteria,
  getFindings,
  getMe,
  getPlans,
  hasToken,
  listAssessments,
  logout as apiLogout,
  pollJob,
  reevaluateAssessment,
} from '@/lib/api';
import type { AuthUser } from '@/lib/api';
import type { AssessmentDetail, CriterionResult, Finding, Plan } from '@/lib/types';

type Tab = 'dashboard' | 'recommendations' | 'threats' | 'compare';

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'dashboard', label: 'Resumen de Madurez', icon: <LayoutDashboard className="h-4 w-4" /> },
  { key: 'recommendations', label: 'Recomendaciones', icon: <Brain className="h-4 w-4" /> },
  { key: 'threats', label: 'Simulación de Amenazas', icon: <Radar className="h-4 w-4" /> },
  { key: 'compare', label: 'Comparar', icon: <GitCompare className="h-4 w-4" /> },
];

//: Id de la evaluación activa, para que al recargar la página se restaure en vez de perderse.
const ACTIVE_KEY = 'pf.activeAssessmentId';

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('es', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  const [assessment, setAssessment] = useState<AssessmentDetail | null>(null);
  const [criteria, setCriteria] = useState<CriterionResult[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [reevaluating, setReevaluating] = useState(false);

  const [history, setHistory] = useState<AssessmentDetail[]>([]);
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('dashboard');

  // Restaura la sesión al montar (token en localStorage) y vuelve al login ante cualquier 401.
  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!hasToken()) {
        if (mounted) setAuthChecked(true);
        return;
      }
      try {
        const me = await getMe();
        if (mounted) setUser(me);
      } catch {
        // el 401 ya limpió el token y disparó el evento; aquí solo se marca la verificación
      } finally {
        if (mounted) setAuthChecked(true);
      }
    })();
    const onUnauthorized = () => setUser(null);
    window.addEventListener('pf:unauthorized', onUnauthorized);
    return () => {
      mounted = false;
      window.removeEventListener('pf:unauthorized', onUnauthorized);
    };
  }, []);

  const loadAssessmentDetails = useCallback(async (detail: AssessmentDetail) => {
    setAssessment(detail);
    localStorage.setItem(ACTIVE_KEY, detail.id);
    setCriteria([]);
    setFindings([]);
    setPlans([]);
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
  }, []);

  const refreshHistory = useCallback(async (): Promise<AssessmentDetail[]> => {
    try {
      const list = await listAssessments();
      setHistory(list);
      return list;
    } catch {
      return [];
    }
  }, []);

  // Carga el historial (ya filtrado por organización en el backend) y restaura la activa.
  useEffect(() => {
    if (!user) return;
    let mounted = true;
    (async () => {
      try {
        const list = await listAssessments();
        if (!mounted) return;
        setHistory(list);
        const savedId = localStorage.getItem(ACTIVE_KEY);
        const saved = list.find((a) => a.id === savedId);
        const fallback = list.find((a) => a.estado === 'completada') ?? list[0];
        const chosen = saved ?? fallback;
        if (chosen) await loadAssessmentDetails(chosen);
      } catch (err) {
        if (mounted) {
          setDetailError(err instanceof Error ? err.message : 'No se pudo cargar el historial.');
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, [user, loadAssessmentDetails]);

  async function handleCreated(detail: AssessmentDetail) {
    setDetailError(null);
    setTab('dashboard');
    setHistory((prev) => [detail, ...prev.filter((a) => a.id !== detail.id)]);
    await loadAssessmentDetails(detail);
  }

  // Se llama apenas la API acepta el job (202): refresca el historial para que la evaluación
  // recién encolada aparezca aunque el modal se cierre antes de que termine.
  async function handleAccepted() {
    await refreshHistory();
  }

  async function selectAssessment(id: string) {
    const chosen = history.find((a) => a.id === id);
    if (!chosen) return;
    setDetailError(null);
    setTab('dashboard');
    await loadAssessmentDetails(chosen);
  }

  async function handleReevaluate() {
    if (!assessment) return;
    setReevaluating(true);
    setDetailError(null);
    try {
      const accepted = await reevaluateAssessment(assessment.id);
      const job = await pollJob(accepted.job_id);
      if (job.estado === 'fallido') {
        setDetailError(job.error ?? 'La reevaluación falló en el worker, sin más detalle.');
        return;
      }
      const detail = await getAssessment(accepted.assessment_id);
      await refreshHistory();
      await loadAssessmentDetails(detail);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'No se pudo reevaluar.');
    } finally {
      setReevaluating(false);
    }
  }

  function handleLogout() {
    apiLogout();
    setUser(null);
    setAssessment(null);
    setCriteria([]);
    setFindings([]);
    setPlans([]);
    setHistory([]);
    setDetailError(null);
    localStorage.removeItem(ACTIVE_KEY);
  }

  if (!authChecked) {
    return (
      <div className="grid-bg flex min-h-screen items-center justify-center text-sm text-slate-500">
        Cargando…
      </div>
    );
  }

  if (!user) {
    return <Login onLogin={setUser} />;
  }

  return (
    <div className="min-h-screen grid-bg">
      <Header
        onOpenSelector={() => setSelectorOpen(true)}
        user={user}
        onLogout={handleLogout}
      />

      {(assessment || history.length > 0) && (
        <div className="border-b border-white/[0.06] bg-ink-900/40">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 sm:px-6">
            <ShieldCheck className="h-4 w-4 text-cyan-400" />
            {assessment ? (
              <>
                <span className="text-xs font-medium text-slate-400">Organización activa:</span>
                <span className="text-xs font-semibold text-white">{assessment.org_nombre}</span>
                <span className="hidden text-xs text-slate-600 sm:inline">
                  · assessment {assessment.id.slice(0, 8)} · {assessment.scope}
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-400">Selecciona una evaluación del historial</span>
            )}

            <div className="ml-auto flex items-center gap-2">
              <History className="hidden h-3.5 w-3.5 text-slate-500 sm:block" />
              <label className="hidden text-xs text-slate-500 sm:block">Historial</label>
              <select
                value={assessment?.id ?? ''}
                onChange={(e) => selectAssessment(e.target.value)}
                className="max-w-[15rem] rounded-lg border border-white/10 bg-ink-900/60 px-2 py-1 text-xs text-slate-200 outline-none focus:border-cyan-500/50"
              >
                {!assessment && <option value="">Seleccionar…</option>}
                {history.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.org_nombre} · {formatWhen(a.creado_en)} · {a.estado}
                  </option>
                ))}
              </select>
              <button
                onClick={() => refreshHistory()}
                title="Actualizar historial"
                className="rounded-lg border border-white/[0.06] bg-ink-900/60 p-1.5 text-slate-400 transition-colors hover:text-white"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
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
          <MaturityDashboard
            assessment={assessment}
            criteria={criteria}
            onReevaluate={handleReevaluate}
            reevaluating={reevaluating}
          />
        ) : tab === 'recommendations' ? (
          <RecommendationEngine
            assessmentId={assessment.id}
            findings={findings}
            plans={plans}
            onPlansUpdated={setPlans}
          />
        ) : tab === 'threats' ? (
          <ThreatSimulation orgId={assessment.org_id} orgNombre={assessment.org_nombre} />
        ) : (
          <CompareAssessments orgId={assessment.org_id} currentAssessmentId={assessment.id} />
        )}
      </main>

      <ContextSelector
        open={selectorOpen}
        onClose={() => setSelectorOpen(false)}
        onCreated={handleCreated}
        onAccepted={handleAccepted}
      />

      <footer className="mx-auto max-w-[1400px] px-4 pb-8 pt-4 sm:px-6">
        <p className="text-center text-xs text-slate-700">
          Prototipo académico · Evaluación determinista + IA opcional · Referencia NIST CSF 2.0 · No apto para uso en producción
        </p>
      </footer>
    </div>
  );
}

export default App;
