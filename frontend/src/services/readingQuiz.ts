import type {
  QuizAnswerOption,
  QuizQuestion,
  ReadingBandwidth,
  ReadingIntent,
  ReadingMode,
} from '../types/readingMode'

/**
 * Two-question reading-mode quiz contract (frontend mirror of
 * `app/services/reading_quiz.py`).
 *
 * Stable answer IDs map deterministically to session bandwidth/intent. Copy may
 * evolve freely; the IDs and the mapping are the durable contract.
 */

export const BANDWIDTH_QUESTION_ID = 'brainpower'
export const INTENT_QUESTION_ID = 'pick'

export const QUIZ_QUESTIONS: QuizQuestion[] = [
  {
    id: BANDWIDTH_QUESTION_ID,
    prompt: 'How much brain do you have right now?',
    answers: [
      { id: 'easy', label: 'Easy' },
      { id: 'normal', label: 'Normal' },
      { id: 'substantial', label: 'Give me something substantial' },
    ],
  },
  {
    id: INTENT_QUESTION_ID,
    prompt: 'What kind of pick sounds good?',
    answers: [
      { id: 'momentum', label: 'Keep something going' },
      { id: 'familiar', label: 'Something familiar' },
      { id: 'explore', label: 'Something different' },
      { id: 'random', label: "Don't overthink it" },
    ],
  },
]

const ANSWERS_BY_QUESTION_ID: Record<string, QuizAnswerOption[]> = Object.fromEntries(
  QUIZ_QUESTIONS.map((question) => [question.id, question.answers]),
)

/** Bandwidth value selected by each stable bandwidth-question answer ID. */
export const BANDWIDTH_BY_ANSWER_ID: Record<string, ReadingBandwidth> = {
  easy: 'light',
  normal: 'balanced',
  substantial: 'deep',
}

/** Intent value selected by each stable intent-question answer ID. */
export const INTENT_BY_ANSWER_ID: Record<string, ReadingIntent> = {
  momentum: 'momentum',
  familiar: 'familiar',
  explore: 'explore',
  random: 'random',
}

const BANDWIDTH_ANSWER_ID_BY_VALUE: Record<ReadingBandwidth, string> = {
  light: 'easy',
  balanced: 'normal',
  deep: 'substantial',
}

/**
 * Intent value selected by each stable intent-question answer ID.
 *
 * The quiz never produces the `balanced` intent; it can only arrive through
 * partial manual/correction updates, so no answer ID maps to it.
 */
export const INTENT_ANSWER_ID_BY_VALUE: Partial<Record<ReadingIntent, string>> = {
  momentum: 'momentum',
  familiar: 'familiar',
  explore: 'explore',
  random: 'random',
}

const DISPLAY_LABELS: Record<string, string> = {
  light: 'Light',
  balanced: 'Balanced',
  deep: 'Deep',
  momentum: 'Momentum',
  familiar: 'Familiar',
  explore: 'Explore',
  random: 'Random',
}

/**
 * Resolve one answered quiz into a deterministic reading mode.
 *
 * Args:
 *   bandwidthAnswerId: Stable answer ID chosen for the bandwidth question.
 *   intentAnswerId: Stable answer ID chosen for the intent question.
 *
 * Returns:
 *   The resolved bandwidth/intent pair to submit with source `quiz`.
 *
 * Throws:
 *   Error when an answer ID is unknown for its question.
 */
export function resolveReadingMode(
  bandwidthAnswerId: string,
  intentAnswerId: string,
): ReadingMode {
  const bandwidth = BANDWIDTH_BY_ANSWER_ID[bandwidthAnswerId]
  if (!bandwidth || !ANSWERS_BY_QUESTION_ID[BANDWIDTH_QUESTION_ID]?.some((a) => a.id === bandwidthAnswerId)) {
    throw new Error(`Unknown quiz answer: ${bandwidthAnswerId}`)
  }
  const intent = INTENT_BY_ANSWER_ID[intentAnswerId]
  if (!intent || !ANSWERS_BY_QUESTION_ID[INTENT_QUESTION_ID]?.some((a) => a.id === intentAnswerId)) {
    throw new Error(`Unknown quiz answer: ${intentAnswerId}`)
  }
  return { bandwidth, intent }
}

/** Return the stable answer ID that produced a persisted bandwidth value. */
export function answerIdForBandwidth(bandwidth: ReadingBandwidth): string | null {
  return BANDWIDTH_ANSWER_ID_BY_VALUE[bandwidth] ?? null
}

/** Return the stable answer ID that produced a persisted intent value. */
export function answerIdForIntent(intent: ReadingIntent): string | null {
  return INTENT_ANSWER_ID_BY_VALUE[intent] ?? null
}

/** Return true when the value is a known reading-mode bandwidth. */
export function isReadingBandwidth(value: unknown): value is ReadingBandwidth {
  return value === 'light' || value === 'balanced' || value === 'deep'
}

/** Return true when the value is a known reading-mode intent. */
export function isReadingIntent(value: unknown): value is ReadingIntent {
  return (
    value === 'balanced'
    || value === 'momentum'
    || value === 'familiar'
    || value === 'explore'
    || value === 'random'
  )
}

/** Human-readable label for a single mode value, e.g. `Light`. */
export function readingModeValueLabel(value: string): string {
  return DISPLAY_LABELS[value] ?? value
}

/** Human-readable two-part mode label, e.g. `Light · Momentum`. */
export function formatReadingModeLabel(bandwidth: string, intent: string): string {
  return `${readingModeValueLabel(bandwidth)} · ${readingModeValueLabel(intent)}`
}
