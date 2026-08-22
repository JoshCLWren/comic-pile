/** Bandwidth describes how mentally demanding a comic is for the current moment. */
export type Bandwidth = 'light' | 'balanced' | 'deep'

/** Intent describes what kind of pick the reader wants right now. */
export type Intent = 'balanced' | 'momentum' | 'familiar' | 'explore' | 'random'

/** Combined reading mode for a session. */
export interface ReadingMode {
  bandwidth: Bandwidth
  intent: Intent
}

/** Source that produced the current mode values. */
export type ReadingModeSource = 'inferred' | 'manual' | 'snooze' | 'quiz'

export const BANDWIDTH_VALUES: Bandwidth[] = ['light', 'balanced', 'deep']
export const INTENT_VALUES: Intent[] = ['balanced', 'momentum', 'familiar', 'explore', 'random']

export function isBandwidth(value: string): value is Bandwidth {
  return (BANDWIDTH_VALUES as string[]).includes(value)
}

export function isIntent(value: string): value is Intent {
  return (INTENT_VALUES as string[]).includes(value)
}

export function formatReadingMode(mode: ReadingMode | null | undefined): string {
  if (!mode) return 'Balanced \u00B7 Balanced'
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
  return `${cap(mode.bandwidth)} \u00B7 ${cap(mode.intent)}`
}
