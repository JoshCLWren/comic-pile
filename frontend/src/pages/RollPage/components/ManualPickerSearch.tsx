import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'

export interface ManualPickerSearchOption {
  id: number
  label: string
}

export interface ManualPickerSearchProps {
  activeOptions: ManualPickerSearchOption[]
  snoozedOptions?: ManualPickerSearchOption[]
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  pending?: boolean
  placeholder?: string
  noMatchText?: string
  clearLabel?: string
}

/**
 * Searchable, accessible manual series picker for the Roll "Pick manually"
 * modal. Replaces the previous native `<select>` so large libraries stay
 * usable: the reader types a partial title, any already-known disambiguating
 * identity text, or a Thread id (including the ids shown in "Series #N"
 * fallback labels) and the option list filters in place.
 *
 * Filtering never mutates, rolls, rates, or marks anything read; it only
 * narrows the visible choices. Selection still resolves to the exact Thread
 * id carried by each option.
 */
export function ManualPickerSearch({
  activeOptions,
  snoozedOptions = [],
  value,
  onChange,
  disabled = false,
  pending = false,
  placeholder = 'Search series…',
  noMatchText = 'No matching series',
  clearLabel = 'Clear search',
}: ManualPickerSearchProps) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const listboxId = useId()

  const allOptions = useMemo(() => {
    const rows: { option: ManualPickerSearchOption; group: 'active' | 'snoozed' }[] = []
    for (const option of activeOptions) rows.push({ option, group: 'active' })
    for (const option of snoozedOptions) rows.push({ option, group: 'snoozed' })
    return rows
  }, [activeOptions, snoozedOptions])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return allOptions
    return allOptions.filter(({ option }) => {
      // Search on both the full label AND the raw thread ID for identity-based filtering
      const labelMatch = option.label.toLowerCase().includes(needle)
      const identityMatch = String(option.id).includes(needle)
      return labelMatch || identityMatch
    })
  }, [allOptions, query])

  useEffect(() => {
    if (highlighted >= filtered.length) setHighlighted(filtered.length > 0 ? filtered.length - 1 : 0)
  }, [filtered.length, highlighted])

  useEffect(() => {
    if (!open || filtered.length === 0) return
    const activeOption = listRef.current?.children[highlighted]
    activeOption?.scrollIntoView?.({ block: 'nearest' })
  }, [filtered.length, highlighted, open])

  const selectedOption = allOptions.find(({ option }) => String(option.id) === value)?.option

  const commit = (id: number) => {
    onChange(String(id))
    setQuery('')
    setOpen(false)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (disabled || pending) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      if (filtered.length > 0) {
        setHighlighted((prev) => Math.min(prev + 1, filtered.length - 1))
      }
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
      if (filtered.length > 0) {
        setHighlighted((prev) => Math.max(prev - 1, 0))
      }
    } else if (event.key === 'Enter') {
      // While the picker owns the list, Enter must never bubble on to the
      // surrounding form. A failed search therefore cannot submit a stale
      // selection from before the reader started typing.
      if (open) {
        event.preventDefault()
        const choice = filtered[highlighted]
        if (choice) commit(choice.option.id)
      }
    } else if (event.key === 'Escape') {
      // The shared Modal owns Escape for the topmost dialog
      // (docs/FRONTEND_VISUAL_GRAMMAR.md). Collapse the popup here, but do
      // not prevent or stop the event: one Escape must still close
      // "Pick manually" instead of requiring a second or third press.
      if (open) setOpen(false)
    }
  }

  const handleClear = () => {
    setQuery('')
    setOpen(false)
    inputRef.current?.focus()
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={
            open && filtered[highlighted]
              ? `${listboxId}-option-${filtered[highlighted].option.id}`
              : undefined
          }
          aria-label="Series"
          value={query}
          placeholder={placeholder}
          disabled={disabled || pending}
          onChange={(event) => {
            const nextQuery = event.target.value
            setQuery(nextQuery)
            setOpen(true)
            setHighlighted(0)
            // Editing the search invalidates the previous commit: the
            // "Selected: …" line is hidden while a query is active, so keeping
            // the saved id would leave "Pick this series" enabled and able to
            // submit a series the reader is no longer looking at. The reader
            // must choose from the current results.
            if (value) onChange('')
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          className="w-full rounded-xl px-3 py-2 text-sm form-control"
        />
        {query && (
          <button
            type="button"
            onClick={handleClear}
            aria-label={clearLabel}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--theme-text-dim)] hover:text-[var(--theme-text-primary)]"
          >
            ×
          </button>
        )}
      </div>

      {selectedOption && !query && (
        <p className="text-xs text-[var(--theme-text-muted)]" data-testid="manual-picker-selection">
          Selected: {selectedOption.label}
        </p>
      )}

      {open && (
        // Single-select listbox: expose exactly one selected option, the one
        // referenced by aria-activedescendant. Mirroring the committed `value`
        // here as well would advertise two selections at once, so the saved
        // choice is reported by the "Selected: …" line above instead.
        //
        // This listbox stays in normal document flow inside the surrounding
        // Modal instead of being portaled through `OverlayPortal`. It is the
        // inline popup of a combobox form control, not a floating menu: it
        // scrolls with the dialog body and never escapes it. A portal would
        // also paint it underneath the open dialog: the shared layer tokens in
        // `components/overlay.css` stack menus (`--overlay-layer-menu: 200`)
        // below dialogs (`--overlay-layer-dialog: 300`), and the Modal already
        // lives in the dialog root.
        <ul
          ref={listRef}
          id={listboxId}
          role="listbox"
          aria-label="Series options"
          className="max-h-60 overflow-auto rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)]"
        >
          {filtered.length === 0 ? (
            <li
              role="option"
              aria-disabled="true"
              className="px-3 py-2 text-sm text-[var(--theme-text-dim)]"
            >
              {noMatchText}
            </li>
          ) : (
            filtered.map(({ option, group }, index) => (
              <li
                key={option.id}
                id={`${listboxId}-option-${option.id}`}
                role="option"
                aria-selected={index === highlighted}
                className={`cursor-pointer px-3 py-2 text-sm ${
                  index === highlighted
                    ? 'bg-[var(--theme-primary-action)]/15 text-[var(--theme-text-primary)]'
                    : 'text-[var(--theme-text-muted)]'
                }`}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => commit(option.id)}
              >
                <span className="block font-bold">{option.label}</span>
                {group === 'snoozed' && (
                  <span className="block text-[10px] uppercase tracking-wider text-[var(--theme-text-dim)]">Snoozed</span>
                )}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}

export default ManualPickerSearch