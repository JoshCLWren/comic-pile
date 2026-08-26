import { useCallback, useEffect, useMemo, useState } from 'react'
import Modal from '../components/Modal'
import { getQuizQuestions, setReadingModeFromQuiz } from '../services/readingMode'
import type { ReadingModeState } from '../types'

interface ReadingModeQuizProps {
  isOpen: boolean
  onClose: () => void
  onComplete?: (state: ReadingModeState) => void
}

/**
 * Optional two-question reading-mode quiz. Selecting both answers submits the
 * result through the canonical session-mode API with source `quiz`. Closing or
 * cancelling the modal never submits and therefore leaves the prior mode intact.
 */
export default function ReadingModeQuiz({ isOpen, onClose, onComplete }: ReadingModeQuizProps) {
  const questions = useMemo(() => getQuizQuestions(), [])
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setStep(0)
      setAnswers({})
      setSubmitting(false)
      setError(null)
    }
  }, [isOpen])

  const currentQuestion = questions[step]
  const selectedForStep = currentQuestion ? answers[currentQuestion.id] : undefined
  const isLastStep = step === questions.length - 1

  const selectAnswer = useCallback(
    (answerId: string) => {
      if (!currentQuestion) return
      setAnswers((prev) => ({ ...prev, [currentQuestion.id]: answerId }))
    },
    [currentQuestion],
  )

  const handleNext = useCallback(() => {
    if (selectedForStep === undefined) return
    if (isLastStep) {
      void submit()
    } else {
      setStep((s) => s + 1)
    }
  }, [selectedForStep, isLastStep])

  const handleBack = useCallback(() => {
    setError(null)
    if (step === 0) {
      onClose()
    } else {
      setStep((s) => s - 1)
    }
  }, [step, onClose])

  const submit = useCallback(async () => {
    setSubmitting(true)
    setError(null)
    try {
      const state = await setReadingModeFromQuiz(answers)
      onComplete?.(state)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save reading mode')
      setSubmitting(false)
    }
  }, [answers, onComplete, onClose])

  const canAdvance = selectedForStep !== undefined && !submitting

  return (
    <Modal isOpen={isOpen} title="Find my reading mode" onClose={onClose} data-testid="reading-mode-quiz">
      {error && (
        <p role="alert" className="text-sm text-red-400" data-testid="reading-mode-quiz-error">
          {error}
        </p>
      )}

      <p className="text-sm text-stone-400">
        Step {step + 1} of {questions.length}
      </p>

      {currentQuestion && (
        <fieldset className="space-y-3">
          <legend className="text-lg font-bold text-stone-200">{currentQuestion.prompt}</legend>
          {currentQuestion.answers.map((answer) => {
            const checked = answers[currentQuestion.id] === answer.id
            return (
              <button
                key={answer.id}
                type="button"
                role="radio"
                aria-checked={checked}
                data-testid={`quiz-answer-${currentQuestion.id}-${answer.id}`}
                onClick={() => selectAnswer(answer.id)}
                className={`w-full text-left rounded-lg border px-4 py-3 text-stone-200 transition-colors ${
                  checked
                    ? 'border-amber-400 bg-amber-400/10'
                    : 'border-stone-700 hover:border-stone-500'
                }`}
              >
                {answer.label}
              </button>
            )
          })}
        </fieldset>
      )}

      <div className="flex items-center justify-between gap-2 pt-2">
        <button
          type="button"
          onClick={handleBack}
          data-testid="reading-mode-quiz-back"
          className="rounded-lg border border-stone-700 px-4 py-2 text-stone-300 hover:border-stone-500"
        >
          {step === 0 ? 'Cancel' : 'Back'}
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={!canAdvance}
          data-testid="reading-mode-quiz-next"
          className="rounded-lg bg-amber-500 px-4 py-2 font-bold text-stone-900 disabled:opacity-40"
        >
          {isLastStep ? 'Set my mode' : 'Next'}
        </button>
      </div>
    </Modal>
  )
}
