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
    expect(screen.getByTestId('correction-choice-even_easier')).toHaveTextContent('Even easier')
    expect(screen.getByTestId('correction-choice-keep_level_different')).toHaveTextContent('Keep this level, different comic')
    expect(screen.getByTestId('correction-choice-something_familiar')).toHaveTextContent('Something familiar')
    expect(screen.getByTestId('correction-choice-something_different')).toHaveTextContent('Something different')
    expect(screen.getByTestId('correction-choice-pure_random')).toHaveTextContent('Pure random')
    expect(screen.getByTestId('correction-sheet-dismiss')).toHaveTextContent('Dismiss')
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
