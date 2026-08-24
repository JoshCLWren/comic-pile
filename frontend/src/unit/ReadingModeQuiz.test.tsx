import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import ReadingModeQuiz from '../components/ReadingModeQuiz'
import type { ReadingModeState } from '../types'

vi.mock('../services/readingMode', () => ({
  getQuizQuestions: () => [
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
  ],
  setReadingModeFromQuiz: vi.fn(),
}))

import { setReadingModeFromQuiz } from '../services/readingMode'

beforeEach(() => {
  vi.resetAllMocks()
})

function Harness({ onComplete }: { onComplete?: (s: ReadingModeState) => void }) {
  const [open, setOpen] = useState(true)
  return (
    <ReadingModeQuiz
      isOpen={open}
      onClose={() => setOpen(false)}
      onComplete={onComplete}
    />
  )
}

it('completes the two-question flow and records source quiz', async () => {
  const user = userEvent.setup()
  const onComplete = vi.fn()
  const resolved: ReadingModeState = {
    bandwidth: 'deep',
    intent: 'explore',
    source: 'quiz',
    suggested: false,
  }
  vi.mocked(setReadingModeFromQuiz).mockResolvedValue(resolved)

  render(<Harness onComplete={onComplete} />)

  // Question 1
  expect(screen.getByText('How much brain do you have right now?')).toBeInTheDocument()
  await user.click(screen.getByTestId('quiz-answer-brainpower-substantial'))
  await user.click(screen.getByTestId('reading-mode-quiz-next'))

  // Question 2
  expect(screen.getByText('What kind of pick sounds good?')).toBeInTheDocument()
  await user.click(screen.getByTestId('quiz-answer-pick-explore'))
  await user.click(screen.getByTestId('reading-mode-quiz-next'))

  await waitFor(() => expect(setReadingModeFromQuiz).toHaveBeenCalledTimes(1))
  expect(setReadingModeFromQuiz).toHaveBeenCalledWith({
    brainpower: 'substantial',
    pick: 'explore',
  })
  expect(onComplete).toHaveBeenCalledWith(resolved)
})

it('cannot advance without selecting an answer', async () => {
  const user = userEvent.setup()
  render(<Harness />)

  const next = screen.getByTestId('reading-mode-quiz-next') as HTMLButtonElement
  expect(next.disabled).toBe(true)
  await user.click(next)
  expect(setReadingModeFromQuiz).not.toHaveBeenCalled()
  // Still on question 1
  expect(screen.getByText('How much brain do you have right now?')).toBeInTheDocument()
})

it('cancel on the first question closes without submitting', async () => {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(
    <ReadingModeQuiz isOpen onClose={onClose} />
  )

  await user.click(screen.getByTestId('reading-mode-quiz-back'))
  expect(onClose).toHaveBeenCalled()
  expect(setReadingModeFromQuiz).not.toHaveBeenCalled()
})

it('back returns to the previous question', async () => {
  const user = userEvent.setup()
  render(<Harness />)

  await user.click(screen.getByTestId('quiz-answer-brainpower-easy'))
  await user.click(screen.getByTestId('reading-mode-quiz-next'))
  expect(screen.getByText('What kind of pick sounds good?')).toBeInTheDocument()

  await user.click(screen.getByTestId('reading-mode-quiz-back'))
  expect(screen.getByText('How much brain do you have right now?')).toBeInTheDocument()
})

it('exposes accessible radio semantics for answers', async () => {
  render(<Harness />)
  const options = screen.getAllByRole('radio')
  expect(options).toHaveLength(3)
  fireEvent.click(options[0])
  expect(options[0]).toHaveAttribute('aria-checked', 'true')
})
