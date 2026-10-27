import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'

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
 * usable: the reader types a partial title (or any already-known
 * disambiguating identity text) and the option list filters in place.
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
  const listboxId = useRef(`manual-picker-listbox-${Math.random().toString(36).slice(2)}`).current

  const allOptions = useMemo(() => {
    const rows: { option: ManualPickerSearchOption; group: 'active' | 'snoozed' }[] = []
    for (const option of activeOptions) rows.push({ option, group: 'active' })
    for (const option of snoozedOptions) rows.push({ option, group: 'snoozed' })
    return rows
  }, [activeOptions, snoozedOptions])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return allOptions
    return allOptions.filter(({ option }) => option.label.toLowerCase().includes(needle))
  }, [allOptions, query])

  useEffect(() => {
    if (highlighted >= filtered.length) setHighlighted(filtered.length > 0 ? filtered.length - 1 : 0)
  }, [filtered.length, highlighted])

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
      setHighlighted((prev) => Math.min(prev + 1, Math.max(filtered.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
      setHighlighted((prev) => Math.max(prev - 1, 0))
    } else if (event.key === 'Enter') {
      if (open && filtered[highlighted]) {
        event.preventDefault()
        commit(filtered[highlighted].option.id)
      }
    } else if (event.key === 'Escape') {
      if (open) {
        event.preventDefault()
        setOpen(false)
      } else if (query) {
        event.preventDefault()
        setQuery('')
      }
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
            setQuery(event.target.value)
            setOpen(true)
            setHighlighted(0)
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
            className="absolute right-2 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-200"
          >
            ×
          </button>
        )}
      </div>

      {selectedOption && !query && (
        <p className="text-xs text-stone-300" data-testid="manual-picker-selection">
          Selected: {selectedOption.label}
        </p>
      )}

      {open && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label="Series options"
          className="max-h-60 overflow-auto rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)]"
        >
          {filtered.length === 0 ? (
            <li role="option" aria-disabled="true" className="px-3 py-2 text-sm text-stone-500">
              {noMatchText}
            </li>
          ) : (
            filtered.map(({ option, group }, index) => (
              <li
                key={option.id}
                id={`${listboxId}-option-${option.id}`}
                role="option"
                aria-selected={String(option.id) === value}
                className={`cursor-pointer px-3 py-2 text-sm ${
                  index === highlighted ? 'bg-white/10 text-stone-100' : 'text-stone-300'
                }`}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => commit(option.id)}
              >
                <span className="block font-bold">{option.label}</span>
                {group === 'snoozed' && (
                  <span className="block text-[10px] uppercase tracking-wider text-stone-500">Snoozed</span>
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