import type { Estado } from '@/lib/types';

type Severity = 'alta' | 'media' | 'baja';

interface Meta {
  label: string;
  text: string;
  bg: string;
  border: string;
  dot: string;
  bar: string;
}

export const ESTADO_META: Record<Estado, Meta> = {
  evaluado: {
    label: 'Evaluado',
    text: 'text-emerald-300',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
    dot: 'bg-emerald-400',
    bar: 'bg-emerald-400',
  },
  no_implementado: {
    label: 'No implementado',
    text: 'text-rose-300',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
    dot: 'bg-rose-400',
    bar: 'bg-rose-400',
  },
  evidencia_insuficiente: {
    label: 'Evidencia insuficiente',
    text: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    dot: 'bg-amber-400',
    bar: 'bg-amber-400',
  },
  no_aplicable: {
    label: 'No aplicable',
    text: 'text-slate-400',
    bg: 'bg-white/[0.04]',
    border: 'border-white/10',
    dot: 'bg-slate-500',
    bar: 'bg-slate-500',
  },
  error: {
    label: 'Error de evaluación',
    text: 'text-rose-300',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
    dot: 'bg-rose-400',
    bar: 'bg-rose-400',
  },
};

export const SEVERITY_META: Record<Severity, { label: string; text: string; bg: string; border: string }> = {
  alta: {
    label: 'Prioridad Alta',
    text: 'text-rose-300',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
  },
  media: {
    label: 'Prioridad Media',
    text: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
  },
  baja: {
    label: 'Prioridad Baja',
    text: 'text-sky-300',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/30',
  },
};

const THREAT_SEVERITY_META: Record<string, { label: string; text: string; bg: string; border: string; dot: string }> = {
  alta: { label: 'Alta', text: 'text-rose-300', bg: 'bg-rose-500/10', border: 'border-rose-500/40', dot: 'bg-rose-400' },
  media: { label: 'Media', text: 'text-amber-300', bg: 'bg-amber-500/10', border: 'border-amber-500/40', dot: 'bg-amber-400' },
  baja: { label: 'Baja', text: 'text-sky-300', bg: 'bg-sky-500/10', border: 'border-sky-500/40', dot: 'bg-sky-400' },
};

export function incidentSeverityMeta(severidad: string) {
  return THREAT_SEVERITY_META[severidad] ?? THREAT_SEVERITY_META.media;
}

/** Color de acento por función CSF (docs/03 §1), compartido por el dashboard y la comparación. */
export const FUNCTION_ACCENTS: Record<string, string> = {
  GV: '#a78bfa',
  ID: '#60a5fa',
  PR: '#34d399',
  DE: '#fbbf24',
  RS: '#fb7185',
  RC: '#2dd4bf',
};

/** Cruce con privacidad (docs/03 §7): criterios que tocan datos personales desde ciberseguridad. */
export const PRIVACY_CRITERIA = new Set([
  'CRI-ID-04',
  'CRI-PR-01',
  'CRI-PR-03',
  'CRI-PR-05',
  'CRI-DE-02',
  'CRI-RS-01',
  'CRI-RS-03',
  'CRI-RC-01',
  'CRI-RC-02',
  'CRI-RC-03',
]);

/** Relación con el Privacy Framework por criterio del cruce (docs/03 §7). */
export const PRIVACY_RELATION: Record<string, string> = {
  'CRI-ID-04': 'Identify-P',
  'CRI-PR-01': 'Protect-P',
  'CRI-PR-03': 'Protect-P',
  'CRI-PR-05': 'Protect-P',
  'CRI-DE-02': 'Protect-P + Detect',
  'CRI-RS-01': 'Protect-P + Respond',
  'CRI-RS-03': 'Protect-P + Respond',
  'CRI-RC-01': 'Protect-P + Recover',
  'CRI-RC-02': 'Protect-P + Recover',
  'CRI-RC-03': 'Protect-P + Recover',
};

/** Aclaración de alcance obligatoria en todo reporte con la dimensión de privacidad (docs/00 §6). */
export const PRIVACY_SCOPE_NOTE =
  'Cubre eventos de ciberseguridad que afectan datos personales; no es una evaluación integral de privacidad.';

const INCIDENT_ESTADO_META: Record<string, { label: string; text: string; bg: string; border: string; dot: string }> = {
  open: { label: 'Abierto', text: 'text-rose-300', bg: 'bg-rose-500/10', border: 'border-rose-500/40', dot: 'bg-rose-400' },
  triaged: { label: 'Triado', text: 'text-amber-300', bg: 'bg-amber-500/10', border: 'border-amber-500/40', dot: 'bg-amber-400' },
  contained: { label: 'Contenido', text: 'text-sky-300', bg: 'bg-sky-500/10', border: 'border-sky-500/40', dot: 'bg-sky-400' },
  recovering: { label: 'Recuperando', text: 'text-indigo-300', bg: 'bg-indigo-500/10', border: 'border-indigo-500/40', dot: 'bg-indigo-400' },
  closed: { label: 'Cerrado', text: 'text-emerald-300', bg: 'bg-emerald-500/10', border: 'border-emerald-500/40', dot: 'bg-emerald-400' },
};

export function incidentEstadoMeta(estado: string) {
  return (
    INCIDENT_ESTADO_META[estado] ?? {
      label: estado,
      text: 'text-slate-400',
      bg: 'bg-white/[0.04]',
      border: 'border-white/10',
      dot: 'bg-slate-500',
    }
  );
}

/** Un incidente está en el historial cuando alcanzó el estado terminal `closed` (docs/08 §4). */
export const isIncidentClosed = (estado: string): boolean => estado === 'closed';
