import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReadingMode } from '../types/readingMode'
import ReadingQuizModal from '../pages/RollPage/components/ReadingQuizModal'

function renderQuiz(overrides: Partial<Parameters<typeof ReadingQuizModal>[0]> = {}) {
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  const onClose = vi.fn()
  render(
    <ReadingQuizModal
      isOpen
      onClose={onClose}
      initialBandwidthAnswerId={null}
      initialIntentAnswerId={null}
      onSubmit={onSubmit}
      {...overrides}
    />,
  )
  return { onSubmit, onClose }
}

describe('ReadingQuizModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('completes in exactly two selections and submits with the quiz source', async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderQuiz()

    // Question 1 is visible first.
    expect(screen.getByText('How much brain do you have right now?')).toBeInTheDocument()
    await user.click(screen.getByTestId('quiz-answer-easy'))

    // Question 2 replaces question 1 without any extra decision.
    expect(screen.getByText('What kind of pick sounds good?')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('quiz-answer-momentum'))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith({ bandwidth: 'light', intent: 'momentum' })
  })

  it.each([
    ['normal', 'familiar', 'balanced', 'familiar'],
    ['substantial', 'explore', 'deep', 'explore'],
    ['substantial', 'random', 'deep', 'random'],
    ['normal', 'momentum', 'balanced', 'momentum'],
  ] as const)(
    'maps %s + %s deterministically',
    async (bandwidthAnswer, intentAnswer, bandwidth, intent) => {
      const user = userEvent.setup()
      const { onSubmit } = renderQuiz()

      await user.click(screen.getByTestId(`quiz-answer-${bandwidthAnswer}`))
      await user.click(screen.getByTestId(`quiz-answer-${intentAnswer}`))

      await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
      expect(onSubmit).toHaveBeenCalledWith({ bandwidth, intent })
    },
  )

  it('cancel after the first selection never submits and closes unchanged', async () => {
    const user = userEvent.setup()
    const { onSubmit, onClose } = renderQuiz()

    await user.click(screen.getByTestId('quiz-answer-easy'))
    expect(screen.getByText('What kind of pick sounds good?')).toBeInTheDocument()

    await user.click(screen.getByTestId('quiz-cancel'))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('back returns to question one while preserving the intent choice for resubmission', async () => {
    const user = userEvent.setup()
    const failingSubmit = vi.fn<(mode: ReadingMode) => Promise<void>>().mockRejectedValueOnce(
      new Error('network down'),
    )
    const { onClose } = renderQuiz({ onSubmit: failingSubmit })

    await user.click(screen.getByTestId('quiz-answer-substantial'))
    await user.click(screen.getByTestId('quiz-answer-random'))

    // Submission failed, so the quiz stays open with an error and no close.
    await waitFor(() => expect(failingSubmit).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('alert')).toHaveTextContent(/failed to save/i)
    expect(onClose).not.toHaveBeenCalled()

    await user.click(screen.getByTestId('quiz-back'))
    expect(screen.getByText('How much brain do you have right now?')).toBeInTheDocument()
    expect(screen.getByTestId('quiz-answer-substantial')).toHaveAttribute('aria-pressed', 'true')

    // Re-answering question one keeps the prior intent choice and resubmits both.
    await user.click(screen.getByTestId('quiz-answer-easy'))
    expect(screen.getByText('What kind of pick sounds good?')).toBeInTheDocument()
    expect(screen.getByTestId('quiz-answer-random')).toHaveAttribute('aria-pressed', 'true')

    failingSubmit.mockResolvedValueOnce(undefined)
    await user.click(screen.getByTestId('quiz-answer-random'))
    await waitFor(() =>
      expect(failingSubmit).toHaveBeenLastCalledWith({ bandwidth: 'light', intent: 'random' }),
    )
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('seeds selections from the current session mode when reopened', async () => {
    renderQuiz({
      initialBandwidthAnswerId: 'deep',
      initialIntentAnswerId: 'familiar',
    })

    // Both axes already answered: starts on question two with prior picks pressed.
    expect(screen.getByText('What kind of pick sounds good?')).toBeInTheDocument()
    expect(screen.queryByText('How much brain do you have right now?')).toBeNull()
    expect(screen.getByTestId('quiz-answer-familiar')).toHaveAttribute('aria-pressed', 'true')
  })
})
