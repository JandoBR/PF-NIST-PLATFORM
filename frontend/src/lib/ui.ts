import type { Status, Priority } from '@/data/mockData';

type ThreatSeverity = 'critical' | 'high' | 'medium' | 'low';

export const STATUS_META: Record<
  Status,
  { label: string; text: string; bg: string; border: string; dot: string; bar: string }
> = {
  compliant: {
    label: 'Compliant',
    text: 'text-emerald-300',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
    dot: 'bg-emerald-400',
    bar: 'bg-emerald-400',
  },
  partial: {
    label: 'Partial Gap',
    text: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    dot: 'bg-amber-400',
    bar: 'bg-amber-400',
  },
  critical: {
    label: 'Critical Gap',
    text: 'text-rose-300',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
    dot: 'bg-rose-400',
    bar: 'bg-rose-400',
  },
};

export const PRIORITY_META: Record<
  Priority,
  { label: string; text: string; bg: string; border: string }
> = {
  high: {
    label: 'High Priority',
    text: 'text-rose-300',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
  },
  medium: {
    label: 'Medium Priority',
    text: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
  },
  low: {
    label: 'Low Priority',
    text: 'text-sky-300',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/30',
  },
};

export const SEVERITY_META: Record<
  ThreatSeverity,
  { label: string; text: string; bg: string; border: string; dot: string }
> = {
  critical: {
    label: 'Critical',
    text: 'text-rose-300',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/40',
    dot: 'bg-rose-400',
  },
  high: {
    label: 'High',
    text: 'text-orange-300',
    bg: 'bg-orange-500/10',
    border: 'border-orange-500/40',
    dot: 'bg-orange-400',
  },
  medium: {
    label: 'Medium',
    text: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/40',
    dot: 'bg-amber-400',
  },
  low: {
    label: 'Low',
    text: 'text-sky-300',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/40',
    dot: 'bg-sky-400',
  },
};
