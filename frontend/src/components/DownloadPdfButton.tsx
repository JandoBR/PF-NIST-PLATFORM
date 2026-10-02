import { useState } from 'react';
import { AlertTriangle, FileDown, Loader2 } from 'lucide-react';

interface Props {
  label: string;
  onDownload: () => Promise<void>;
  disabled?: boolean;
  disabledReason?: string;
}

/** Botón de descarga de un informe PDF (AMP-02): muestra progreso y el error si falla. */
export function DownloadPdfButton({ label, onDownload, disabled, disabledReason }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setBusy(true);
    setError(null);
    try {
      await onDownload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo descargar el informe.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={handleClick}
        disabled={busy || disabled}
        title={disabled ? disabledReason : undefined}
        className="btn-ghost"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
        {label}
      </button>
      {error && (
        <p className="flex items-center gap-1.5 text-xs text-rose-300">
          <AlertTriangle className="h-3.5 w-3.5" /> {error}
        </p>
      )}
    </div>
  );
}
