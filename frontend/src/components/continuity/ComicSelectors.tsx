import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, FocusEvent } from 'react'
import type { Issue, ThreadListItem } from '../../types'
import { isNumber } from '../../utils/runtimeChecks'

export interface SelectedComic {
  thread: ThreadListItem
  issue: Issue | null
}

export interface SelectedIssueRange {
  thread: ThreadListItem
  startIssue: Issue
  endIssue: Issue
}

interface SelectorStateProps {
  isLoading?: boolean
  error?: string | null
  disabled?: boolean
}

interface ContinuityThreadSelectorProps extends SelectorStateProps {
  threads: ThreadListItem[]
  value: ThreadListItem | null
  onChange: (thread: ThreadListItem | null) => void
  label?: string
  excludeThreadId?: number | null
  placeholder?: string
}

export function ContinuityThreadSelector({
  threads,
  value,
  onChange,
  label = 'Comic series',
  excludeThreadId = null,
  placeholder = 'Search by title',
  isLoading = false,
  error = null,
  disabled = false,
}: ContinuityThreadSelectorProps) {
  const [query, setQuery] = useState(value?.title ?? '')
  const resultRefs = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    if (value) setQuery(value.title)
  }, [value])

  const isEmptyQuery = !query.trim()
  const results = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return []
    return threads
      .filter((thread) => thread.id !== excludeThreadId)
      .filter((thread) => `${thread.title} ${thread.format}`.toLocaleLowerCase().includes(normalized))
      .sort((a, b) => {
        const titleRank = a.title.localeCompare(b.title)
        if (titleRank !== 0) return titleRank
        const formatRank = a.format.localeCompare(b.format)
        if (formatRank !== 0) return formatRank
        return a.id - b.id
      })
      .slice(0, 50)
  }, [excludeThreadId, query, threads])

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && results.length > 0) {
      event.preventDefault()
      resultRefs.current[0]?.focus()
    }
  }

  function selectThread(thread: ThreadListItem) {
    onChange(thread)
    setQuery(thread.title)
  }

  return (
    <div className="space-y-2">
      <label className="block text-[10px] font-bold uppercase tracking-widest text-stone-500">
        {label}
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            if (value && event.target.value !== value.title) onChange(null)
          }}
          onKeyDown={handleSearchKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          aria-expanded={!disabled && results.length > 0}
          className="mt-1 w-full rounded-xl px-3 py-2 text-sm form-control disabled:opacity-50"
        />
      </label>

      {value && (
        <div
          data-testid="selected-thread-value"
          className="rounded-xl border border-solid border-white/10 bg-white/5 px-3 py-2"
        >
          <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
            Selected series
          </p>
          <p
            data-testid="selected-thread-title"
            className="mt-1 break-words text-sm font-semibold leading-snug text-stone-200"
          >
            {value.title}
          </p>
          {value.format ? <p className="mt-1 text-xs text-stone-500">{value.format}</p> : null}
        </div>
      )}

      {isLoading && <p className="text-xs text-stone-500">Loading comics…</p>}
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      {!isLoading && !error && !disabled && isEmptyQuery && (
        <p className="text-xs text-stone-500">Type to search comics</p>
      )}
      {!isLoading && !error && !disabled && !isEmptyQuery && results.length === 0 && (
        <p className="text-xs text-stone-500">No matching comics found.</p>
      )}
      {!isLoading && !error && !disabled && results.length > 0 && (
        <div role="listbox" aria-label={`${label} results`} className="max-h-48 overflow-auto rounded-xl border border-white/10 bg-white/5">
          {results.map((thread, index) => (
            <button
              key={thread.id}
              ref={(element) => { resultRefs.current[index] = element }}
              type="button"
              role="option"
              aria-selected={value?.id === thread.id}
              onClick={() => selectThread(thread)}
              className={`w-full border-b border-white/5 px-3 py-2 text-left text-sm last:border-b-0 hover:bg-white/10 ${
                value?.id === thread.id ? 'bg-white/10 text-white' : 'text-stone-300'
              }`}
            >
              <span className="block font-semibold">{thread.title}</span>
              <span className="block text-xs text-stone-500">
                {[
                  thread.format,
                  isNumber(thread.issues_remaining) ? `${thread.issues_remaining} remaining` : null,
                  isNumber(thread.total_issues) ? `${thread.total_issues} total` : null,
                ]
                  .filter(Boolean)
                  .join(' • ')}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

interface ContinuityIssueSelectorProps extends SelectorStateProps {
  issues: Issue[]
  value: Issue | null
  onChange: (issue: Issue | null) => void
  label?: string
  emptyMessage?: string
}

export function ContinuityIssueSelector({
  issues,
  value,
  onChange,
  label = 'Issue',
  emptyMessage = 'No issues available',
  isLoading = false,
  error = null,
  disabled = false,
}: ContinuityIssueSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    setHighlightedIndex(-1)
    setIsOpen(false)
  }, [value, disabled, isLoading, issues.length])

  function closeDropdown() {
    setIsOpen(false)
    setHighlightedIndex(-1)
  }

  function handleButtonKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled || isLoading || issues.length === 0) return

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setIsOpen(true)
      const nextIndex = event.key === 'ArrowDown' ? 0 : issues.length - 1
      setHighlightedIndex(nextIndex)
      optionRefs.current[nextIndex]?.focus()
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setIsOpen(!isOpen)
      if (!isOpen) setHighlightedIndex(0)
    } else if (event.key === 'Escape') {
      closeDropdown()
      buttonRef.current?.focus()
    }
  }

  function handleOptionKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      const nextIndex = index + 1 < issues.length ? index + 1 : 0
      setHighlightedIndex(nextIndex)
      optionRefs.current[nextIndex]?.focus()
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      const nextIndex = index - 1 >= 0 ? index - 1 : issues.length - 1
      setHighlightedIndex(nextIndex)
      optionRefs.current[nextIndex]?.focus()
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      const issue = issues[index]
      onChange(issue)
      closeDropdown()
      buttonRef.current?.focus()
    } else if (event.key === 'Escape') {
      closeDropdown()
      buttonRef.current?.focus()
    } else if (event.key === 'Home') {
      event.preventDefault()
      setHighlightedIndex(0)
      optionRefs.current[0]?.focus()
    } else if (event.key === 'End') {
      event.preventDefault()
      const lastIndex = issues.length - 1
      setHighlightedIndex(lastIndex)
      optionRefs.current[lastIndex]?.focus()
    }
  }

  function handleButtonBlur(event: FocusEvent<HTMLButtonElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      closeDropdown()
    }
  }

  function handleOptionBlur(event: FocusEvent<HTMLButtonElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      closeDropdown()
    }
  }

  const displayValue = value
    ? `#${value.issue_number}`
    : isLoading
      ? 'Loading issues…'
      : issues.length === 0
        ? emptyMessage
        : 'Select an issue'

  return (
    <div className="space-y-1 relative">
      <label className="block text-[10px] font-bold uppercase tracking-widest text-stone-500">
        {label}
        <div className="relative">
          <button
            ref={buttonRef}
            type="button"
            role="combobox"
            aria-expanded={isOpen && !disabled && !isLoading && issues.length > 0}
            aria-haspopup="listbox"
            aria-disabled={disabled || isLoading || issues.length === 0}
            onClick={() => {
              if (!disabled && !isLoading && issues.length > 0) setIsOpen(!isOpen)
            }}
            onKeyDown={handleButtonKeyDown}
            onBlur={handleButtonBlur}
            disabled={disabled || isLoading || issues.length === 0}
            className="mt-1 w-full rounded-xl px-3 py-2 text-sm form-control disabled:opacity-50 text-left"
            style={{ backgroundColor: 'var(--theme-bg-panel)', borderColor: 'var(--theme-border)', color: 'var(--theme-text-primary)' }}
          >
            <span className="block truncate">{displayValue}</span>
          </button>
          {isOpen && !disabled && !isLoading && issues.length > 0 && (
            <div
              role="listbox"
              aria-label={`${label} options`}
              className="absolute z-10 mt-1 w-full max-h-60 overflow-auto rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] shadow-lg"
            >
              {issues.map((issue, index) => (
                <button
                  key={issue.id}
                  ref={(element) => { optionRefs.current[index] = element }}
                  type="button"
                  role="option"
                  aria-selected={value?.id === issue.id}
                  onClick={() => {
                    onChange(issue)
                    closeDropdown()
                    buttonRef.current?.focus()
                  }}
                  onKeyDown={(event) => handleOptionKeyDown(event, index)}
                  onBlur={handleOptionBlur}
                  className={`w-full border-b border-[var(--theme-border)] px-3 py-2 text-left text-sm last:border-b-0 hover:bg-[var(--theme-bg-hover)] ${
                    value?.id === issue.id ? 'bg-[var(--theme-bg-hover)] text-[var(--theme-text-primary)]' : 'text-[var(--theme-text-primary)]'
                  } ${highlightedIndex === index ? 'bg-[var(--theme-bg-hover)] outline-none' : ''}`}
                >
                  <span className="block font-semibold">#{issue.issue_number}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </label>
      {isLoading && <p className="text-xs text-stone-500">Loading issues…</p>}
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      {!isLoading && !error && !disabled && issues.length === 0 && (
        <p className="text-xs text-stone-500">{emptyMessage}</p>
      )}
    </div>
  )
}

interface ContinuityIssueRangeSelectorProps extends SelectorStateProps {
  thread: ThreadListItem
  issues: Issue[]
  value: SelectedIssueRange | null
  onChange: (range: SelectedIssueRange | null) => void
  label?: string
}

export function ContinuityIssueRangeSelector({
  thread,
  issues,
  value,
  onChange,
  label = 'Issue range',
  isLoading = false,
  error = null,
  disabled = false,
}: ContinuityIssueRangeSelectorProps) {
  const [draftStart, setDraftStart] = useState<Issue | null>(value?.startIssue ?? null)
  const [draftEnd, setDraftEnd] = useState<Issue | null>(value?.endIssue ?? null)

  useEffect(() => {
    setDraftStart(value?.startIssue ?? null)
    setDraftEnd(value?.endIssue ?? null)
  }, [value])

  const startIndex = draftStart ? issues.findIndex((issue) => issue.id === draftStart.id) : -1
  const endIndex = draftEnd ? issues.findIndex((issue) => issue.id === draftEnd.id) : -1
  const isReversed = startIndex >= 0 && endIndex >= 0 && startIndex > endIndex

  function publishRange(nextStart: Issue | null, nextEnd: Issue | null) {
    if (!nextStart || !nextEnd) {
      onChange(null)
      return
    }

    const nextStartIndex = issues.findIndex((issue) => issue.id === nextStart.id)
    const nextEndIndex = issues.findIndex((issue) => issue.id === nextEnd.id)
    if (nextStartIndex < 0 || nextEndIndex < 0 || nextStartIndex > nextEndIndex) {
      onChange(null)
      return
    }

    onChange({ thread, startIssue: nextStart, endIssue: nextEnd })
  }

  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-[10px] font-bold uppercase tracking-widest text-stone-500">{label}</legend>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <ContinuityIssueSelector
          label="First issue"
          issues={issues}
          value={draftStart}
          onChange={(issue) => {
            setDraftStart(issue)
            publishRange(issue, draftEnd)
          }}
          isLoading={isLoading}
          disabled={disabled}
        />
        <ContinuityIssueSelector
          label="Last issue"
          issues={issues}
          value={draftEnd}
          onChange={(issue) => {
            setDraftEnd(issue)
            publishRange(draftStart, issue)
          }}
          isLoading={isLoading}
          disabled={disabled}
        />
      </div>
      {isReversed && (
        <p role="alert" className="text-xs text-amber-300">
          Choose a valid issue range in reading order.
        </p>
      )}
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    </fieldset>
  )
}
