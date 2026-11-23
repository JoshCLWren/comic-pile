import { fireEvent, render, screen, waitFor } from './testingLibrary'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ReadingModeQuiz from '../components/ReadingModeQuiz'
import type { QuizQuestion, ReadingModeState } from '../types'
import * as readingMode from '../services/readingMode'

const QUIZ_QUESTIONS: QuizQuestion[] = [
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
]

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(readingMode, 'getQuizQuestions').mockReturnValue(QUIZ_QUESTIONS)
  vi.spyOn(readingMode, 'setReadingModeFromQuiz').mockResolvedValue({
    bandwidth: 'balanced',
    intent: 'momentum',
    source: 'quiz',
    suggested: false,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
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
  vi.mocked(readingMode.setReadingModeFromQuiz).mockResolvedValue(resolved)

  render(<Harness onComplete={onComplete} />)

  // Question 1
  expect(screen.getByText('How much brain do you have right now?')).toBeInTheDocument()
  await user.click(screen.getByTestId('quiz-answer-brainpower-substantial'))
  await user.click(screen.getByTestId('reading-mode-quiz-next'))

  // Question 2
  expect(screen.getByText('What kind of pick sounds good?')).toBeInTheDocument()
  await user.click(screen.getByTestId('quiz-answer-pick-explore'))
  await user.click(screen.getByTestId('reading-mode-quiz-next'))

  await waitFor(() => expect(readingMode.setReadingModeFromQuiz).toHaveBeenCalledTimes(1))
  expect(readingMode.setReadingModeFromQuiz).toHaveBeenCalledWith({
    brainpower: 'substantial',
    pick: 'explore',
  })
  expect(onComplete).toHaveBeenCalledWith(resolved)
})

it('cannot advance without selecting an answer', async () => {
  const user = userEvent.setup()
  render(<Harness />)

  // SAFETY: the selector matches only the control the component rendered
  const next = screen.getByTestId('reading-mode-quiz-next') as HTMLButtonElement
  expect(next.disabled).toBe(true)
  await user.click(next)
  expect(readingMode.setReadingModeFromQuiz).not.toHaveBeenCalled()
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
  expect(readingMode.setReadingModeFromQuiz).not.toHaveBeenCalled()
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
