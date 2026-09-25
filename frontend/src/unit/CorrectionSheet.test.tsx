import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import CorrectionSheet from '../components/CorrectionSheet'

describe('CorrectionSheet', () => {
  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <CorrectionSheet isOpen={false} onClose={vi.fn()} onSubmit={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders all five correction choices when open', () => {
    render(<CorrectionSheet isOpen={true} onClose={vi.fn()} onSubmit={vi.fn()} />)

    expect(screen.getByTestId('correction-sheet')).toBeInTheDocument()
    expect(screen.getByText('Not the vibe?')).toBeInTheDocument()
    expect(screen.getByTestId('correction-choice-even_easier')).toHaveTextContent('Give me something lighter')
    expect(screen.getByTestId('correction-choice-keep_level_different')).toHaveTextContent('Keep about the same effort')
    expect(screen.getByTestId('correction-choice-something_familiar')).toHaveTextContent("Stay close to what I've liked")
    expect(screen.getByTestId('correction-choice-something_different')).toHaveTextContent('Give me a change of pace')
    expect(screen.getByTestId('correction-choice-pure_random')).toHaveTextContent('Surprise me')
    expect(screen.getByTestId('correction-sheet-dismiss')).toHaveTextContent('Dismiss')
  })

  it('shows explanations for every steerable choice', () => {
    render(<CorrectionSheet isOpen={true} onClose={vi.fn()} onSubmit={vi.fn()} />)

    expect(screen.getByTestId('correction-choice-even_easier')).toHaveTextContent('Favor a lower-commitment/easier read.')
    expect(screen.getByTestId('correction-choice-keep_level_different')).toHaveTextContent('Keep the current commitment level, but choose another comic.')
    expect(screen.getByTestId('correction-choice-something_familiar')).toHaveTextContent('Favor something similar to comics I\'ve rated well.')
    expect(screen.getByTestId('correction-choice-something_different')).toHaveTextContent('Favor something meaningfully different from recent/high-rated reads.')
  })

  it('shows Surprise me explanation that steering is not applied', () => {
    render(<CorrectionSheet isOpen={true} onClose={vi.fn()} onSubmit={vi.fn()} />)

    const surpriseButton = screen.getByTestId('correction-choice-pure_random')
    expect(surpriseButton).toHaveTextContent('Surprise me')
    expect(surpriseButton).toHaveTextContent('Do not steer by similarity or effort preference for this reroll.')
  })

  it('shows personalized examples when provided', () => {
    render(
      <CorrectionSheet
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
        examples={{
          something_familiar: 'Based on your ratings, think more Planetary / Hellboy territory.',
          pure_random: null,
          even_easier: 'Think more like Superman\'s Pal Jimmy Olsen #134.',
        }}
      />,
    )

    expect(screen.getByTestId('correction-choice-something_familiar')).toHaveTextContent('Based on your ratings, think more Planetary / Hellboy territory.')
    expect(screen.getByTestId('correction-choice-even_easier')).toHaveTextContent("Think more like Superman's Pal Jimmy Olsen #134.")
    // Surprise me explicitly has no fabricated preference signal
    expect(screen.getByTestId('correction-choice-pure_random')).not.toHaveTextContent('Based on your ratings')
  })

  it('degrades cleanly when no personalized examples exist', () => {
    render(<CorrectionSheet isOpen={true} onClose={vi.fn()} onSubmit={vi.fn()} />)

    const familiarButton = screen.getByTestId('correction-choice-something_familiar')
    expect(familiarButton).toHaveTextContent("Stay close to what I've liked")
    expect(familiarButton).toHaveTextContent('Favor something similar to comics I\'ve rated well.')
  })

  it('submits the correct patch for each choice', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    render(<CorrectionSheet isOpen={true} onClose={onClose} onSubmit={onSubmit} />)

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

    render(<CorrectionSheet isOpen={true} onClose={onClose} onSubmit={onSubmit} />)

    await user.click(screen.getByTestId('correction-sheet-dismiss'))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('shows error state on submit failure', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockRejectedValue(new Error('API error'))
    const onClose = vi.fn()

    render(<CorrectionSheet isOpen={true} onClose={onClose} onSubmit={onSubmit} />)

    await user.click(screen.getByTestId('correction-choice-even_easier'))
    expect(screen.getByTestId('correction-sheet-error')).toHaveTextContent('Failed to update reading mode. Please try again.')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('disables choices while submitting', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockImplementation(() => new Promise(() => {}))
    const onClose = vi.fn()

    render(<CorrectionSheet isOpen={true} onClose={onClose} onSubmit={onSubmit} />)

    await user.click(screen.getByTestId('correction-choice-even_easier'))
    expect(screen.getByTestId('correction-choice-keep_level_different')).toBeDisabled()
    expect(screen.getByTestId('correction-sheet-dismiss')).toBeDisabled()
  })

  it('is accessible by keyboard', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    render(<CorrectionSheet isOpen={true} onClose={onClose} onSubmit={onSubmit} />)

    await user.tab()
    expect(screen.getByTestId('correction-choice-even_easier')).toHaveFocus()

    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('even_easier', { bandwidth: 'light' })
  })

  it('hides the quiz suggestion when quizEnabled is false', () => {
    render(
      <CorrectionSheet
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
        quizEnabled={false}
        onOpenQuiz={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('correction-sheet-open-quiz')).not.toBeInTheDocument()
  })

  it('opens the quiz from the suggestion link when enabled', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onOpenQuiz = vi.fn()

    render(
      <CorrectionSheet
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        quizEnabled={true}
        onOpenQuiz={onOpenQuiz}
      />,
    )

    await user.click(screen.getByTestId('correction-sheet-open-quiz'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onOpenQuiz).toHaveBeenCalledTimes(1)
  })

  it('dismiss closes the sheet without opening the quiz', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onOpenQuiz = vi.fn()

    render(
      <CorrectionSheet
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        quizEnabled={true}
        onOpenQuiz={onOpenQuiz}
      />,
    )

    await user.click(screen.getByTestId('correction-sheet-dismiss'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onOpenQuiz).not.toHaveBeenCalled()
  })
})
