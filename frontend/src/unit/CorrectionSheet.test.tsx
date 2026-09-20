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

  it('renders all five correction choices as answers to one question', () => {
    render(<CorrectionSheet isOpen={true} onClose={vi.fn()} onSubmit={vi.fn()} />)

    expect(screen.getByTestId('correction-sheet')).toBeInTheDocument()
    expect(screen.getByText('Not feeling it?')).toBeInTheDocument()
    expect(screen.getByText('What should change about the next roll?')).toBeInTheDocument()
    expect(screen.getByTestId('correction-choice-even_easier')).toHaveTextContent(
      'Give me something lighter',
    )
    expect(screen.getByTestId('correction-choice-keep_level_different')).toHaveTextContent(
      'Keep about the same effort',
    )
    expect(screen.getByTestId('correction-choice-something_familiar')).toHaveTextContent(
      'Stay close to what I’ve liked',
    )
    expect(screen.getByTestId('correction-choice-something_different')).toHaveTextContent(
      'Give me a change of pace',
    )
    expect(screen.getByTestId('correction-choice-pure_random')).toHaveTextContent('Surprise me')
    expect(screen.getByTestId('correction-sheet-dismiss')).toHaveTextContent('Dismiss')
  })

  it('uses plain language with no recommendation-model vocabulary', () => {
    const { container } = render(
      <CorrectionSheet isOpen={true} onClose={vi.fn()} onSubmit={vi.fn()} />,
    )

    const text = container.textContent ?? ''
    expect(text).not.toMatch(/keep this level/i)
    expect(text).not.toMatch(/level/i)
    expect(text).not.toMatch(/bandwidth/i)
    expect(text).not.toMatch(/\bintent\b/i)
  })

  it('renders personalized examples as subordinate lines without changing patches', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(
      <CorrectionSheet
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={onSubmit}
        examples={{
          even_easier: 'Superman’s Pal Jimmy Olsen #134',
          something_familiar: 'Planetary / Hellboy',
        }}
      />,
    )

    expect(screen.getByTestId('correction-example-even_easier')).toHaveTextContent(
      'Superman’s Pal Jimmy Olsen #134',
    )
    expect(screen.getByTestId('correction-example-something_familiar')).toHaveTextContent(
      'Planetary / Hellboy',
    )
    // Options without an honest example degrade to descriptive copy.
    expect(screen.queryByTestId('correction-example-keep_level_different')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-example-something_different')).not.toBeInTheDocument()

    // Examples are explanatory only: selection still uses the canonical patch.
    await user.click(screen.getByTestId('correction-choice-even_easier'))
    expect(onSubmit).toHaveBeenCalledWith('even_easier', { bandwidth: 'light' })
  })

  it('degrades cleanly to descriptive copy when history is insufficient', () => {
    render(<CorrectionSheet isOpen={true} onClose={vi.fn()} onSubmit={vi.fn()} />)

    expect(screen.getByTestId('correction-choice-something_familiar')).toHaveTextContent(
      'Favor something similar to comics you’ve rated well.',
    )
    expect(screen.queryByTestId('correction-example-even_easier')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-example-keep_level_different')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-example-something_familiar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-example-something_different')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-example-pure_random')).not.toBeInTheDocument()
  })

  it('never shows an example for Surprise me and states steering is off', () => {
    render(
      <CorrectionSheet
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
        examples={{ pure_random: 'Saga' }}
      />,
    )

    expect(screen.getByTestId('correction-choice-pure_random')).toHaveTextContent(
      'Don’t steer by your past ratings or reading effort for this reroll.',
    )
    expect(screen.queryByTestId('correction-example-pure_random')).not.toBeInTheDocument()
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
    expect(screen.getByTestId('correction-sheet-error')).toHaveTextContent(
      'Failed to update reading mode. Please try again.',
    )
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
