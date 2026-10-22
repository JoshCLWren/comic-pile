import { forwardRef, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import Modal from './Modal'
import type {
  ReadingGraphChoiceEffect,
  ReadingGraphOverlapChoiceId,
  ReadingGraphPreview,
} from '../services/api-reading-graph'
import { radioGroupNavigationTarget } from '../utils/radioGroupKeyboard'
import {
  describeOverlapEffect,
  effectiveOverlapChoice,
  readingGraphIssueLabels,
  readingGraphSeriesLabel,
  readingGraphSeriesStatus,
  type ReadingGraphChoices,
} from '../utils/readingGraphOverlaps'

interface ReadingGraphOverlapDialogProps {
  isOpen: boolean
  /** Server preview that names the conflicts and their prospective effects. */
  preview: ReadingGraphPreview
  /** Answers made during this preview session, keyed by overlap identity. */
  choices: ReadingGraphChoices
  /** Called when the reader answers the series conflict on screen. */
  onChoose: (overlapId: string, choice: ReadingGraphOverlapChoiceId) => void
  /** Close without changing the reader's answers. */
  onClose: () => void
  /** Every conflict has an answer; continue the adoption flow. */
  onDone: () => void
  /** The graph is being recomputed from the reader's answers. */
  busy?: boolean
}

interface OverlapChoiceButtonProps {
  effect: ReadingGraphChoiceEffect
  preview: ReadingGraphPreview
  checked: boolean
  onSelect: () => void
}

/** One answer card: its label, explanation, and prospective comic effects. */
const OverlapChoiceButton = forwardRef<HTMLButtonElement, OverlapChoiceButtonProps>(
  function OverlapChoiceButton({ effect, preview, checked, onSelect }, ref) {
  const described = describeOverlapEffect(preview, effect)
  return (
    <button
      ref={ref}
      type="button"
      role="radio"
      aria-checked={checked}
      tabIndex={0}
      onClick={onSelect}
      className={`w-full rounded-xl border px-3 py-3 text-left transition-colors ${
        checked
          ? 'border-[var(--theme-continuity-accent)] bg-[var(--theme-bg-panel)]'
          : 'border-[var(--theme-border)] hover:bg-white/5'
      }`}
    >
        <span className="block text-sm font-black text-[var(--theme-text-primary)]">
          {effect.label}
        </span>
        <span className="mt-1 block text-xs text-[var(--theme-text-muted)]">
          {effect.detail}
        </span>
        {described.rollable.length > 0 && (
          <span className="mt-2 block text-xs text-[var(--theme-success)]">
            Keeps rolling: {described.rollable.join(', ')}
          </span>
        )}
        {described.waiting.length > 0 && (
          <span className="mt-1 block text-xs text-[var(--theme-warning)]">
            Still waits: {described.waiting.join(', ')}
          </span>
        )}
        {effect.series.length > 0 && (
          <span className="mt-2 block text-xs text-[var(--theme-text-dim)]">
            Graph:{' '}
            {effect.series
              .map(
                (node) =>
                  `${readingGraphSeriesLabel(node)} ${readingGraphSeriesStatus(node).toLowerCase()}`,
              )
              .join(' · ')}
          </span>
        )}
      </button>
    )
  },
)

/**
 * Ask the reader how one genuine series overlap should continue.
 *
 * The dialog walks the server's conflicts one volume pair at a time — never one
 * question per issue and never a single "which whole CBL wins" control. Each
 * answer shows the prospective "keeps rolling" / "still waits" comics and the
 * resulting series graph before it is applied, and the same answer is restored
 * the next time the source is opened.
 *
 * @param props - Conflicts, current answers, and finish/close handlers.
 * @returns The overlap questionnaire, or an empty modal when no conflict exists.
 */
export default function ReadingGraphOverlapDialog({
  isOpen,
  preview,
  choices,
  onChoose,
  onClose,
  onDone,
  busy = false,
}: ReadingGraphOverlapDialogProps) {
  const [step, setStep] = useState(0)
  const wasOpen = useRef(false)
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])

  // Reset the questionnaire position each time the dialog opens. The conflict
  // list itself stays the live server preview so each answer shows the effects
  // computed from the reader's previous answers.
  useEffect(() => {
    if (isOpen && !wasOpen.current) setStep(0)
    wasOpen.current = isOpen
  }, [isOpen])

  const overlaps = preview.overlaps
  const clampedStep = Math.min(step, Math.max(overlaps.length - 1, 0))
  const overlap = overlaps[clampedStep]
  const isLastStep = clampedStep >= overlaps.length - 1
  const selected = overlap ? effectiveOverlapChoice(overlap, choices) : null
  const blockedLabels = overlap
    ? readingGraphIssueLabels(preview, overlap.blocked_issue_ids)
    : []

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!overlap) return
    const focusedIndex = optionRefs.current.findIndex(
      (option) => option != null && option === document.activeElement,
    )
    const targetIndex = radioGroupNavigationTarget(
      event.key,
      focusedIndex,
      overlap.choices.length,
    )
    if (targetIndex === null) return
    event.preventDefault()
    const target = overlap.choices[targetIndex]
    optionRefs.current[targetIndex]?.focus()
    if (target && target.choice !== selected) {
      onChoose(overlap.overlap_id, target.choice)
    }
  }

  const goBack = () => {
    if (clampedStep === 0) {
      onClose()
      return
    }
    setStep((current) => Math.max(current - 1, 0))
  }

  const goForward = () => {
    if (selected === null) return
    if (isLastStep) {
      onDone()
      return
    }
    setStep((current) => current + 1)
  }

  return (
    <Modal
      isOpen={isOpen}
      title="Resolve overlapping series"
      onClose={onClose}
      data-testid="reading-graph-overlap-dialog"
      size="large"
    >
      <div className="space-y-4">
        <p className="text-xs font-bold text-[var(--theme-text-muted)]" role="status">
          {overlaps.length === 0
            ? 'No overlapping series need a decision.'
            : `Overlap ${clampedStep + 1} of ${overlaps.length}`}
        </p>

        {overlap && (
          <>
            <div>
              <h3
                id="reading-graph-overlap-question"
                className="text-base font-black text-[var(--theme-text-primary)]"
              >
                {overlap.question}
              </h3>
              {blockedLabels.length > 0 && (
                <p className="mt-2 text-xs text-[var(--theme-text-muted)]">
                  Waiting right now: {blockedLabels.join(', ')}
                </p>
              )}
            </div>

            <div
              className="space-y-2"
              role="radiogroup"
              aria-labelledby="reading-graph-overlap-question"
              onKeyDown={handleKeyDown}
            >
              {overlap.choices.map((effect, index) => (
                <OverlapChoiceButton
                  key={effect.choice}
                  ref={(element) => {
                    optionRefs.current[index] = element
                  }}
                  effect={effect}
                  preview={preview}
                  checked={selected === effect.choice}
                  onSelect={() => onChoose(overlap.overlap_id, effect.choice)}
                />
              ))}
            </div>

            {busy && (
              <p className="text-xs text-[var(--theme-text-muted)]">Updating the graph…</p>
            )}
          </>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--theme-border)] pt-3">
          <button
            type="button"
            onClick={goBack}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
          >
            {step === 0 ? 'Cancel' : 'Back'}
          </button>
          <button
            type="button"
            onClick={goForward}
            disabled={selected === null || busy}
            className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
          >
            {isLastStep ? 'Use these choices' : 'Next series'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
