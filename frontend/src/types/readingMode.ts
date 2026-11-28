import type { ReadingBandwidth, ReadingIntent } from './index'

/** Compact display projection from the canonical scoped reading-mode resource. */
export interface ReadingModeDisplay {
  bandwidth: ReadingBandwidth | string | null
  intent: ReadingIntent | string | null
  source?: string | null
  confidence?: number | null
  version?: string | number | null
}

/** Human-readable label for a bandwidth or intent value; falls back to the raw value. */
export function readingModeLabel(value: string | null | undefined): string {
  if (!value) return ''
  const normalized = value.trim().toLowerCase()
  if (normalized === 'balanced') return 'Balanced'
  if (normalized === 'light') return 'Light'
  if (normalized === 'deep') return 'Deep'
  if (normalized === 'momentum') return 'Momentum'
  if (normalized === 'familiar') return 'Familiar'
  if (normalized === 'explore') return 'Explore'
  if (normalized === 'random') return 'Random'
  return value.trim()
}

/** Compact `Bandwidth · Intent` summary for header-scale mode controls. */
export function formatReadingMode(mode: ReadingModeDisplay | null | undefined): string {
  if (!mode) return ''
  const parts = [readingModeLabel(mode.bandwidth), readingModeLabel(mode.intent)].filter(Boolean)
  return parts.join(' · ')
}
