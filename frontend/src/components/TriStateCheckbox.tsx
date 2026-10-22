import { useEffect, useRef } from 'react'

interface TriStateCheckboxProps {
  /** True when every controlled item is selected. */
  checked: boolean
  /** True when only some controlled items are selected. */
  indeterminate: boolean
  /** Accessible name for the control. */
  label: string
  /** Disabled state, for example while a commit is in flight. */
  disabled?: boolean
  /** Called with the reader's next selection. */
  onChange: (checked: boolean) => void
}

/**
 * Native checkbox with the browser's mixed (indeterminate) state.
 *
 * The mixed state is an IDL property React cannot render directly, so the
 * input keeps its own `indeterminate` flag in sync with the prop. Clicking a
 * mixed checkbox selects everything, which is what a reader expects from a
 * partially selected group.
 *
 * @param props - Checkbox state and change handler.
 * @returns The tri-state checkbox.
 */
export default function TriStateCheckbox({
  checked,
  indeterminate,
  label,
  disabled = false,
  onChange,
}: TriStateCheckboxProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = indeterminate
    }
  }, [indeterminate])

  return (
    <input
      ref={inputRef}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      aria-label={label}
      onChange={(event) => onChange(event.target.checked)}
    />
  )
}
