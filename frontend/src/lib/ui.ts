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
