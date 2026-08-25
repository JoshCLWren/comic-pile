import { describe, expect, it } from 'vitest'
import {
  BANDWIDTH_QUESTION_ID,
  INTENT_QUESTION_ID,
  READING_MODE_QUIZ,
  getReadingModeQuiz,
  resolveQuizAnswers,
} from '../services/readingModeQuiz'

function answerIdsFor(questionId: string): string[] {
  const question = READING_MODE_QUIZ.questions.find((q) => q.id === questionId)
  return question ? question.options.map((o) => o.id) : []
}

describe('reading-mode quiz contract', () => {
  it('exposes two questions with stable ids', () => {
    expect(READING_MODE_QUIZ.questions.map((q) => q.id)).toEqual([
      BANDWIDTH_QUESTION_ID,
      INTENT_QUESTION_ID,
    ])
  })

  it('maps every bandwidth answer id deterministically', () => {
    const expected: Record<string, 'light' | 'balanced' | 'deep'> = {
      light: 'light',
      balanced: 'balanced',
      deep: 'deep',
    }
    for (const [answerId, bandwidth] of Object.entries(expected)) {
      const mode = resolveQuizAnswers({
        [BANDWIDTH_QUESTION_ID]: answerId,
        [INTENT_QUESTION_ID]: 'momentum',
      })
      expect(mode.bandwidth).toBe(bandwidth)
    }
  })

  it('maps every intent answer id deterministically', () => {
    const expected: Record<string, 'momentum' | 'familiar' | 'explore' | 'random'> = {
      momentum: 'momentum',
      familiar: 'familiar',
      explore: 'explore',
      random: 'random',
    }
    for (const [answerId, intent] of Object.entries(expected)) {
      const mode = resolveQuizAnswers({
        [BANDWIDTH_QUESTION_ID]: 'balanced',
        [INTENT_QUESTION_ID]: answerId,
      })
      expect(mode.intent).toBe(intent)
    }
  })

  it('covers every answer in the quiz definition', () => {
    expect(answerIdsFor(BANDWIDTH_QUESTION_ID).sort()).toEqual(['balanced', 'deep', 'light'])
    expect(answerIdsFor(INTENT_QUESTION_ID).sort()).toEqual([
      'explore',
      'familiar',
      'momentum',
      'random',
    ])
  })

  it('produces a valid session mode for every combination', () => {
    const bandwidthIds = answerIdsFor(BANDWIDTH_QUESTION_ID)
    const intentIds = answerIdsFor(INTENT_QUESTION_ID)
    for (const bandwidthId of bandwidthIds) {
      for (const intentId of intentIds) {
        const mode = resolveQuizAnswers({
          [BANDWIDTH_QUESTION_ID]: bandwidthId,
          [INTENT_QUESTION_ID]: intentId,
        })
        expect(['light', 'balanced', 'deep']).toContain(mode.bandwidth)
        expect(['balanced', 'momentum', 'familiar', 'explore', 'random']).toContain(mode.intent)
        expect(mode.source).toBe('quiz')
      }
    }
  })

  it('keeps copy separate from stable answer ids', () => {
    for (const question of READING_MODE_QUIZ.questions) {
      for (const option of question.options) {
        expect(option.id).not.toBe(option.copy)
        expect((option.bandwidth === undefined) !== (option.intent === undefined)).toBe(true)
      }
    }
  })

  it('resolves using only stable ids, ignoring copy', () => {
    const mode = resolveQuizAnswers({
      [BANDWIDTH_QUESTION_ID]: 'deep',
      [INTENT_QUESTION_ID]: 'explore',
    })
    expect(mode).toEqual({ bandwidth: 'deep', intent: 'explore', source: 'quiz' })
  })

  it('throws on an unknown answer id', () => {
    expect(() =>
      resolveQuizAnswers({
        [BANDWIDTH_QUESTION_ID]: 'nope',
        [INTENT_QUESTION_ID]: 'momentum',
      }),
    ).toThrow()
  })

  it('throws when a dimension is missing', () => {
    expect(() => resolveQuizAnswers({ [BANDWIDTH_QUESTION_ID]: 'light' })).toThrow()
  })

  it('ignores unknown question ids', () => {
    const mode = resolveQuizAnswers({
      [BANDWIDTH_QUESTION_ID]: 'light',
      [INTENT_QUESTION_ID]: 'random',
      'future-question': 'ignored',
    })
    expect(mode).toEqual({ bandwidth: 'light', intent: 'random', source: 'quiz' })
  })

  it('returns the same shared quiz instance', () => {
    expect(getReadingModeQuiz()).toBe(READING_MODE_QUIZ)
  })
})
