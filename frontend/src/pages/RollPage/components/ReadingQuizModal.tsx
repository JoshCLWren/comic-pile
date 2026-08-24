import { useEffect, useState } from 'react'
import Modal from '../../../components/Modal'
import {
  BANDWIDTH_BY_ANSWER_ID,
  INTENT_BY_ANSWER_ID,
  QUIZ_QUESTIONS,
  formatReadingModeLabel,
  resolveReadingMode,
} from '../../../services/readingQuiz'
import type { ReadingMode } from '../../../types/readingMode'

interface ReadingQuizModalProps {
  isOpen: boolean
  onClose: () => void
  /** Stable bandwidth answer ID preselected from the session's current mode, or null. */
  initialBandwidthAnswerId: string | null
  /** Stable intent answer ID preselected from the session's current mode, or null. */
  initialIntentAnswerId: string | null
  onSubmit: (mode: ReadingMode) => Promise<void>
}

const BANDWIDTH_QUESTION = QUIZ_QUESTIONS[0]
const INTENT_QUESTION = QUIZ_QUESTIONS[1]

/**
 * Two-question reading-mode quiz rendered as a bottom-sheet/modal.
 *
 * The flow is exactly two decisions: choosing the second answer submits the
 * resolved mode with source `quiz`. Cancel, backdrop, and Escape all close
 * without submitting so the quiz never changes or blocks normal rolling.
 */
export default function ReadingQuizModal({
  isOpen,
  onClose,
  initialBandwidthAnswerId,
  initialIntentAnswerId,
  onSubmit,
}: ReadingQuizModalProps) {
  const [selectedBandwidthId, setSelectedBandwidthId] = useState<string | null>(null)
  const [selectedIntentId, setSelectedIntentId] = useState<string | null>(null)
  const [activeQuestionIndex, setActiveQuestionIndex] = useState(0)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')

  // Reset the two-decision flow every time the quiz opens, seeded with the
  // answers that produced the session's current mode when those IDs still exist.
  useEffect(() => {
    if (!isOpen) return
    setSelectedBandwidthId(initialBandwidthAnswerId)
    setSelectedIntentId(initialIntentAnswerId)
    setActiveQuestionIndex(initialBandwidthAnswerId ? 1 : 0)
    setIsSubmitting(false)
    setError('')
  }, [isOpen, initialBandwidthAnswerId, initialIntentAnswerId])

  const submitQuiz = async (bandwidthAnswerId: string, intentAnswerId: string) => {
    let mode: ReadingMode
    try {
      mode = resolveReadingMode(bandwidthAnswerId, intentAnswerId)
    } catch {
      setError('That combination is no longer valid. Please pick again.')
      return
    }
    setIsSubmitting(true)
    setError('')
    try {
      await onSubmit(mode)
      onClose()
    } catch (err) {
      console.error('Reading quiz submission failed:', err)
      setError('Failed to save your reading mode. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleAnswerSelect = (questionIndex: number, answerId: string) => {
    if (isSubmitting) return
    setError('')
    if (questionIndex === 0) {
      setSelectedBandwidthId(answerId)
      setActiveQuestionIndex(1)
      return
    }
    const bandwidthAnswerId = selectedBandwidthId ?? ''
    setSelectedIntentId(answerId)
    void submitQuiz(bandwidthAnswerId, answerId)
  }

  if (!BANDWIDTH_QUESTION || !INTENT_QUESTION) return null

  const question = activeQuestionIndex === 0 ? BANDWIDTH_QUESTION : INTENT_QUESTION
  const currentSelection =
    activeQuestionIndex === 0 ? selectedBandwidthId : selectedIntentId

  // After both questions are answered the resolved pair previews before submit.
  const bandwidthValue =
    activeQuestionIndex === 1 && selectedBandwidthId
      ? BANDWIDTH_BY_ANSWER_ID[selectedBandwidthId]
      : undefined
  const intentValue =
    activeQuestionIndex === 1 && selectedIntentId
      ? INTENT_BY_ANSWER_ID[selectedIntentId]
      : undefined
  const previewLabel =
    bandwidthValue && intentValue ? formatReadingModeLabel(bandwidthValue, intentValue) : null

  return (
    <Modal isOpen={isOpen} title="Reading mode" onClose={onClose} data-testid="reading-quiz-modal">
      <div className="space-y-4">
        <p className="text-xs text-stone-400">
          Two quick questions tune this session&apos;s rolls. You can skip this at any time.
        </p>

        <fieldset className="space-y-2" aria-label={question.prompt}>
          <legend className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
            {`Question ${activeQuestionIndex + 1} of ${QUIZ_QUESTIONS.length}`}
          </legend>
          <p className="text-sm font-black text-stone-300">{question.prompt}</p>
          <div className="grid gap-2">
            {question.answers.map((answer) => (
              <button
                key={answer.id}
                type="button"
                data-testid={`quiz-answer-${answer.id}`}
                aria-pressed={currentSelection === answer.id}
                disabled={isSubmitting}
                onClick={() => handleAnswerSelect(activeQuestionIndex, answer.id)}
                className={`min-h-11 w-full px-4 py-3 rounded-xl border text-left text-sm font-black transition-colors disabled:opacity-60 ${
                  currentSelection === answer.id
                    ? 'bg-amber-600/20 border-amber-600 text-amber-500'
                    : 'bg-white/5 border-white/10 text-stone-300 hover:bg-white/10'
                }`}
              >
                {answer.label}
              </button>
            ))}
          </div>
        </fieldset>

        {previewLabel && (
          <p className="text-[10px] font-bold uppercase tracking-widest text-amber-500" role="status">
            {previewLabel}
          </p>
        )}
        {error && (
          <p className="text-xs text-red-400" role="alert">
            {error}
          </p>
        )}

        <div className="flex gap-2 pt-2">
          {activeQuestionIndex === 1 ? (
            <button
              type="button"
              data-testid="quiz-back"
              onClick={() => setActiveQuestionIndex(0)}
              disabled={isSubmitting}
              className="flex-1 py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
            >
              Back
            </button>
          ) : null}
          <button
            type="button"
            data-testid="quiz-cancel"
            onClick={onClose}
            disabled={isSubmitting}
            className="flex-1 py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            Cancel
          </button>
        </div>
      </div>
    </Modal>
  )
}
