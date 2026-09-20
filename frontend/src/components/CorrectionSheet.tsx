import { useCallback, useState } from 'react'
import Modal from './Modal'
import type { SessionModeUpdateRequest } from '../types'

export type CorrectionChoiceId =
  | 'even_easier'
  | 'keep_level_different'
  | 'something_familiar'
  | 'something_different'
  | 'pure_random'

/** Example display title per choice. Absent key = descriptive copy only. */
export type CorrectionExamples = Partial<Record<CorrectionChoiceId, string>>

interface CorrectionSheetProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (choice: CorrectionChoiceId, patch: SessionModeUpdateRequest) => Promise<void>
  /** Opens the two-question reading-mode quiz; closes the sheet first. */
  onOpenQuiz?: () => void
  /** Whether the reading-mode quiz is surfaced in this build (issue #1945 gate). */
  quizEnabled?: boolean
  /**
   * Personalized example titles drawn from the signed-in user's own
   * rated/read history. Explanatory only: selection still uses the canonical
   * patch below. Missing keys render descriptive copy with no invented
   * example. A `pure_random` entry is ignored because that choice explicitly
   * ignores steering preferences.
   */
  examples?: CorrectionExamples
}

interface CorrectionChoice {
  id: CorrectionChoiceId
  label: string
  description: string
  /** `{example}` slot filled from `examples`; null renders no example line. */
  exampleTemplate: string | null
  patch: SessionModeUpdateRequest
}

const CHOICES: CorrectionChoice[] = [
  {
    id: 'even_easier',
    label: 'Give me something lighter',
    description: 'Favor a lower-commitment, easier read for the next roll.',
    exampleTemplate: 'Think more like {example}, a lighter read.',
    patch: { bandwidth: 'light' },
  },
  {
    id: 'keep_level_different',
    label: 'Keep about the same effort',
    description: 'Keep the same reading commitment, but pick a different comic.',
    exampleTemplate: 'Think another read at the same commitment, like {example}.',
    patch: { intent: 'balanced' },
  },
  {
    id: 'something_familiar',
    label: 'Stay close to what I’ve liked',
    description: 'Favor something similar to comics you’ve rated well.',
    exampleTemplate: 'Based on your ratings, think more {example} territory.',
    patch: { intent: 'familiar' },
  },
  {
    id: 'something_different',
    label: 'Give me a change of pace',
    description: 'Favor something meaningfully different from your recent favorites.',
    exampleTemplate: 'Think less familiar territory, more like {example}.',
    patch: { intent: 'explore' },
  },
  {
    id: 'pure_random',
    label: 'Surprise me',
    description: 'Don’t steer by your past ratings or reading effort for this reroll.',
    exampleTemplate: null,
    patch: { intent: 'random' },
  },
]

/**
 * Correction sheet surfaced after meaningful Snooze prediction failures.
 *
 * Triggered only when the backend signals `suggest_clarification` (repeated or
 * contradictory snoozes). Each choice maps to a predictable bandwidth/intent
 * patch submitted through the canonical session-mode API. Dismissing the sheet
 * leaves the current backend mode intact — no API call fires on dismiss.
 *
 * Copy answers one user question ("What should change about the next roll?")
 * in plain language with no recommendation-model vocabulary. Optional
 * per-choice examples come from the caller's already-loaded rated/read
 * history via the `examples` prop; the sheet itself issues no network
 * requests, so there is no per-option request pattern.
 *
 * Because this surface only appears when a one-tap correction may be
 * insufficient, it also offers the two-question quiz as a non-forced
 * alternative (issue #1739): choosing it closes the sheet and opens the quiz,
 * and dismissing the sheet never blocks later manual access.
 */
export default function CorrectionSheet({
  isOpen,
  onClose,
  onSubmit,
  onOpenQuiz,
  quizEnabled = false,
  examples,
}: CorrectionSheetProps) {
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const handleChoice = useCallback(
    async (choice: CorrectionChoice) => {
      setSubmitting(true)
      setSubmitError(null)
      try {
        await onSubmit(choice.id, choice.patch)
        onClose()
      } catch (_err) {
        setSubmitError('Failed to update reading mode. Please try again.')
      } finally {
        setSubmitting(false)
      }
    },
    [onSubmit, onClose],
  )

  const handleOpenQuiz = useCallback(() => {
    if (!onOpenQuiz) return
    onClose()
    onOpenQuiz()
  }, [onClose, onOpenQuiz])

  if (!isOpen) return null

  return (
    <Modal isOpen title="Not feeling it?" onClose={onClose} data-testid="correction-sheet">
      <p className="mb-3 text-sm text-[var(--theme-text-muted)]">
        What should change about the next roll?
      </p>
      {submitError && (
        <p role="alert" className="text-sm text-[var(--theme-danger)]" data-testid="correction-sheet-error">
          {submitError}
        </p>
      )}

      <fieldset className="space-y-3">
        <legend className="sr-only">Pick what should change about the next roll</legend>
        {CHOICES.map((choice) => {
          // Surprise-me never shows an example: it explicitly ignores
          // steering preferences, so any example would imply a false signal.
          const example =
            choice.id === 'pure_random' ? undefined : examples?.[choice.id]?.trim() || undefined
          return (
            <button
              key={choice.id}
              type="button"
              data-testid={`correction-choice-${choice.id}`}
              disabled={submitting}
              onClick={() => handleChoice(choice)}
              className="w-full text-left rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-3 text-[var(--theme-text-primary)] text-sm transition-colors hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
            >
              <span className="font-black">{choice.label}</span>
              <span className="block mt-0.5 font-normal">{choice.description}</span>
              {choice.exampleTemplate && example && (
                <span
                  className="block mt-0.5 text-xs font-normal text-[var(--theme-text-muted)]"
                  data-testid={`correction-example-${choice.id}`}
                >
                  {choice.exampleTemplate.replace('{example}', example)}
                </span>
              )}
            </button>
          )
        })}
      </fieldset>

      <div className="mt-4 pt-3 border-t border-[var(--theme-border)]">
        <button
          type="button"
          data-testid="correction-sheet-dismiss"
          disabled={submitting}
          onClick={onClose}
          className="w-full py-2 text-left text-sm font-bold uppercase tracking-wider text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] disabled:opacity-50"
        >
          Dismiss
        </button>
        {quizEnabled && (
          <button
            type="button"
            data-testid="correction-sheet-open-quiz"
            disabled={submitting}
            onClick={handleOpenQuiz}
            className="w-full py-2 text-left text-sm font-bold uppercase tracking-wider text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-comic-accent)] disabled:opacity-50"
          >
            Not sure? Take the two-question quiz
          </button>
        )}
      </div>
    </Modal>
  )
}
