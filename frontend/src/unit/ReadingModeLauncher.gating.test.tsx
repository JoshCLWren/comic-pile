import { render, screen } from './testingLibrary'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as readingMode from '../services/readingMode'
import { FEATURES } from '../config/features'
import ReadingModeLauncher from '../components/ReadingModeLauncher'
import type { ReadingModeState } from '../types'

const originalReadingModeQuiz = FEATURES.readingModeQuiz
const inactiveReadingMode: ReadingModeState = {
  bandwidth: null,
  intent: null,
  source: null,
  suggested: false,
}

describe('ReadingModeLauncher production gating (issue #1945)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(readingMode, 'getReadingMode').mockResolvedValue(inactiveReadingMode)
    vi.spyOn(readingMode, 'dismissReadingModeSuggestion').mockResolvedValue(inactiveReadingMode)
    vi.spyOn(readingMode, 'getQuizQuestions').mockReturnValue([])
    vi.spyOn(readingMode, 'setReadingModeFromQuiz').mockResolvedValue(inactiveReadingMode)
  })

  afterEach(() => {
    Object.assign(FEATURES, { readingModeQuiz: originalReadingModeQuiz })
    vi.restoreAllMocks()
  })

  it('renders nothing on the normal production Roll surface when the quiz feature is disabled', () => {
    Object.assign(FEATURES, { readingModeQuiz: false })

    const { container } = render(<ReadingModeLauncher />)

    expect(screen.queryByTestId('open-reading-mode-quiz')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-mode-suggestion')).not.toBeInTheDocument()
    expect(screen.queryByText('Find my reading mode')).not.toBeInTheDocument()
    expect(container).toBeEmptyDOMElement()
  })

  it('exposes the launcher and quiz entry point only when the feature is explicitly enabled', () => {
    Object.assign(FEATURES, { readingModeQuiz: true })

    render(<ReadingModeLauncher />)

    expect(screen.getByTestId('open-reading-mode-quiz')).toHaveTextContent(
      'Find my reading mode',
    )
  })
})
