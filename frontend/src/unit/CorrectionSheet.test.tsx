import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import CorrectionSheet, { deriveCorrectionExamples } from '../components/CorrectionSheet'

function renderSheet(props: Partial<React.ComponentProps<typeof CorrectionSheet>> = {}) {
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <CorrectionSheet
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
        ratedHistory={[]}
        {...props}
      />
    </QueryClientProvider>,
  )
}

describe('CorrectionSheet', () => {
  it('renders nothing when isOpen is false', () => {
    const client = new QueryClient()
    const { container } = render(
      <QueryClientProvider client={client}>
        <CorrectionSheet isOpen={false} onClose={vi.fn()} onSubmit={vi.fn()} ratedHistory={[]} />
      </QueryClientProvider>,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders coherent plain-language choices answering the same question', () => {
    renderSheet()

    expect(screen.getByTestId('correction-sheet')).toBeInTheDocument()
    expect(screen.getByText('Not feeling it?')).toBeInTheDocument()
    expect(screen.getByTestId('correction-sheet-subtitle')).toHaveTextContent('What should change about the next roll?')
    expect(screen.getByTestId('correction-choice-even_easier')).toHaveTextContent('Give me something lighter')
    expect(screen.getByTestId('correction-choice-keep_level_different')).toHaveTextContent('Keep about the same effort')
    expect(screen.getByTestId('correction-choice-something_familiar')).toHaveTextContent('Stay close to what I')
    expect(screen.getByTestId('correction-choice-something_different')).toHaveTextContent('Give me a change of pace')
    expect(screen.getByTestId('correction-choice-pure_random')).toHaveTextContent('Surprise me')
    expect(screen.getByTestId('correction-sheet-dismiss')).toHaveTextContent('Dismiss')
    // Old ambiguous wording must not appear
    expect(screen.queryByText('Keep this level')).not.toBeInTheDocument()
    expect(screen.queryByText('Even easier')).not.toBeInTheDocument()
    expect(screen.queryByText('Pure random')).not.toBeInTheDocument()
  })

  it('does not expose raw model vocabulary like level/bandwidth/intent', () => {
    renderSheet()
    const sheet = screen.getByTestId('correction-sheet').textContent ?? ''
    expect(sheet.toLowerCase()).not.toMatch(/\blevel\b/)
    expect(sheet.toLowerCase()).not.toMatch(/\bbandwidth\b/)
    expect(sheet.toLowerCase()).not.toMatch(/\bintent\b/)
  })

  it('submits the correct canonical patch for each choice', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    renderSheet({ onSubmit, onClose, ratedHistory: [] })

    await user.click(screen.getByTestId('correction-choice-even_easier'))
    expect(onSubmit).toHaveBeenCalledWith('even_easier', { bandwidth: 'light' })
    expect(onClose).toHaveBeenCalledTimes(1)

    await user.click(screen.getByTestId('correction-choice-keep_level_different'))
    expect(onSubmit).toHaveBeenCalledWith('keep_level_different', { intent: 'balanced' })

    await user.click(screen.getByTestId('correction-choice-something_familiar'))
    expect(onSubmit).toHaveBeenCalledWith('something_familiar', { intent: 'familiar' })

    await user.click(screen.getByTestId('correction-choice-something_different'))
    expect(onSubmit).toHaveBeenCalledWith('something_different', { intent: 'explore' })

    await user.click(screen.getByTestId('correction-choice-pure_random'))
    expect(onSubmit).toHaveBeenCalledWith('pure_random', { intent: 'random' })
  })

  it('dismiss closes without calling onSubmit', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    const onClose = vi.fn()

    renderSheet({ onSubmit, onClose })

    await user.click(screen.getByTestId('correction-sheet-dismiss'))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('shows error state on submit failure', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockRejectedValue(new Error('API error'))
    const onClose = vi.fn()

    renderSheet({ onSubmit, onClose })

    await user.click(screen.getByTestId('correction-choice-even_easier'))
    expect(screen.getByTestId('correction-sheet-error')).toHaveTextContent('Failed to update reading mode. Please try again.')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('disables choices while submitting', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockImplementation(() => new Promise(() => {}))
    const onClose = vi.fn()

    renderSheet({ onSubmit, onClose })

    await user.click(screen.getByTestId('correction-choice-even_easier'))
    expect(screen.getByTestId('correction-choice-keep_level_different')).toBeDisabled()
    expect(screen.getByTestId('correction-sheet-dismiss')).toBeDisabled()
  })

  it('is accessible by keyboard', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    renderSheet({ onSubmit, onClose })

    await user.tab()
    expect(screen.getByTestId('correction-choice-even_easier')).toHaveFocus()

    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('even_easier', { bandwidth: 'light' })
  })

  it('hides the quiz suggestion when quizEnabled is false', () => {
    renderSheet({ quizEnabled: false, onOpenQuiz: vi.fn() })
    expect(screen.queryByTestId('correction-sheet-open-quiz')).not.toBeInTheDocument()
  })

  it('opens the quiz from the suggestion link when enabled', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onOpenQuiz = vi.fn()

    renderSheet({ quizEnabled: true, onClose, onOpenQuiz })

    await user.click(screen.getByTestId('correction-sheet-open-quiz'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onOpenQuiz).toHaveBeenCalledTimes(1)
  })

  it('dismiss closes the sheet without opening the quiz', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onOpenQuiz = vi.fn()

    renderSheet({ quizEnabled: true, onClose, onOpenQuiz })

    await user.click(screen.getByTestId('correction-sheet-dismiss'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onOpenQuiz).not.toHaveBeenCalled()
  })

  it('shows personalized examples from rated history', () => {
    const ratedHistory = [
      { id: 1, title: 'Planetary', rating: 5, format: 'Comic', issues_remaining: 2 },
      { id: 2, title: 'Hellboy', rating: 4.8, format: 'Comic', issues_remaining: 5 },
      { id: 3, title: 'Jimmy Olsen #134', rating: 4.2, format: 'Comic', issues_remaining: 1 },
    ]
    renderSheet({ ratedHistory })

    // Each steerable choice should have an example drawn from history
    expect(screen.getByTestId('correction-example-even_easier')).toHaveTextContent('Jimmy Olsen')
    expect(screen.getByTestId('correction-example-keep_level_different')).toHaveTextContent('Hellboy')
    expect(screen.getByTestId('correction-example-something_familiar')).toHaveTextContent('Planetary')
    expect(screen.getByTestId('correction-example-something_different')).toHaveTextContent('Jimmy Olsen')
    // Surprise me example is marked illustrative/random
    expect(screen.getByTestId('correction-example-pure_random')).toHaveTextContent('Illustrative')
    expect(screen.getByTestId('correction-example-pure_random')).toHaveTextContent('random')
  })

  it('degrades cleanly when history is insufficient — no invented example', () => {
    renderSheet({ ratedHistory: [] })

    // Surprise still shows fallback that explains no steering, not an invented title
    expect(screen.getByTestId('correction-example-pure_random')).toHaveTextContent('No preference signal applied')
    // Steerable choices have no example element when no history
    expect(screen.queryByTestId('correction-example-even_easier')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-example-something_familiar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-example-something_different')).not.toBeInTheDocument()
  })

  it('Surprise me clearly communicates no steering preference', () => {
    renderSheet({ ratedHistory: [] })
    expect(screen.getByTestId('correction-choice-pure_random')).toHaveTextContent('Don\u2019t steer by similarity or effort')
    expect(screen.getByTestId('correction-example-pure_random')).toHaveTextContent('No preference signal applied')
  })
})

describe('deriveCorrectionExamples', () => {
  it('returns null examples for empty history', () => {
    expect(deriveCorrectionExamples([])).toEqual({
      even_easier: null,
      keep_level_different: null,
      something_familiar: null,
      something_different: null,
      pure_random: null,
    })
    expect(deriveCorrectionExamples(null)).toEqual({
      even_easier: null,
      keep_level_different: null,
      something_familiar: null,
      something_different: null,
      pure_random: null,
    })
  })

  it('uses only provided rated titles, never invents', () => {
    const examples = deriveCorrectionExamples([
      { id: 1, title: 'Saga', rating: 5, format: 'Comic', issues_remaining: 3 },
    ])
    const values = Object.values(examples).filter(Boolean) as string[]
    for (const v of values) {
      expect(v).toContain('Saga')
    }
  })
})
