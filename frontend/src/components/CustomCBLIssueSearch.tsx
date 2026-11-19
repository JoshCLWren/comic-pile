import { FormEvent, KeyboardEvent, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  customCBLApi,
  type CustomCBLEntry,
  type CustomCBLIssueSearchResult,
} from '../services/api-custom-cbl'
import { queryKeys } from '../query/queryKeys'

interface CustomCBLIssueSearchProps {
  selectedId: number | null
  disabled: boolean
  isPending: boolean
  entries: CustomCBLEntry[]
  onAdd: (candidate: CustomCBLIssueSearchResult) => void
}

/**
 * Global issue search for the custom CBL editor. Owns the search input and its
 * submitted query, filters results against the draft entries, labels ambiguous
 * same-named series, and supports keyboard navigation from the field into the
 * result buttons. Adding an issue is delegated to the parent via `onAdd`.
 */
export default function CustomCBLIssueSearch({
  selectedId,
  disabled,
  isPending,
  entries,
  onAdd,
}: CustomCBLIssueSearchProps) {
  const issueSearchInput = useRef<HTMLInputElement>(null)
  const issueSearchResults = useRef<HTMLDivElement>(null)
  const [issueQuery, setIssueQuery] = useState('')
  const [submittedIssueQuery, setSubmittedIssueQuery] = useState('')

  const issueSearchQuery = useQuery({
    queryKey: queryKeys.customCBLs.issueSearch(submittedIssueQuery),
    queryFn: () => customCBLApi.searchIssues(submittedIssueQuery),
    enabled: selectedId !== null && submittedIssueQuery.length > 0,
  })

  const searchResults = (issueQuery.trim() === submittedIssueQuery ? issueSearchQuery.data ?? [] : [])
    .filter((candidate) => !entries.some((entry) => entry.issue_id === candidate.issue_id))
    .sort((a, b) => a.series_name.localeCompare(b.series_name) || a.thread_id - b.thread_id)

  // Show the series ID only when results hold several same-named series.
  const ambiguousSeriesNames = useMemo(() => {
    const ids = new Map<string, Set<number>>()
    searchResults.forEach((c) => ids.set(c.series_name.toLocaleLowerCase(), (ids.get(c.series_name.toLocaleLowerCase()) ?? new Set<number>()).add(c.thread_id)))
    return new Set([...ids].flatMap(([name, set]) => (set.size > 1 ? [name] : [])))
  }, [searchResults])

  const search = (event: FormEvent) => {
    event.preventDefault()
    const next = issueQuery.trim()
    if (!next || disabled || isPending) return
    setSubmittedIssueQuery(next)
  }
  const focusSearchResult = (event: KeyboardEvent<HTMLElement>, fromInput = false) => {
    const buttons = Array.from(issueSearchResults.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
    if (event.key === 'Escape' && !fromInput) {
      event.preventDefault()
      issueSearchInput.current?.focus()
      return
    }
    if (buttons.length === 0) return
    if (fromInput && event.key === 'Enter') {
      // Results already belong to this query: do not resubmit or add an
      // unintended issue. Enter adds only when a result button has focus.
      event.preventDefault()
      buttons[0].focus()
      return
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const current = event.target instanceof HTMLButtonElement ? buttons.indexOf(event.target) : -1
    const next = event.key === 'ArrowDown'
      ? (current + 1) % buttons.length
      : (current <= 0 ? buttons.length : current) - 1
    buttons[next].focus()
  }
  const addIssue = (candidate: CustomCBLIssueSearchResult) => {
    onAdd(candidate)
    issueSearchInput.current?.focus()
  }

  return (
    <>
      <form onSubmit={search} className="flex flex-col gap-2 sm:flex-row">
        <input ref={issueSearchInput} onKeyDown={(event) => focusSearchResult(event, true)} aria-describedby="custom-cbl-search-help" aria-label="Search issues for custom CBL" value={issueQuery} onChange={(event) => setIssueQuery(event.target.value)} placeholder="Search your issues, e.g. All-Star Comics" maxLength={200} disabled={disabled || isPending} className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50" />
        <button type="submit" disabled={!issueQuery.trim() || disabled || isPending || issueSearchQuery.isFetching} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">{issueSearchQuery.isFetching ? 'Searching…' : 'Find issues'}</button>
      </form>

      <p id="custom-cbl-search-help" className="text-xs text-[var(--theme-text-muted)]">Find issues, then use the arrow keys to choose a result and Enter to add it. Escape returns to search.</p>

      {searchResults.length > 0 && (
        <div ref={issueSearchResults} className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-[var(--theme-border)] p-2" aria-label="Custom CBL issue search results">
          {searchResults.map((candidate) => (
            <button key={candidate.issue_id} onKeyDown={(event) => focusSearchResult(event)} type="button" onClick={() => addIssue(candidate)} disabled={disabled || isPending} className="flex min-h-10 w-full items-center justify-between gap-3 rounded-lg px-2 text-left text-sm text-[var(--theme-text-primary)] hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)] disabled:opacity-50">
              <span>{candidate.series_name} #{candidate.issue_number}{ambiguousSeriesNames.has(candidate.series_name.toLocaleLowerCase()) && <span className="ml-2 text-xs text-[var(--theme-text-dim)]">Series ID {candidate.thread_id}</span>}</span><span className="text-xs text-[var(--theme-text-dim)]">Add</span>
            </button>
          ))}
        </div>
      )}
    </>
  )
}
