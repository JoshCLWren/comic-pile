import {
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
  // SAFETY: React's KeyboardEvent is a DOM event type, not the global DOM one
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import Modal from './Modal'
import { readingModeLabel, type ReadingBandwidth, type ReadingIntent, type SessionModeState } from '../types/rollBootstrap'
import type { SessionModeUpdateRequest } from '../types'
import { radioGroupNavigationTarget } from '../utils/radioGroupKeyboard'

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

interface OptionButtonProps {
  label: string
  isSelected: boolean
  onClick: () => void
  disabled: boolean
  description?: string
}

const OptionButton = forwardRef<HTMLButtonElement, OptionButtonProps>(function OptionButton(
  { label, isSelected, onClick, disabled, description },
  ref,
) {
  return (
    <button
      ref={ref}
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
})

interface RadioOptionGroupProps<T extends string> {
  label: string
  options: readonly T[]
  selected: T
  disabled: boolean
  onSelect: (value: T) => void
  descriptions?: Partial<Record<T, string>>
}

/**
 * Custom radio group with the native keyboard contract.
 *
 * Arrow keys move focus to the next/previous option and select it, Home/End
 * jump to the first/last option, and selection wraps at both ends. Because a
 * selection in this sheet is the commit action (the same as clicking an
 * option), arrow-activated options submit through the caller's `onSelect`.
 */
function RadioOptionGroup<T extends string>({
  label,
  options,
  selected,
  disabled,
  onSelect,
  descriptions,
}: RadioOptionGroupProps<T>) {
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const focusedIndex = optionRefs.current.findIndex(
      (option) => option != null && option === document.activeElement,
    )
    const targetIndex = radioGroupNavigationTarget(event.key, focusedIndex, options.length)
    if (targetIndex === null) return

    event.preventDefault()
    const targetOption = options[targetIndex]
    optionRefs.current[targetIndex]?.focus()
    if (targetOption === selected) return
    onSelect(targetOption)
  }

  return (
    <div className="space-y-2" role="radiogroup" aria-label={label} onKeyDown={handleKeyDown}>
      {options.map((option, index) => (
        <OptionButton
          key={option}
          ref={(element) => {
            optionRefs.current[index] = element
          }}
          label={readingModeLabel(option)}
          isSelected={selected === option}
          disabled={disabled}
          description={descriptions?.[option]}
          onClick={() => onSelect(option)}
        />
      ))}
    </div>
  )
}

/**
 * Reading-mode selector sheet: two independent radio groups for bandwidth and
 * intent. Submits through the canonical session-mode API and refreshes
 * bootstrap state on success. Each dimension is changed independently.
 *
 * The groups follow the native radiogroup keyboard contract (issue #3682): Tab
 * enters a group, arrow keys move and select within it, Home/End jump to the
 * group edges, and arrow movement wraps. Selecting commits immediately, the
 * same as clicking an option, so Escape remains the way to leave without
 * committing.
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
  const errorRef = useRef<HTMLParagraphElement>(null)

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

  // Disabling the focused option during submit drops focus to <body>, which
  // would leave the modal without a focused control. Failed submissions keep
  // the sheet open, so hand focus to the error message instead.
  useEffect(() => {
    if (!submitError) return
    errorRef.current?.focus()
  }, [submitError])

  const handleOpenQuiz = useCallback(() => {
    if (!onOpenQuiz) return
    onClose()
    onOpenQuiz()
  }, [onClose, onOpenQuiz])

  if (!isOpen) return null

  return (
    <Modal isOpen title="Reading mode" onClose={onClose} data-testid="mode-selector-sheet">
      {submitError && (
        <p
          ref={errorRef}
          role="alert"
          tabIndex={-1}
          className="text-sm text-[var(--theme-danger)]"
          data-testid="mode-selector-error"
        >
          {submitError}
        </p>
      )}

      <fieldset disabled={submitting}>
        <legend className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-muted)] mb-2">
          Bandwidth — how demanding do you want comics to feel?
        </legend>
        <RadioOptionGroup
          label="Bandwidth"
          options={BANDWIDTH_OPTIONS}
          selected={currentBandwidth}
          disabled={submitting}
          onSelect={(bandwidth) => handleSubmit({ bandwidth, intent: currentIntent })}
        />
      </fieldset>

      <fieldset disabled={submitting} className="mt-4">
        <legend className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-muted)] mb-2">
          Intent — what kind of pick sounds good?
        </legend>
        <RadioOptionGroup
          label="Intent"
          options={INTENT_OPTIONS}
          selected={currentIntent}
          disabled={submitting}
          descriptions={INTENT_DESCRIPTIONS}
          onSelect={(intent) => handleSubmit({ bandwidth: currentBandwidth, intent })}
        />
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
