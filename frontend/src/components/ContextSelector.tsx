import { useState } from 'react';
import {
  X,
  FolderCog,
  FileCode2,
  UploadCloud,
  Loader2,
  Sparkles,
  ArrowRight,
  AlertTriangle,
  Brain,
} from 'lucide-react';
import { DEMO_BUNDLES, fetchAsFile } from '@/data/demo';
import { ApiError, createAssessment } from '@/lib/api';
import type { AssessmentDetail } from '@/lib/types';

interface ContextSelectorProps {
  open: boolean;
  onClose: () => void;
  onCreated: (assessment: AssessmentDetail) => void;
}

type Mode = 'demo' | 'custom';

export function ContextSelector({ open, onClose, onCreated }: ContextSelectorProps) {
  const [mode, setMode] = useState<Mode>('demo');
  const [bundleId, setBundleId] = useState(DEMO_BUNDLES[0].id);
  const [orgName, setOrgName] = useState('Organización Demo');
  const [aiAdjust, setAiAdjust] = useState(false);
  const [useAiForDocuments, setUseAiForDocuments] = useState(false);
  const [terraformFiles, setTerraformFiles] = useState<File[]>([]);
  const [ansibleFiles, setAnsibleFiles] = useState<File[]>([]);
  const [documentFiles, setDocumentFiles] = useState<File[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsConfirm, setNeedsConfirm] = useState(false);
  const [confirmLiveAi, setConfirmLiveAi] = useState(false);

  if (!open) return null;

  const hasCustomFiles = terraformFiles.length + ansibleFiles.length + documentFiles.length > 0;
  const canSubmit = orgName.trim().length > 0 && (mode === 'demo' || hasCustomFiles);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
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
          orgName: orgName.trim(),
          aiAdjust,
          useAiForDocuments: useAiForDocuments && docs.length > 0,
          confirmLiveAi,
          terraformFiles: tf,
          ansibleFiles: ans,
          documentFiles: docs,
        };
      } else {
        input = {
          orgName: orgName.trim(),
          aiAdjust,
          useAiForDocuments: useAiForDocuments && documentFiles.length > 0,
          confirmLiveAi,
          terraformFiles,
          ansibleFiles,
          documentFiles,
        };
      }

      const assessment = await createAssessment(input);
      resetAndClose();
      onCreated(assessment);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNeedsConfirm(true);
        setError(err.detail);
      } else {
        setError(err instanceof Error ? err.message : 'Error desconocido.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  function resetAndClose() {
    setError(null);
    setNeedsConfirm(false);
    setConfirmLiveAi(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm animate-fade-in"
        onClick={() => !submitting && resetAndClose()}
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
              disabled={submitting}
              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white disabled:opacity-40"
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
            <label className="mb-2 block text-xs font-medium text-slate-400">
              Nombre de la organización
            </label>
            <input
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="Ej. Empresa Demo"
              className="input mb-5"
            />

            {mode === 'demo' ? (
              <div className="grid gap-3 sm:grid-cols-2">
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

            {/* Opciones de IA */}
            <div className="mt-5 space-y-2 rounded-lg border border-white/[0.06] bg-ink-900/40 p-3.5">
              <div className="flex items-center gap-2 text-xs font-medium text-slate-400">
                <Brain className="h-3.5 w-3.5 text-cyan-400" />
                Capa de IA (opcional)
              </div>
              <Checkbox
                checked={aiAdjust}
                onChange={setAiAdjust}
                label="Ajustar puntajes con contexto adicional (U2)"
              />
              <Checkbox
                checked={useAiForDocuments}
                onChange={setUseAiForDocuments}
                label="Usar IA para extraer afirmaciones de los documentos (U1)"
              />
              <p className="pl-6 text-xs text-slate-600">
                Sin una DEEPSEEK_API_KEY configurada en el backend, esto no tiene costo ni efecto:
                el resultado queda igual al puntaje base.
              </p>
            </div>

            {error && (
              <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/[0.07] p-3.5 text-xs text-amber-200">
                <div className="mb-1 flex items-center gap-2 font-medium">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {needsConfirm ? 'Confirmación requerida' : 'No se pudo crear la evaluación'}
                </div>
                <p className="whitespace-pre-line leading-relaxed">{error}</p>
                {needsConfirm && (
                  <label className="mt-2 flex items-center gap-2 text-amber-100">
                    <input
                      type="checkbox"
                      checked={confirmLiveAi}
                      onChange={(e) => setConfirmLiveAi(e.target.checked)}
                      className="h-3.5 w-3.5 rounded border-amber-500/40 bg-transparent"
                    />
                    Confirmo que quiero hacer llamadas reales (y pagadas) a la API de IA.
                  </label>
                )}
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
                disabled={!canSubmit || submitting || (needsConfirm && !confirmLiveAi)}
                className="btn-primary flex-shrink-0"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {submitting ? 'Evaluando…' : needsConfirm ? 'Reintentar' : 'Analizar'}
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

function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-slate-300">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 rounded border-white/20 bg-transparent"
      />
      {label}
    </label>
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
