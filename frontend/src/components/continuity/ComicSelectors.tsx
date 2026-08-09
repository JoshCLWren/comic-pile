import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { Issue, Thread } from '../../types'

export interface SelectedComic {
  thread: Thread
  issue: Issue | null
}

export interface SelectedIssueRange {
  thread: Thread
  startIssue: Issue
  endIssue: Issue
}

interface SelectorStateProps {
  isLoading?: boolean
  error?: string | null
  disabled?: boolean
}

interface ContinuityThreadSelectorProps extends SelectorStateProps {
  threads: Thread[]
  value: Thread | null
  onChange: (thread: Thread | null) => void
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

  const results = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    return threads
      .filter((thread) => thread.id !== excludeThreadId)
      .filter((thread) => {
        if (!normalized) return true
        return `${thread.title} ${thread.format}`.toLocaleLowerCase().includes(normalized)
      })
      .slice(0, 50)
  }, [excludeThreadId, query, threads])

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && results.length > 0) {
      event.preventDefault()
      resultRefs.current[0]?.focus()
    }
  }

  function selectThread(thread: Thread) {
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
          className="mt-1 w-full rounded-xl border border-solid border-white/20 bg-white/5 px-3 py-2 text-sm text-stone-300 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-500/30 disabled:opacity-50"
        />
      </label>

      {isLoading && <p className="text-xs text-stone-500">Loading comics…</p>}
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      {!isLoading && !error && !disabled && results.length === 0 && (
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
              <span className="block text-xs text-stone-500">{thread.format}</span>
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
  return (
    <div className="space-y-1">
      <label className="block text-[10px] font-bold uppercase tracking-widest text-stone-500">
        {label}
        <select
          value={value?.id ?? ''}
          onChange={(event) => {
            const next = issues.find((issue) => issue.id === Number(event.target.value)) ?? null
            onChange(next)
          }}
          disabled={disabled || isLoading || issues.length === 0}
          className="mt-1 w-full rounded-xl border border-solid border-white/20 bg-white/5 px-3 py-2 text-sm text-stone-300 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-500/30 disabled:opacity-50"
        >
          <option value="">{isLoading ? 'Loading issues…' : issues.length === 0 ? emptyMessage : 'Select an issue'}</option>
          {issues.map((issue) => (
            <option key={issue.id} value={issue.id}>#{issue.issue_number}</option>
          ))}
        </select>
      </label>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    </div>
  )
}

interface ContinuityIssueRangeSelectorProps extends SelectorStateProps {
  thread: Thread
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
          #{draftStart?.issue_number} comes after #{draftEnd?.issue_number} in {thread.title}. Choose a later ending issue.
        </p>
      )}
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    </fieldset>
  )
}
