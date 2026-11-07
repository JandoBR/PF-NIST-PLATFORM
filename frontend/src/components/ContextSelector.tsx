import { useEffect, useRef, useState } from 'react';
import {
  X,
  FolderCog,
  FileCode2,
  UploadCloud,
  Loader2,
  Sparkles,
  ArrowRight,
  AlertTriangle,
} from 'lucide-react';
import { DEMO_BUNDLES, fetchAsFile } from '@/data/demo';
import { JobTimeoutError, createAssessment, getAssessment, isAbortError, pollJob } from '@/lib/api';
import type { AssessmentAccepted, AssessmentDetail, JobEstado } from '@/lib/types';

interface ContextSelectorProps {
  open: boolean;
  onClose: () => void;
  onCreated: (assessment: AssessmentDetail) => void;
  /** Se llama apenas la API acepta el job (202), antes de que termine: permite al dashboard
   * registrar la evaluacion en el historial aunque el modal se cierre a mitad de camino. */
  onAccepted?: (accepted: AssessmentAccepted) => void;
}

type Mode = 'demo' | 'custom';

export function ContextSelector({ open, onClose, onCreated, onAccepted }: ContextSelectorProps) {
  const [mode, setMode] = useState<Mode>('demo');
  const [bundleId, setBundleId] = useState(DEMO_BUNDLES[0].id);
  const [terraformFiles, setTerraformFiles] = useState<File[]>([]);
  const [ansibleFiles, setAnsibleFiles] = useState<File[]>([]);
  const [documentFiles, setDocumentFiles] = useState<File[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [jobEstado, setJobEstado] = useState<JobEstado | null>(null);
  const [error, setError] = useState<string | null>(null);

  //: Permite abortar el sondeo del job si el usuario cierra el modal: el job sigue corriendo en
  //: el backend, pero la UI deja de esperar y el dashboard lo recupera por el historial.
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);

  if (!open) return null;

  const hasCustomFiles = terraformFiles.length + ansibleFiles.length + documentFiles.length > 0;
  const canSubmit = mode === 'demo' || hasCustomFiles;

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    setJobEstado(null);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      let input;
      if (mode === 'demo') {
        const bundle = DEMO_BUNDLES.find((b) => b.id === bundleId) ?? DEMO_BUNDLES[0];
        const [tf, ans, docs] = await Promise.all([
          Promise.all((bundle.terraform ?? []).map(fetchAsFile)),
          Promise.all((bundle.ansible ?? []).map(fetchAsFile)),
          Promise.all((bundle.documents ?? []).map(fetchAsFile)),
        ]);
        input = {
          aiAdjust: true,
          useAiForDocuments: docs.length > 0,
          terraformFiles: tf,
          ansibleFiles: ans,
          documentFiles: docs,
        };
      } else {
        input = {
          aiAdjust: true,
          useAiForDocuments: documentFiles.length > 0,
          terraformFiles,
          ansibleFiles,
          documentFiles,
        };
      }

      // POST /assessments encola el pipeline en worker-core y devuelve de inmediato (docs/09
      // §16): hay que sondear el job hasta que termine antes de tener algo que mostrar.
      const accepted = await createAssessment(input);
      onAccepted?.(accepted);
      const job = await pollJob(accepted.job_id, {
        signal: controller.signal,
        onTick: (j) => setJobEstado(j.estado),
      });

      if (job.estado === 'fallido') {
        setError(job.error ?? 'La evaluación falló en el worker, sin más detalle.');
        return;
      }

      const assessment = await getAssessment(accepted.assessment_id);
      resetAndClose();
      onCreated(assessment);
    } catch (err) {
      if (isAbortError(err)) {
        return; // el usuario cerró el modal: el job sigue en el backend, no es un error de UI
      }
      if (err instanceof JobTimeoutError) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Error desconocido.');
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setSubmitting(false);
      setJobEstado(null);
    }
  }

  function resetAndClose() {
    abortRef.current?.abort();
    setError(null);
    onClose();
  }

  const submitLabel =
    jobEstado === 'pendiente'
      ? 'En cola…'
      : jobEstado === 'en_progreso'
        ? 'Evaluando…'
        : submitting
          ? 'Enviando…'
          : 'Analizar';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm animate-fade-in"
        onClick={resetAndClose}
      />
      <div className="relative z-10 w-full max-w-2xl animate-scale-in">
        <div className="card max-h-[90vh] overflow-y-auto shadow-2xl shadow-black/50">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/[0.06] px-6 py-4">
            <div className="flex items-center gap-2.5">
              <FolderCog className="h-5 w-5 text-cyan-400" />
              <h2 className="text-base font-semibold text-white">Nueva Evaluación</h2>
            </div>
            <button
              onClick={resetAndClose}
              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Mode tabs */}
          <div className="flex gap-1 px-6 pt-4">
            <TabBtn active={mode === 'demo'} onClick={() => setMode('demo')}>
              Datos de Ejemplo
            </TabBtn>
            <TabBtn active={mode === 'custom'} onClick={() => setMode('custom')}>
              Subir mis Archivos
            </TabBtn>
          </div>

          <div className="px-6 py-5">
            {/* La organización sale de la sesión (doc 10): ya no se elige aquí. */}
            {mode === 'demo' ? (
              <div className="grid gap-3 sm:grid-cols-3">
                {DEMO_BUNDLES.map((b) => (
                  <button
                    key={b.id}
                    onClick={() => setBundleId(b.id)}
                    className={`group rounded-xl border p-4 text-left transition-all duration-200 ${
                      bundleId === b.id
                        ? 'border-cyan-500/50 bg-cyan-500/[0.07] glow-cyan'
                        : 'border-white/[0.06] bg-ink-900/40 hover:border-white/15 hover:bg-ink-900/70'
                    }`}
                  >
                    <div
                      className={`mb-2.5 flex h-10 w-10 items-center justify-center rounded-lg transition-colors ${
                        bundleId === b.id
                          ? 'bg-cyan-500/15 text-cyan-300'
                          : 'bg-white/[0.04] text-slate-400 group-hover:text-slate-200'
                      }`}
                    >
                      <FileCode2 className="h-5 w-5" />
                    </div>
                    <h3 className="text-sm font-semibold text-slate-100">{b.label}</h3>
                    <p className="mt-1 text-xs leading-relaxed text-slate-500">{b.description}</p>
                  </button>
                ))}
              </div>
            ) : (
              <div className="space-y-4">
                <FilePicker
                  label="Terraform (.tf)"
                  accept=".tf"
                  files={terraformFiles}
                  onChange={setTerraformFiles}
                />
                <FilePicker
                  label="Ansible (.yml / .yaml)"
                  accept=".yml,.yaml"
                  files={ansibleFiles}
                  onChange={setAnsibleFiles}
                />
                <FilePicker
                  label="Documentos de política (.md / .pdf)"
                  accept=".md,.pdf"
                  files={documentFiles}
                  onChange={setDocumentFiles}
                />
                {!hasCustomFiles && (
                  <p className="text-xs text-slate-500">
                    Se requiere al menos un archivo de alguno de los tres tipos.
                  </p>
                )}
              </div>
            )}


            {error && (
              <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/[0.07] p-3.5 text-xs text-amber-200">
                <div className="mb-1 flex items-center gap-2 font-medium">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  No se pudo crear la evaluación
                </div>
                <p className="whitespace-pre-line leading-relaxed">{error}</p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-white/[0.06] px-6 py-4">
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs text-slate-500">
                El motor de reglas evalúa 32 subcategorías CSF 2.0 de forma determinista.
              </p>
              <button
                onClick={handleSubmit}
                disabled={!canSubmit || submitting}
                className="btn-primary flex-shrink-0"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {submitLabel}
                {!submitting && <ArrowRight className="h-4 w-4" />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function FilePicker({
  label,
  accept,
  files,
  onChange,
}: {
  label: string;
  accept: string;
  files: File[];
  onChange: (files: File[]) => void;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-slate-400">{label}</label>
      <label className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-dashed border-white/15 bg-ink-900/40 px-3.5 py-3 text-xs text-slate-500 transition-colors hover:border-cyan-500/40 hover:text-slate-300">
        <UploadCloud className="h-4 w-4 flex-shrink-0" />
        {files.length > 0 ? (
          <span className="truncate text-slate-300">{files.map((f) => f.name).join(', ')}</span>
        ) : (
          <span>Elegir archivo(s)…</span>
        )}
        <input
          type="file"
          accept={accept}
          multiple
          className="hidden"
          onChange={(e) => onChange(Array.from(e.target.files ?? []))}
        />
      </label>
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
        active ? 'bg-white/[0.06] text-white' : 'text-slate-500 hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  );
}
