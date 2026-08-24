/**
 * Pure shared contract for the optional two-question reading-mode quiz.
 *
 * This module mirrors the backend `app.services.reading_mode_quiz` contract so
 * the answer-to-mode mapping is defined once per language and never hidden in
 * component conditionals. It is dependency-free and safe to unit test in
 * isolation. See issue #1735 (Phase 6 of #1685).
 *
 * Contract rules:
 * - Stable answer IDs map deterministically to a bandwidth and/or intent value.
 * - Quiz copy (wording) lives on the option objects, separate from the stable
 *   answer IDs, so wording can evolve without changing IDs or mappings.
 * - All valid combinations of one bandwidth answer and one intent answer
 *   produce a valid `SessionReadingMode`.
 * - A resolved quiz result is tagged with source `quiz` and is meant to apply
 *   only to the current session; this module persists nothing.
 * - No creator/Taste Bank logic is included here.
 */

export type ReadingBandwidth = 'light' | 'balanced' | 'deep'
export type ReadingIntent = 'balanced' | 'momentum' | 'familiar' | 'explore' | 'random'
export type ReadingModeSource = 'default' | 'inferred' | 'manual' | 'quiz'

export interface SessionReadingMode {
  bandwidth: ReadingBandwidth
  intent: ReadingIntent
  source: ReadingModeSource
}

export interface QuizAnswerOption {
  id: string
  copy: string
  bandwidth?: ReadingBandwidth
  intent?: ReadingIntent
}

export interface QuizQuestion {
  id: string
  prompt: string
  options: readonly QuizAnswerOption[]
}

export interface ReadingModeQuiz {
  id: string
  title: string
  questions: readonly QuizQuestion[]
}

export const BANDWIDTH_QUESTION_ID = 'bandwidth'
export const INTENT_QUESTION_ID = 'intent'

export const READING_MODE_QUIZ: ReadingModeQuiz = {
  id: 'reading-mode-v1',
  title: 'Reading mode',
  questions: [
    {
      id: BANDWIDTH_QUESTION_ID,
      prompt: 'How much brain do you have right now?',
      options: [
        { id: 'light', copy: 'Easy', bandwidth: 'light' },
        { id: 'balanced', copy: 'Normal', bandwidth: 'balanced' },
        { id: 'deep', copy: 'Give me something substantial', bandwidth: 'deep' },
      ],
    },
    {
      id: INTENT_QUESTION_ID,
      prompt: 'What kind of pick sounds good?',
      options: [
        { id: 'momentum', copy: 'Keep something going', intent: 'momentum' },
        { id: 'familiar', copy: 'Something familiar', intent: 'familiar' },
        { id: 'explore', copy: 'Something different', intent: 'explore' },
        { id: 'random', copy: "Don't overthink it", intent: 'random' },
      ],
    },
  ],
}

export function getReadingModeQuiz(): ReadingModeQuiz {
  return READING_MODE_QUIZ
}

function findOption(
  question: QuizQuestion,
  answerId: string,
): QuizAnswerOption | undefined {
  return question.options.find((option) => option.id === answerId)
}

export function resolveQuizAnswers(answers: Record<string, string>): SessionReadingMode {
  let bandwidth: ReadingBandwidth | undefined
  let intent: ReadingIntent | undefined

  for (const question of READING_MODE_QUIZ.questions) {
    const answerId = answers[question.id]
    if (answerId === undefined) {
      continue
    }
    const option = findOption(question, answerId)
    if (!option) {
      throw new Error(`Unknown answer '${answerId}' for question '${question.id}'`)
    }
    if (option.bandwidth !== undefined) {
      bandwidth = option.bandwidth
    }
    if (option.intent !== undefined) {
      intent = option.intent
    }
  }

  if (bandwidth === undefined || intent === undefined) {
    throw new Error('Reading-mode quiz requires both a bandwidth and an intent answer')
  }

  return { bandwidth, intent, source: 'quiz' }
}
