import { useCallback, useState } from 'react'
import Modal from './Modal'
import type { SessionModeUpdateRequest } from '../types'

export type CorrectionChoiceId =
  | 'even_easier'
  | 'keep_level_different'
  | 'something_familiar'
  | 'something_different'
  | 'pure_random'

interface CorrectionSheetProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (choice: CorrectionChoiceId, patch: SessionModeUpdateRequest) => Promise<void>
}

interface CorrectionChoice {
  id: CorrectionChoiceId
  label: string
  patch: SessionModeUpdateRequest
}

const CHOICES: CorrectionChoice[] = [
  { id: 'even_easier', label: 'Even easier', patch: { bandwidth: 'light' } },
  { id: 'keep_level_different', label: 'Keep this level, different comic', patch: { intent: 'balanced' } },
  { id: 'something_familiar', label: 'Something familiar', patch: { intent: 'familiar' } },
  { id: 'something_different', label: 'Something different', patch: { intent: 'explore' } },
  { id: 'pure_random', label: 'Pure random', patch: { intent: 'random' } },
]

/**
 * Correction sheet surfaced after meaningful Snooze prediction failures.
 *
 * Triggered only when the backend signals `suggest_clarification` (repeated or
 * contradictory snoozes). Each choice maps to a predictable bandwidth/intent
 * patch submitted through the canonical session-mode API. Dismissing the sheet
 * leaves the current backend mode intact — no API call fires on dismiss.
 */
export default function CorrectionSheet({ isOpen, onClose, onSubmit }: CorrectionSheetProps) {
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

  if (!isOpen) return null

  return (
    <Modal isOpen title="Not the vibe?" onClose={onClose} data-testid="correction-sheet">
      {submitError && (
        <p role="alert" className="text-sm text-[var(--theme-danger)]" data-testid="correction-sheet-error">
          {submitError}
        </p>
      )}

      <fieldset className="space-y-3">
        <legend className="sr-only">Pick a reading-mode correction</legend>
        {CHOICES.map((choice) => (
          <button
            key={choice.id}
            type="button"
            data-testid={`correction-choice-${choice.id}`}
            disabled={submitting}
            onClick={() => handleChoice(choice)}
            className="w-full text-left rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-3 text-[var(--theme-text-primary)] text-sm transition-colors hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
          >
            {choice.label}
          </button>
        ))}
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
      </div>
    </Modal>
  )
}
