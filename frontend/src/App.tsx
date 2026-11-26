import { useCallback, useEffect, useRef, useState } from 'react';
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
import { EventsIncidents } from '@/components/EventsIncidents';
import { CompareAssessments } from '@/components/CompareAssessments';
import { JobHistory } from '@/components/JobHistory';
import {
  getAssessment,
  getCriteria,
  getFindings,
  getMe,
  getPlans,
  hasToken,
  listAssessments,
  logout as apiLogout,
} from '@/lib/api';
import type { AuthUser } from '@/lib/api';
import { formatDbDate } from '@/lib/datetime';
import type { AssessmentAccepted, AssessmentDetail, CriterionResult, Finding, Plan } from '@/lib/types';

type Tab = 'dashboard' | 'recommendations' | 'threats' | 'compare' | 'jobs';

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'dashboard', label: 'Resumen de Madurez', icon: <LayoutDashboard className="h-4 w-4" /> },
  { key: 'recommendations', label: 'Recomendaciones', icon: <Brain className="h-4 w-4" /> },
  { key: 'threats', label: 'Eventos e Incidentes', icon: <Radar className="h-4 w-4" /> },
  { key: 'compare', label: 'Comparar', icon: <GitCompare className="h-4 w-4" /> },
];

//: Id de la evaluación activa, para que al recargar la página se restaure en vez de perderse.
const ACTIVE_KEY = 'pf.activeAssessmentId';

//: Estados no terminales de una evaluación y cada cuánto se consulta la activa mientras dura.
const IN_PROGRESS = ['pendiente', 'en_progreso'];
const ACTIVE_POLL_MS = 3000;
const ACTIVE_POLL_TIMEOUT_MS = 20 * 60_000;

function formatWhen(iso: string): string {
  return formatDbDate(iso, 'es', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  const [assessment, setAssessment] = useState<AssessmentDetail | null>(null);
  const [criteria, setCriteria] = useState<CriterionResult[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [pollNotice, setPollNotice] = useState<string | null>(null);

  const [history, setHistory] = useState<AssessmentDetail[]>([]);
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('dashboard');

  // Identifica la petición de detalle más reciente y la evaluación que el usuario quiere activa,
  // para que una respuesta lenta de A no pise una selección posterior de B (ni el sondeo).
  const detailRequest = useRef(0);
  const activeId = useRef<string | null>(null);
  const pollStart = useRef<{ id: string; at: number } | null>(null);

  const clearActiveData = useCallback(() => {
    detailRequest.current += 1;
    activeId.current = null;
    pollStart.current = null;
    setAssessment(null);
    setCriteria([]);
    setFindings([]);
    setPlans([]);
    setHistory([]);
    setDetailError(null);
    setPollNotice(null);
    setSelectorOpen(false);
    setTab('dashboard');
    localStorage.removeItem(ACTIVE_KEY);
  }, []);

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
    const onUnauthorized = () => {
      setUser(null);
      clearActiveData();
    };
    window.addEventListener('pf:unauthorized', onUnauthorized);
    return () => {
      mounted = false;
      window.removeEventListener('pf:unauthorized', onUnauthorized);
    };
  }, [clearActiveData]);

  const loadAssessmentDetails = useCallback(async (detail: AssessmentDetail) => {
    const requestId = ++detailRequest.current;
    activeId.current = detail.id;
    setAssessment(detail);
    localStorage.setItem(ACTIVE_KEY, detail.id);
    setCriteria([]);
    setFindings([]);
    setPlans([]);
    setDetailError(null);
    setPollNotice(null);
    pollStart.current = null;
    try {
      const [c, f, p] = await Promise.all([
        getCriteria(detail.id),
        getFindings(detail.id),
        getPlans(detail.id),
      ]);
      if (requestId !== detailRequest.current) return;
      setCriteria(c);
      setFindings(f);
      setPlans(p);
    } catch (err) {
      if (requestId !== detailRequest.current) return;
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
        if (chosen) {
          await loadAssessmentDetails(chosen);
        } else {
          // Sin evaluación restaurable no debe quedar activa la de una sesión anterior.
          clearActiveData();
        }
      } catch (err) {
        if (mounted) {
          setDetailError(err instanceof Error ? err.message : 'No se pudo cargar el historial.');
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, [user, loadAssessmentDetails, clearActiveData]);

  async function handleCreated(detail: AssessmentDetail) {
    setDetailError(null);
    setTab('dashboard');
    setHistory((prev) => [detail, ...prev.filter((a) => a.id !== detail.id)]);
    await loadAssessmentDetails(detail);
  }

  // Se llama apenas la API acepta el job (202). La evaluación recién encolada pasa a ser la activa
  // enseguida: así, aunque el modal se cierre antes de que termine, el sondeo de la activa (abajo)
  // recarga puntajes, hallazgos y planes al acabar, sin ir al historial a elegirla.
  async function handleAccepted(accepted: AssessmentAccepted) {
    setDetailError(null);
    const previousActiveId = activeId.current;
    activeId.current = accepted.assessment_id;
    await refreshHistory();
    try {
      const detail = await getAssessment(accepted.assessment_id);
      if (activeId.current !== accepted.assessment_id) return;
      setTab('dashboard');
      await loadAssessmentDetails(detail);
    } catch {
      // sin el detalle no se puede activar; queda en el historial y se elige desde ahí
      if (activeId.current === accepted.assessment_id) activeId.current = previousActiveId;
    }
  }

  // Una ingesta con suficientes patrones nuevos encola una reevaluación automática antes de marcar
  // su job como hecho (docs/08 §8): si aparece una evaluación que no estaba, pasa a ser la activa.
  async function handleIngested() {
    const knownIds = new Set(history.map((a) => a.id));
    const list = await refreshHistory();
    const created = list.find((a) => !knownIds.has(a.id));
    if (!created) return;
    setDetailError(null);
    setTab('dashboard');
    activeId.current = created.id;
    await loadAssessmentDetails(created);
  }

  // Mientras la evaluación activa está en curso (se eligió del historial o se acaba de crear), se
  // consulta hasta que termine y entonces se recarga TODO: puntajes, criterios, hallazgos y
  // planes. Antes solo se pedían los criterios, y el resumen se quedaba con los datos de cuando
  // la evaluación aún no tenía resultados.
  useEffect(() => {
    if (!assessment || !IN_PROGRESS.includes(assessment.estado)) return;
    const { id, estado } = assessment;
    const previousStart = pollStart.current;
    let startedAt: number;
    if (previousStart && previousStart.id === id) {
      startedAt = previousStart.at;
    } else {
      startedAt = Date.now();
      pollStart.current = { id, at: startedAt };
    }
    let cancelled = false;
    const timer = window.setInterval(async () => {
      if (Date.now() - startedAt > ACTIVE_POLL_TIMEOUT_MS) {
        window.clearInterval(timer);
        setPollNotice(
          'La evaluación sigue en cola o procesándose tras 20 minutos y se dejó de consultar. Revisa la pestaña Actividad para ver el estado del job.'
        );
        return;
      }
      try {
        const fresh = await getAssessment(id);
        if (cancelled || activeId.current !== id || fresh.estado === estado) return;
        if (IN_PROGRESS.includes(fresh.estado)) {
          setAssessment(fresh); // pasó de pendiente a en_progreso
          return;
        }
        window.clearInterval(timer);
        await loadAssessmentDetails(fresh);
        void refreshHistory();
      } catch {
        // un fallo de red puntual no debe parar el sondeo; se reintenta en el siguiente ciclo
      }
    }, ACTIVE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [assessment, loadAssessmentDetails, refreshHistory]);

  async function selectAssessment(id: string) {
    const chosen = history.find((a) => a.id === id);
    if (!chosen) return;
    setDetailError(null);
    setTab('dashboard');
    activeId.current = id;
    // El historial puede estar desactualizado (una evaluación en curso aparece sin puntajes):
    // se pide el detalle actual y, si falla, se usa el que ya hay.
    const fresh = await getAssessment(id).catch(() => chosen);
    if (activeId.current !== id) return;
    await loadAssessmentDetails(fresh);
  }

  function handleLogout() {
    apiLogout();
    setUser(null);
    clearActiveData();
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
        jobsOpen={tab === 'jobs'}
        onToggleJobs={() => setTab((current) => (current === 'jobs' ? 'dashboard' : 'jobs'))}
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
        {pollNotice && (
          <div className="card mb-4 flex items-center gap-2 border-amber-500/30 bg-amber-500/[0.07] p-3.5 text-sm text-amber-200">
            <AlertTriangle className="h-4 w-4 flex-shrink-0" />
            {pollNotice}
          </div>
        )}

        {detailError && (
          <div className="card mb-4 flex items-center gap-2 border-rose-500/30 bg-rose-500/[0.07] p-3.5 text-sm text-rose-200">
            <AlertTriangle className="h-4 w-4 flex-shrink-0" />
            {detailError}
          </div>
        )}

        {tab === 'threats' ? (
          // Eventos e incidentes dependen de la organizacion (sesion), no de una evaluacion: se
          // pueden ingerir logs y ver incidentes sin haber evaluado nada (docs/08).
          <EventsIncidents
            orgId={user.org_id}
            orgNombre={user.org_nombre}
            onIngested={() => void handleIngested()}
          />
        ) : tab === 'jobs' ? (
          // Como los eventos, la actividad en segundo plano es de la organización: se ve sin evaluación.
          <JobHistory
            onClose={() => setTab('dashboard')}
            onOpenAssessment={(id) => void selectAssessment(id)}
            openableIds={new Set(history.map((a) => a.id))}
          />
        ) : !assessment ? (
          <div className="card flex flex-col items-center justify-center px-6 py-20 text-center">
            <ShieldCheck className="mb-4 h-12 w-12 text-slate-700" />
            <h2 className="text-lg font-semibold text-slate-300">Ninguna evaluación activa</h2>
            <p className="mt-1 max-w-sm text-sm text-slate-500">
              Crea una evaluación con datos de ejemplo o tus propios archivos de Terraform/Ansible/documentos
              para empezar. Los eventos e incidentes, en cambio, no necesitan una evaluación.
            </p>
            <button onClick={() => setSelectorOpen(true)} className="btn-primary mt-5">
              Nueva Evaluación
            </button>
          </div>
        ) : tab === 'dashboard' ? (
          <MaturityDashboard assessment={assessment} criteria={criteria} />
        ) : tab === 'recommendations' ? (
          <RecommendationEngine
            key={assessment.id}
            assessmentId={assessment.id}
            findings={findings}
            plans={plans}
            onPlansUpdated={setPlans}
          />
        ) : (
          <CompareAssessments orgId={assessment.org_id} currentAssessmentId={assessment.id} />
        )}
      </main>

      <ContextSelector
        open={selectorOpen}
        orgId={user.org_id}
        onClose={() => setSelectorOpen(false)}
        onCreated={handleCreated}
        onAccepted={handleAccepted}
      />

      <footer className="mx-auto max-w-[1400px] px-4 pb-8 pt-4 sm:px-6">
        <p className="text-center text-xs text-slate-700">
          Evaluación determinista asistida por IA · Referencia NIST CSF 2.0
        </p>
      </footer>
    </div>
  );
}

export default App;
