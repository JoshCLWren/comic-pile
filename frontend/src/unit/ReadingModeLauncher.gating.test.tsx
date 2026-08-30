import { render, screen } from '@testing-library/react'
import type { ComponentType } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../services/readingMode', () => ({
  getReadingMode: vi.fn().mockResolvedValue(null),
  dismissReadingModeSuggestion: vi.fn().mockResolvedValue(null),
  getQuizQuestions: vi.fn().mockReturnValue([]),
  setReadingModeFromQuiz: vi.fn(),
}))

async function loadLauncher(enabled: boolean): Promise<ComponentType> {
  vi.doMock('../config/features', () => ({
    FEATURES: { readingModeQuiz: enabled },
  }))
  vi.resetModules()
  const mod = await import('../components/ReadingModeLauncher')
  return mod.default
}

describe('ReadingModeLauncher production gating (issue #1945)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('renders nothing on the normal production Roll surface when the quiz feature is disabled', async () => {
    const Launcher = await loadLauncher(false)

    const { container } = render(<Launcher />)

    expect(screen.queryByTestId('open-reading-mode-quiz')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-mode-suggestion')).not.toBeInTheDocument()
    expect(screen.queryByText('Find my reading mode')).not.toBeInTheDocument()
    expect(container).toBeEmptyDOMElement()
  })

  it('exposes the launcher and quiz entry point only when the feature is explicitly enabled', async () => {
    const Launcher = await loadLauncher(true)

    render(<Launcher />)

    expect(screen.getByTestId('open-reading-mode-quiz')).toHaveTextContent(
      'Find my reading mode',
    )
  })
})
