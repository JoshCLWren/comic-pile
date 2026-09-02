import { useCallback, useEffect, useState } from 'react'
import Modal from './Modal'
import { sessionApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'

interface CorrectionSheetProps {
  isOpen: boolean
  onClose: () => void
  correction: {
    reason_code: string
    active_bandwidth: string | null
    active_confidence: number | null
    predicted_bandwidth: string | null
    bandwidth_changed: boolean
    suggest_clarification: boolean
  }
}

type CorrectionChoice =
  | 'even_easier'
  | 'keep_level_different'
  | 'something_familiar'
  | 'something_different'
  | 'pure_random'

const CHOICE_LABELS: Record<CorrectionChoice, string> = {
  even_easier: 'Even easier',
  keep_level_different: 'Keep this level, different comic',
  something_familiar: 'Something familiar',
  something_different: 'Something different',
  pure_random: 'Pure random',
}

const CHOICE_DESCRIPTIONS: Record<CorrectionChoice, string> = {
  even_easier: 'Shift toward lighter, quicker reads',
  keep_level_different: 'Same reading demand, pick another series',
  something_familiar: 'Prefer series you know and enjoy',
  something_different: 'Explore outside your usual picks',
  pure_random: 'Unweighted selection from your pool',
}

const CHOICE_TO_MODE: Record<CorrectionChoice, { bandwidth?: string; intent?: string }> = {
  even_easier: { bandwidth: 'light' },
  keep_level_different: {},
  something_familiar: { intent: 'familiar' },
  something_different: { intent: 'explore' },
  pure_random: { intent: 'random' },
}

export default function CorrectionSheet({
  isOpen,
  onClose,
  correction,
}: CorrectionSheetProps) {
  const [selectedChoice, setSelectedChoice] = useState<CorrectionChoice | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setSelectedChoice(null)
      setError(null)
      setSubmitting(false)
    }
  }, [isOpen])

  const handleSelect = useCallback(async (choice: CorrectionChoice) => {
    setSelectedChoice(choice)
    setError(null)
    setSubmitting(true)

    try {
      const modeUpdate = CHOICE_TO_MODE[choice]
      if (Object.keys(modeUpdate).length > 0) {
        await sessionApi.updateMode(modeUpdate)
      }
      onClose()
    } catch (err) {
      setError(getApiErrorDetail(err))
      setSubmitting(false)
    }
  }, [onClose])

  const handleDismiss = useCallback(() => {
    onClose()
  }, [onClose])

  return (
    <Modal
      isOpen={isOpen}
      title="Not the vibe?"
      onClose={handleDismiss}
      data-testid="correction-sheet"
      overlayClassName="bg-black/70 backdrop-blur-sm"
    >
      {isOpen && (() => {
        const reasonLabel = correction.reason_code === 'clarification_needed'
          ? 'Repeated snoozes suggest uncertainty'
          : 'Snooze shifted your reading mode'
        return (
        <>
      <section className="rounded-2xl border border-amber-800/30 bg-amber-950/15 p-4">
        <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-400">
          {reasonLabel}
        </h3>
        <p className="mt-2 text-sm text-stone-300">
          Your last snooze {correction.bandwidth_changed ? 'changed the active bandwidth' : 'lowered confidence in the current mode'}
          {correction.active_bandwidth ? ` (now ${correction.active_bandwidth})` : ''}.
        </p>
        {correction.predicted_bandwidth && correction.predicted_bandwidth !== correction.active_bandwidth && (
          <p className="mt-1 text-[11px] text-stone-500">
            Predicted: {correction.predicted_bandwidth}
          </p>
        )}
      </section>

      <fieldset className="space-y-2" disabled={submitting}>
        <legend className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
          What would you prefer?
        </legend>
        {(['even_easier', 'keep_level_different', 'something_familiar', 'something_different', 'pure_random'] as CorrectionChoice[]).map((choice) => (
          <button
            key={choice}
            type="button"
            onClick={() => handleSelect(choice)}
            className={`w-full text-left rounded-lg border px-4 py-3 text-stone-200 transition-colors ${
              selectedChoice === choice
                ? 'border-amber-400 bg-amber-400/10'
                : 'border-stone-700 hover:border-stone-500'
            }`}
            data-testid={`correction-choice-${choice}`}
          >
            <div className="font-medium">{CHOICE_LABELS[choice]}</div>
            <div className="text-[11px] text-stone-500 mt-0.5">{CHOICE_DESCRIPTIONS[choice]}</div>
          </button>
        ))}
      </fieldset>

      {error && (
        <p className="text-[11px] text-rose-300" role="alert" data-testid="correction-sheet-error">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={handleDismiss}
        className="w-full mt-4 rounded-xl border border-white/10 bg-white/5 py-3 text-xs font-black uppercase tracking-wider text-stone-300 transition hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-amber-500"
        disabled={submitting}
        data-testid="correction-sheet-dismiss"
      >
        {submitting ? 'Applying…' : 'Dismiss'}
      </button>
        </>
        )
      })()}
    </Modal>
  )
}

export type { CorrectionSheetProps }