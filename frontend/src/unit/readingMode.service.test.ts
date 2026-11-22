import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import api from '../services/api'
import {
  QUIZ_QUESTIONS,
  dismissReadingModeSuggestion,
  getQuizQuestions,
  getReadingMode,
  setReadingModeFromQuiz,
  setReadingModeManual,
  suggestReadingMode,
} from '../services/readingMode'

const originalGet = api.get
const originalPost = api.post
const originalPut = api.put

beforeEach(() => {
  vi.clearAllMocks()
  // SAFETY: test mock assertion; the cast targets an injected test double with a compatible runtime shape
  api.get = vi.fn() as typeof api.get
  // SAFETY: test mock assertion; the cast targets an injected test double with a compatible runtime shape
  api.post = vi.fn() as typeof api.post
  // SAFETY: test mock assertion; the cast targets an injected test double with a compatible runtime shape
  api.put = vi.fn() as typeof api.put
})

afterEach(() => {
  api.get = originalGet
  api.post = originalPost
  api.put = originalPut
})

describe('readingMode service', () => {
  it('returns the static quiz questions', () => {
    expect(getQuizQuestions()).toEqual(QUIZ_QUESTIONS)
    expect(getQuizQuestions()).toHaveLength(2)
  })

  it('gets reading mode state from the v2 endpoint', async () => {
    const state = { suggested: false, source: null }
    vi.mocked(api.get).mockResolvedValue(state)

    await expect(getReadingMode()).resolves.toEqual(state)
    expect(api.get).toHaveBeenCalledWith('/v2/reading-mode')
  })

  it('sets reading mode from quiz answers on the v2 endpoint', async () => {
    const state = { suggested: false, source: 'quiz' }
    vi.mocked(api.put).mockResolvedValue(state)
    const answers = { brainpower: 'easy', pick: 'momentum' }

    await expect(setReadingModeFromQuiz(answers)).resolves.toEqual(state)
    expect(api.put).toHaveBeenCalledWith('/v2/reading-mode', {
      answers,
      source: 'quiz',
    })
  })

  it('sets reading mode manually on the v2 endpoint', async () => {
    const state = { suggested: false, source: 'manual' }
    vi.mocked(api.put).mockResolvedValue(state)

    await expect(setReadingModeManual('light', 'explore')).resolves.toEqual(state)
    expect(api.put).toHaveBeenCalledWith('/v2/reading-mode', {
      bandwidth: 'light',
      intent: 'explore',
      source: 'manual',
    })
  })

  it('dismisses a reading mode suggestion on the v2 endpoint', async () => {
    const state = { suggested: false, source: null }
    vi.mocked(api.post).mockResolvedValue(state)

    await expect(dismissReadingModeSuggestion()).resolves.toEqual(state)
    expect(api.post).toHaveBeenCalledWith('/v2/reading-mode/suggestion-dismissals')
  })

  it('requests a reading mode suggestion on the v2 endpoint', async () => {
    const state = { suggested: true, source: null }
    vi.mocked(api.post).mockResolvedValue(state)

    await expect(suggestReadingMode()).resolves.toEqual(state)
    expect(api.post).toHaveBeenCalledWith('/v2/reading-mode/suggestions')
  })
})
