/** Stable reading-mode contract shared by the quiz UI and the session-mode API. */

export type ReadingBandwidth = 'light' | 'balanced' | 'deep'
export type ReadingIntent = 'balanced' | 'momentum' | 'familiar' | 'explore' | 'random'
export type SessionModeSource = 'quiz' | 'manual' | 'correction'

/** One stable quiz answer option; IDs never change even when copy evolves. */
export interface QuizAnswerOption {
  id: string
  label: string
}

/** One quiz question with its stable answer options. */
export interface QuizQuestion {
  id: string
  prompt: string
  answers: QuizAnswerOption[]
}

/** Resolved reading mode submitted through the canonical session-mode API. */
export interface ReadingMode {
  bandwidth: ReadingBandwidth
  intent: ReadingIntent
}

/** Request payload for setting one session's reading mode. */
export interface SessionModeUpdateRequest {
  bandwidth?: ReadingBandwidth | null
  intent?: ReadingIntent | null
  source: SessionModeSource
}

/** Response describing one session's current reading mode. */
export interface SessionModeResponse {
  session_id: number
  bandwidth: string | null
  intent: string | null
  source: string | null
}
