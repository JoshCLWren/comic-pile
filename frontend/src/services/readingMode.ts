import api from './api'
import type {
  QuizQuestion,
  ReadingModeSource,
  ReadingModeState,
} from '../types'

export const QUIZ_QUESTIONS: QuizQuestion[] = [
  {
    id: 'brainpower',
    prompt: 'How much brain do you have right now?',
    answers: [
      { id: 'easy', label: 'Easy', bandwidth: 'light' },
      { id: 'normal', label: 'Normal', bandwidth: 'balanced' },
      { id: 'substantial', label: 'Give me something substantial', bandwidth: 'deep' },
    ],
  },
  {
    id: 'pick',
    prompt: 'What kind of pick sounds good?',
    answers: [
      { id: 'momentum', label: 'Keep something going', intent: 'momentum' },
      { id: 'familiar', label: 'Something familiar', intent: 'familiar' },
      { id: 'explore', label: 'Something different', intent: 'explore' },
      { id: 'random', label: "Don't overthink it", intent: 'random' },
    ],
  },
]

export function getQuizQuestions(): QuizQuestion[] {
  return QUIZ_QUESTIONS
}

export async function getReadingMode(): Promise<ReadingModeState> {
  return api.get<ReadingModeState>('/v1/reading-mode')
}

export async function setReadingModeFromQuiz(
  answers: Record<string, string>,
): Promise<ReadingModeState> {
  return api.post<ReadingModeState>('/v1/reading-mode', {
    answers,
    // SAFETY: the quiz flow always records the source as 'quiz' in the payload contract.
    source: 'quiz' as ReadingModeSource,
  })
}

export async function setReadingModeManual(
  bandwidth: string,
  intent: string,
): Promise<ReadingModeState> {
  return api.post<ReadingModeState>('/v1/reading-mode', {
    bandwidth,
    intent,
    // SAFETY: the manual flow always records the source as 'manual' in the payload contract.
    source: 'manual' as ReadingModeSource,
  })
}

export async function dismissReadingModeSuggestion(): Promise<ReadingModeState> {
  return api.post<ReadingModeState>('/v1/reading-mode/dismiss-suggestion')
}

export async function suggestReadingMode(): Promise<ReadingModeState> {
  return api.post<ReadingModeState>('/v1/reading-mode/suggest')
}
