import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { Issue, ThreadListItem } from '../../types'
import { isNumber } from '../../utils/runtimeChecks'
import OverlayPortal from '../OverlayPortal'

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

/**
 * Issue picker built as an explicit button + listbox rather than a native
 * `<select>`.
 *
 * #3308: the native select rendered every `<option>` as `disabled` in the
 * accessibility tree and silently refused mouse clicks, so the only working
 * path was the keyboard. Chromium derives the option's disabled state from the
 * owning control, so a select that is disabled for any reason reports its whole
 * option list as unselectable with no per-option explanation. Owning the trigger
 * and the list surface directly makes click, keyboard, and assistive
 * selection the same code path.
 *
 * The listbox renders through `OverlayPortal layer="menu"` (see
 * `frontend/AGENTS.md`) so a 100+ issue list is never clipped by an ancestor.
 * Closing is driven by selection, Escape, Tab, or an outside pointer press.
 * There is deliberately no `onBlur` close: on Chromium a mouse press on an
 * option shifts focus first, so a blur-based close unmounts the option before
 * its `click` can land, which is the silent-mouse-failure this replaces.
 */
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
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const triggerContainerRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])
  const listboxId = useId()

  const isUnavailable = disabled || isLoading || issues.length === 0
  const displayValue = value
    ? `#${value.issue_number}`
    : isLoading
      ? 'Loading issues…'
      : issues.length === 0
        ? emptyMessage
        : 'Select an issue'

  // The native select cleared the selection through its placeholder option, so
  // a chosen issue must stay clearable. The clear row only appears once there
  // is something to clear.
  const clearLabel = 'Select an issue'
  const entries: Array<{ key: string; issue: Issue | null }> = [
    ...(value ? [{ key: 'clear', issue: null }] : []),
    ...issues.map((issue) => ({ key: `issue-${issue.id}`, issue })),
  ]

  const closeListbox = useCallback((restoreFocus: boolean) => {
    setIsOpen(false)
    setPosition(null)
    if (restoreFocus) {
      triggerRef.current?.focus()
    }
  }, [])

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return

    const rect = trigger.getBoundingClientRect()
    const listRect = listRef.current?.getBoundingClientRect()
    const viewportWidth = document.documentElement.clientWidth
    const viewportPadding = 8
    const offset = 4
    const left = Math.min(
      Math.max(viewportPadding, rect.left),
      Math.max(viewportPadding, viewportWidth - rect.width - viewportPadding),
    )
    const listHeight = listRect?.height ?? 0
    const belowTop = rect.bottom + offset
    const top = belowTop + listHeight > window.innerHeight - viewportPadding
      ? Math.max(viewportPadding, rect.top - listHeight - offset)
      : belowTop

    setPosition((current) =>
      current && current.top === top && current.left === left ? current : { top, left },
    )
  }, [])

  useEffect(() => {
    if (!isOpen) return

    updatePosition()
    const frame = requestAnimationFrame(updatePosition)
    window.addEventListener('resize', updatePosition)
    document.addEventListener('scroll', updatePosition, true)

    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', updatePosition)
      document.removeEventListener('scroll', updatePosition, true)
    }
  }, [isOpen, updatePosition])

  // Close on an outside press rather than on blur. A pointer press inside the
  // list must not tear the option down before its click handler runs.
  useEffect(() => {
    if (!isOpen) return

    const handlePointerDownOutside = (event: MouseEvent) => {
      // SAFETY: mousedown targets are always DOM nodes, and Node.contains() requires a Node argument.
      const target = event.target as Node
      if (!listRef.current?.contains(target) && !triggerContainerRef.current?.contains(target)) {
        closeListbox(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDownOutside)
    return () => document.removeEventListener('mousedown', handlePointerDownOutside)
  }, [isOpen, closeListbox])

  // A new issue set or an externally cleared selection must not leave a stale
  // list open with options that no longer belong to the current series.
  useEffect(() => {
    setIsOpen(false)
    setPosition(null)
  }, [issues, value])

  const focusOptionAt = (index: number) => {
    const options = optionRefs.current.filter((option): option is HTMLButtonElement => option != null)
    if (options.length === 0) return
    const wrapped = (index + options.length) % options.length
    options[wrapped]?.focus()
  }

  const handleTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (isUnavailable) return

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setIsOpen(true)
      // Options mount with the list, so focus lands on the next frame.
      window.requestAnimationFrame(() =>
        focusOptionAt(event.key === 'ArrowDown' ? 0 : entries.length - 1),
      )
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      // The trigger's native click already toggles; do not open a second path.
      event.preventDefault()
      setIsOpen((open) => !open)
      return
    }
    if (event.key === 'Escape' && isOpen) {
      event.preventDefault()
      closeListbox(false)
    }
  }

  const handleOptionKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusOptionAt(index + 1)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      focusOptionAt(index - 1)
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      focusOptionAt(0)
      return
    }
    if (event.key === 'End') {
      event.preventDefault()
      focusOptionAt(entries.length - 1)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      closeListbox(true)
      return
    }
    if (event.key === 'Tab') {
      closeListbox(false)
    }
  }

  const selectIssue = (issue: Issue | null) => {
    onChange(issue)
    closeListbox(true)
  }

  return (
    <div className="space-y-1">
      <label className="block text-[10px] font-bold uppercase tracking-widest text-stone-500">
        {label}
        <div className="relative" ref={triggerContainerRef}>
          <button
            ref={triggerRef}
            type="button"
            role="combobox"
            aria-expanded={isOpen}
            aria-haspopup="listbox"
            aria-controls={isOpen ? listboxId : undefined}
            disabled={isUnavailable}
            onClick={() => (isOpen ? closeListbox(false) : setIsOpen(true))}
            onKeyDown={handleTriggerKeyDown}
            className="form-control mt-1 min-h-11 w-full rounded-xl px-3 py-2 text-left text-sm disabled:opacity-50"
          >
            <span className="block truncate">{displayValue}</span>
          </button>
        </div>
      </label>
      {isOpen && (
        <OverlayPortal layer="menu">
          <div
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-label={`${label} options`}
            className="surface-glass fixed max-h-60 w-56 overflow-auto p-1 shadow-xl"
            style={position ? { top: position.top, left: position.left } : { top: 0, left: 0, visibility: 'hidden' }}
          >
            {entries.map((entry, index) => (
              <button
                key={entry.key}
                ref={(element) => {
                  optionRefs.current[index] = element
                }}
                type="button"
                role="option"
                aria-selected={entry.issue ? value?.id === entry.issue.id : value === null}
                onClick={() => selectIssue(entry.issue)}
                onKeyDown={(event) => handleOptionKeyDown(event, index)}
                className={`w-full rounded-lg px-3 py-2 text-left text-sm focus:outline-none focus-visible:bg-white/10 ${
                  entry.issue && value?.id === entry.issue.id
                    ? 'bg-white/10 font-semibold text-[var(--theme-text-primary)]'
                    : 'text-[var(--theme-text-muted)] hover:bg-white/10 hover:text-[var(--theme-text-primary)]'
                }`}
              >
                {entry.issue ? `#${entry.issue.issue_number}` : clearLabel}
              </button>
            ))}
          </div>
        </OverlayPortal>
      )}
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
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
