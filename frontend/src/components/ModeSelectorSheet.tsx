import { useCallback, useState } from 'react'
import Modal from './Modal'
import { readingModeLabel, type ReadingBandwidth, type ReadingIntent, type SessionModeState } from '../types/rollBootstrap'
import type { SessionModeUpdateRequest } from '../types'

interface ModeSelectorSheetProps {
  isOpen: boolean
  currentMode: SessionModeState | null
  onClose: () => void
  onSubmit: (patch: SessionModeUpdateRequest) => Promise<void>
  /** Opens the two-question reading-mode quiz; closes the sheet first. */
  onOpenQuiz?: () => void
  /** Whether the reading-mode quiz is surfaced in this build (issue #1945 gate). */
  quizEnabled?: boolean
}

const BANDWIDTH_OPTIONS: ReadingBandwidth[] = ['light', 'balanced', 'deep']
const INTENT_OPTIONS: ReadingIntent[] = ['balanced', 'momentum', 'familiar', 'explore', 'random']

const INTENT_DESCRIPTIONS: Partial<Record<ReadingIntent, string>> = {
  random: 'Unweighted legacy-style selection within the current die pool',
}

function OptionButton({
  label,
  isSelected,
  onClick,
  disabled,
  description,
}: {
  label: string
  isSelected: boolean
  onClick: () => void
  disabled: boolean
  description?: string
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={isSelected}
      aria-label={description ? `${label}: ${description}` : label}
      disabled={disabled}
      onClick={onClick}
      className={`w-full text-left rounded-lg border px-4 py-3 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50 ${
        isSelected
          ? 'border-[var(--theme-comic-accent)] bg-[var(--theme-comic-accent)]/10 text-[var(--theme-comic-accent)]'
          : 'border-[var(--theme-border)] bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)] hover:bg-white/10'
      }`}
    >
      <span className="font-black">{label}</span>
      {description && (
        <span className="block mt-0.5 text-xs text-[var(--theme-text-muted)] font-normal">{description}</span>
      )}
    </button>
  )
}

/**
 * Reading-mode selector sheet: two independent radio groups for bandwidth and
 * intent. Submits through the canonical session-mode API and refreshes
 * bootstrap state on success. Each dimension is changed independently.
 *
 * The sheet is also the always-available manual entry point to the
 * two-question quiz ("Find my reading mode", issue #1739): both dimensions
 * already carry a concrete value, so the quiz stays optional and never
 * interrupts a confident session.
 */
export default function ModeSelectorSheet({
  isOpen,
  currentMode,
  onClose,
  onSubmit,
  onOpenQuiz,
  quizEnabled = false,
}: ModeSelectorSheetProps) {
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // SAFETY: currentMode.bandwidth is either a ReadingBandwidth value or undefined; the fallback normalizes it.
  const currentBandwidth = (currentMode?.bandwidth as ReadingBandwidth | null) ?? 'balanced'
  // SAFETY: currentMode.intent is either a ReadingIntent value or undefined; the fallback normalizes it.
  const currentIntent = (currentMode?.intent as ReadingIntent | null) ?? 'balanced'

  const handleSubmit = useCallback(
    async (patch: SessionModeUpdateRequest) => {
      setSubmitting(true)
      setSubmitError(null)
      try {
        await onSubmit(patch)
        onClose()
      } catch {
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
    <Modal isOpen title="Reading mode" onClose={onClose} data-testid="mode-selector-sheet">
      {submitError && (
        <p role="alert" className="text-sm text-[var(--theme-danger)]" data-testid="mode-selector-error">
          {submitError}
        </p>
      )}

      <fieldset disabled={submitting}>
        <legend className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-muted)] mb-2">
          Bandwidth — how demanding do you want comics to feel?
        </legend>
        <div className="space-y-2" role="radiogroup" aria-label="Bandwidth">
          {BANDWIDTH_OPTIONS.map((bw) => (
            <OptionButton
              key={bw}
              label={readingModeLabel(bw)}
              isSelected={currentBandwidth === bw}
              disabled={submitting}
              onClick={() => handleSubmit({ bandwidth: bw, intent: currentIntent })}
            />
          ))}
        </div>
      </fieldset>

      <fieldset disabled={submitting} className="mt-4">
        <legend className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-muted)] mb-2">
          Intent — what kind of pick sounds good?
        </legend>
        <div className="space-y-2" role="radiogroup" aria-label="Intent">
          {INTENT_OPTIONS.map((intent) => (
            <OptionButton
              key={intent}
              label={readingModeLabel(intent)}
              isSelected={currentIntent === intent}
              disabled={submitting}
              description={INTENT_DESCRIPTIONS[intent]}
              onClick={() => handleSubmit({ bandwidth: currentBandwidth, intent })}
            />
          ))}
        </div>
      </fieldset>

      {quizEnabled && (
        <div className="mt-4 pt-3 border-t border-[var(--theme-border)]">
          <button
            type="button"
            data-testid="mode-selector-open-quiz"
            disabled={submitting}
            onClick={handleOpenQuiz}
            className="w-full py-2 text-left text-sm font-bold uppercase tracking-wider text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-comic-accent)] disabled:opacity-50"
          >
            Find my reading mode
          </button>
        </div>
      )}
    </Modal>
  )
}
