import { ReadingListReader } from './ReadingListReader'
import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { applyCommittedReadingPlan, applyCreatedCustomCBL, applyUpdatedCustomCBL, applyDeletedCustomCBL } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import Modal from './Modal'
import {
  customCBLApi,
  type CustomCBL,
  type CustomCBLEntry,
  type CustomCBLIssueSearchResult,
  type CustomCBLWrite,
  type ReadingListEntryIntent,
  type ReadingListGate,
  type ReadingListMode,
  type ReadingListPredecessorChange,
} from '../services/api-custom-cbl'
import type { ContinuityPlan } from '../services/api-continuity-plans'
import {
  computeEntryRequirements,
  decodeCustomCBLError,
  describeCyclePath,
  describePredecessorChange,
} from '../utils/readingListAuthoring'

interface CustomCBLBuilderProps {
  planId: number
  disabled?: boolean
  onApplied?: (plan: ContinuityPlan) => void
  onPendingChange?: (pending: boolean) => void
}

const DEFAULT_MODE: ReadingListMode = 'loose'
const DEFAULT_GATE: ReadingListGate = 'none'

const GATE_ORDER: ReadingListGate[] = ['none', 'after_previous', 'hold']

const GATE_LABELS: Record<ReadingListGate, string> = {
  none: 'No extra wait',
  after_previous: 'Wait for previous entry',
  hold: 'Hold until reached',
}

function toGate(value: string): ReadingListGate {
  return value === 'hold' || value === 'after_previous' ? value : 'none'
}

function normalizePositions(entries: CustomCBLEntry[]): CustomCBLEntry[] {
  return entries.map((entry, position) => ({
    ...entry,
    position,
    is_checkpoint: Boolean(entry.is_checkpoint),
    skipped: Boolean(entry.skipped),
    gate: entry.gate ?? DEFAULT_GATE,
  }))
}

function draftEntry(result: CustomCBLIssueSearchResult, position: number): CustomCBLEntry {
  return {
    id: -result.issue_id,
    position,
    issue_id: result.issue_id,
    thread_id: result.thread_id,
    series_name: result.series_name,
    issue_number: result.issue_number,
    status: result.status,
    is_checkpoint: false,
    gate: DEFAULT_GATE,
    skipped: false,
  }
}

function sameEntries(left: CustomCBLEntry[], right: CustomCBLEntry[]): boolean {
  return (
    left.length === right.length &&
    left.every((entry, index) => {
      const other = right[index]
      return (
        other !== undefined &&
        entry.issue_id === other.issue_id &&
        entry.gate === other.gate &&
        entry.skipped === other.skipped &&
        Boolean(entry.is_checkpoint) === Boolean(other.is_checkpoint)
      )
    })
  )
}

function buildWritePayload(
  name: string,
  description: string,
  mode: ReadingListMode,
  entries: CustomCBLEntry[],
  confirmed: ReadingListPredecessorChange[] | null,
): CustomCBLWrite {
  const issueIds: number[] = []
  const checkpointIds: number[] = []
  const entryIntents: Record<number, ReadingListEntryIntent> = {}
  for (const entry of entries) {
    issueIds.push(entry.issue_id)
    if (entry.is_checkpoint) checkpointIds.push(entry.issue_id)
    entryIntents[entry.issue_id] = { gate: entry.gate, skipped: entry.skipped }
  }
  const payload: CustomCBLWrite = {
    name: name.trim(),
    description: description.trim() || null,
    mode,
    issue_ids: issueIds,
    entry_intents: entryIntents,
    checkpoint_issue_ids: checkpointIds,
  }
  if (confirmed) payload.confirmed_predecessor_changes = confirmed
  return payload
}

function messageFor(error: unknown, fallback: string): string {
  const detail = decodeCustomCBLError(error)
  if (detail.message) return detail.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}

function waitDescription(
  entry: CustomCBLEntry,
  mode: ReadingListMode,
  waitingOn: number[],
  nameOf: (issueId: number) => string,
): string | null {
  const names = waitingOn.map(nameOf)
  const parts: string[] = []
  if (entry.skipped) {
    parts.push('Skipped in this list only; it does not wait and is not waited on.')
  } else if (names.length > 0) {
    parts.push(`Waits on ${names.join(', ')}.`)
  } else if (entry.gate === 'after_previous') {
    parts.push('Waits on the previous entry.')
  }
  if (entry.gate === 'hold' && !entry.skipped) {
    parts.push('Every later entry stays blocked until this milestone is read.')
  } else if (mode === 'strict' && entry.gate === 'none' && !entry.skipped && names.length > 0) {
    parts.push('Strict mode: waits on every earlier entry.')
  }
  return parts.length > 0 ? parts.join(' ') : null
}

export default function CustomCBLBuilder({
  planId,
  disabled = false,
  onApplied,
  onPendingChange,
}: CustomCBLBuilderProps) {
  const queryClient = useQueryClient()
  const issueSearchInput = useRef<HTMLInputElement>(null)
  const issueSearchResults = useRef<HTMLDivElement>(null)
  const [readerOpen, setReaderOpen] = useState(false)
  const [open, setOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loadedListId, setLoadedListId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [mode, setMode] = useState<ReadingListMode>(DEFAULT_MODE)
  const [entries, setEntries] = useState<CustomCBLEntry[]>([])
  const [issueQuery, setIssueQuery] = useState('')
  const [submittedIssueQuery, setSubmittedIssueQuery] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [exportError, setExportError] = useState<Error | null>(null)

  const listsQuery = useQuery({
    queryKey: queryKeys.customCBLs.list(),
    queryFn: customCBLApi.list,
    enabled: open,
  })
  const detailQuery = useQuery({
    queryKey: selectedId ? queryKeys.customCBLs.detail(selectedId) : queryKeys.customCBLs.detail(0),
    queryFn: () => {
      if (!selectedId) throw new Error('Choose a custom CBL first.')
      return customCBLApi.get(selectedId)
    },
    enabled: selectedId !== null,
  })
  const issueSearchQuery = useQuery({
    queryKey: queryKeys.customCBLs.issueSearch(submittedIssueQuery),
    queryFn: () => customCBLApi.searchIssues(submittedIssueQuery),
    enabled: selectedId !== null && submittedIssueQuery.length > 0,
  })

  useEffect(() => {
    const list = detailQuery.data
    if (!list) return
    // Only (re)seed the form when the selected list identity changes. React Query
    // can emit new data for the same list (refetch, cache write, or the second
    // run this effect triggers via setLoadedListId); reseeding then would discard
    // in-progress mode/gate/skip edits before the reader saves them.
    if (list.id === loadedListId) return
    setName(list.name)
    setDescription(list.description ?? '')
    setMode(list.mode ?? DEFAULT_MODE)
    setEntries(normalizePositions(list.entries))
    setLoadedListId(list.id)
    setMessage(null)
    setExportError(null)
  }, [detailQuery.data, loadedListId])

  const createMutation = useMutation({
    mutationFn: () => customCBLApi.create({ name: newName.trim(), issue_ids: [] }),
    onSuccess: async (created) => {
      await applyCreatedCustomCBL(queryClient, created)
      saveMutation.reset()
      setSelectedId(created.id)
      setNewName('')
      setMessage('Custom CBL created.')
    },
  })
  const saveMutation = useMutation({
    mutationFn: (confirmed: ReadingListPredecessorChange[] | null) => {
      if (!selectedId) throw new Error('Choose a custom CBL first.')
      return customCBLApi.update(
        selectedId,
        buildWritePayload(name, description, mode, entries, confirmed),
      )
    },
    onSuccess: async (saved) => {
      await applyUpdatedCustomCBL(queryClient, saved)
      setEntries(normalizePositions(saved.entries))
      setMode(saved.mode ?? DEFAULT_MODE)
      setMessage('Custom CBL saved.')
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (listId: number) => customCBLApi.delete(listId),
    onSuccess: async () => {
      if (selectedId) await applyDeletedCustomCBL(queryClient, selectedId)
      saveMutation.reset()
      setSelectedId(null)
      setLoadedListId(null)
      setName('')
      setDescription('')
      setMode(DEFAULT_MODE)
      setEntries([])
      setMessage('Custom CBL deleted.')
    },
  })
  const applyMutation = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error('Choose a custom CBL first.')
      return customCBLApi.apply(selectedId, planId)
    },
    onSuccess: async (result) => {
      await applyCommittedReadingPlan(queryClient, result)
      onApplied?.(result)
      const added = result.added_issue_ids.length
      const skipped = result.skipped_existing_issue_ids.length
      setMessage(`Applied to Reading Plan: ${added} added${skipped ? `, ${skipped} already present` : ''}.`)
    },
  })

  const isPending = createMutation.isPending || saveMutation.isPending || deleteMutation.isPending || applyMutation.isPending
  useEffect(() => {
    onPendingChange?.(isPending)
    return () => onPendingChange?.(false)
  }, [isPending, onPendingChange])

  const persisted = detailQuery.data
  const dirty = useMemo(() => {
    if (!persisted) return false
    return (
      name.trim() !== persisted.name ||
      (description.trim() || '') !== (persisted.description ?? '') ||
      mode !== (persisted.mode ?? DEFAULT_MODE) ||
      !sameEntries(entries, persisted.entries)
    )
  }, [description, entries, mode, name, persisted])

  const entryNames = useMemo(() => {
    const names = new Map<number, string>()
    for (const entry of entries) names.set(entry.issue_id, `${entry.series_name} #${entry.issue_number}`)
    return names
  }, [entries])
  const nameFor = (issueId: number): string => entryNames.get(issueId) ?? `Issue #${issueId}`

  const requirements = useMemo(() => computeEntryRequirements(mode, entries), [mode, entries])

  const saveErrorDetail = useMemo(
    () => (saveMutation.error ? decodeCustomCBLError(saveMutation.error) : null),
    [saveMutation.error],
  )
  const confirmationChanges =
    saveErrorDetail?.code === 'reading_list_predecessor_confirmation_required' &&
    saveErrorDetail.predecessorChanges.length > 0
      ? saveErrorDetail.predecessorChanges
      : null
  const cycleError = useMemo(() => {
    if (saveErrorDetail?.code !== 'reading_list_cycle') return null
    const resolveName = (issueId: number) => entryNames.get(issueId) ?? `Issue #${issueId}`
    return describeCyclePath(saveErrorDetail.cyclePath, resolveName)
  }, [entryNames, saveErrorDetail])

  const searchResults = (issueQuery.trim() === submittedIssueQuery ? issueSearchQuery.data ?? [] : []).filter(
    (candidate) => !entries.some((entry) => entry.issue_id === candidate.issue_id),
  )

  const create = (event: FormEvent) => {
    event.preventDefault()
    if (!newName.trim() || disabled || isPending) return
    setMessage(null)
    createMutation.mutate()
  }
  const search = (event: FormEvent) => {
    event.preventDefault()
    const next = issueQuery.trim()
    if (!next || disabled || isPending) return
    setSubmittedIssueQuery(next)
  }
  const addIssue = (candidate: CustomCBLIssueSearchResult) => {
    setEntries((current) => [...current, draftEntry(candidate, current.length)])
    setMessage(`Added ${candidate.series_name} #${candidate.issue_number} to this list. Save to keep your changes.`)
    issueSearchInput.current?.focus()
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
  const removeIssue = (issueId: number) => {
    setEntries((current) => normalizePositions(current.filter((entry) => entry.issue_id !== issueId)))
    setMessage(null)
  }
  const moveIssue = (index: number, delta: -1 | 1) => {
    const target = index + delta
    if (target < 0 || target >= entries.length) return
    setEntries((current) => {
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return normalizePositions(next)
    })
    setMessage(null)
  }
  const updateGate = (issueId: number, gate: ReadingListGate) => {
    setEntries((current) =>
      current.map((entry) => (entry.issue_id === issueId ? { ...entry, gate } : entry)),
    )
    setMessage(null)
  }
  const toggleSkipped = (issueId: number) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.issue_id === issueId ? { ...entry, skipped: !entry.skipped } : entry,
      ),
    )
    setMessage(null)
  }
  const toggleCheckpoint = (issueId: number) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.issue_id === issueId ? { ...entry, is_checkpoint: !entry.is_checkpoint } : entry,
      ),
    )
    setMessage(null)
  }
  const chooseList = (value: string) => {
    const next = value ? Number(value) : null
    if (next === selectedId) return
    // Saving can fail with a structured preview/cycle error tied to the list that
    // was submitted; switching lists must not carry that feedback onto another list.
    saveMutation.reset()
    setMessage(null)
    setSelectedId(next)
  }
  const exportList = async () => {
    if (!selectedId || !persisted || dirty || disabled || isPending) return
    setExportError(null)
    let url: string | null = null
    try {
      const xml = await customCBLApi.exportXml(selectedId)
      const blob = new Blob([xml], { type: 'application/xml' })
      url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${persisted.name.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'custom-reading-list'}.cbl`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (caught) {
      setExportError(caught instanceof Error ? caught : new Error('Custom CBL export failed.'))
    } finally {
      if (url) URL.revokeObjectURL(url)
    }
  }

  const structuredSaveError = confirmationChanges !== null || cycleError !== null
  const error =
    exportError ??
    createMutation.error ??
    deleteMutation.error ??
    applyMutation.error ??
    (structuredSaveError ? null : saveMutation.error) ??
    detailQuery.error ??
    listsQuery.error
  const errorText = error ? messageFor(error, 'Custom CBL operation failed.') : null
  const warnings = persisted?.warnings ?? []

  return (
    <section className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3" aria-labelledby="custom-cbl-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 id="custom-cbl-heading" className="text-sm font-black text-[var(--theme-text-primary)]">Custom CBLs</h3>
          <p className="mt-1 text-xs text-[var(--theme-text-muted)]">Build one ordered list of real comics, choose a strict or loose reading order, add optional waits, and apply it to this Reading Plan.</p>
        </div>
        <button type="button" onClick={() => setOpen((value) => !value)} disabled={disabled || isPending} className="min-h-10 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50" aria-expanded={open}>
          {open ? 'Close custom CBLs' : 'Create or edit custom CBL'}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-4 border-t border-[var(--theme-border)] pt-4">
          <form onSubmit={create} className="flex flex-col gap-2 sm:flex-row">
            <input aria-label="New custom CBL name" value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="New custom CBL name" maxLength={200} disabled={disabled || isPending} className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50" />
            <button type="submit" disabled={!newName.trim() || disabled || isPending} className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50">Create</button>
          </form>

          {(listsQuery.data?.length ?? 0) > 0 && (
            <label className="block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
              Custom CBL
              <select aria-label="Custom CBL" value={selectedId ?? ''} onChange={(event) => chooseList(event.target.value)} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50">
                <option value="">Choose a custom CBL</option>
                {(listsQuery.data ?? []).map((list) => <option key={list.id} value={list.id}>{list.name} · {list.issue_count} issues · {list.mode}</option>)}
              </select>
            </label>
          )}

          {selectedId && persisted && (
            <div className="space-y-4 rounded-xl border border-[var(--theme-border)] p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">Name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm normal-case tracking-normal text-[var(--theme-text-primary)] disabled:opacity-50" /></label>
                <label className="text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">Description<input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm normal-case tracking-normal text-[var(--theme-text-primary)] disabled:opacity-50" /></label>
              </div>

              <fieldset disabled={disabled || isPending} className="rounded-xl border border-[var(--theme-border)] p-3">
                <legend className="px-1 text-sm font-medium text-[var(--theme-text-primary)]">List mode</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="flex items-start gap-2 text-sm text-[var(--theme-text-primary)]">
                    <input type="radio" name={`custom-cbl-mode-${planId}`} value="strict" checked={mode === 'strict'} onChange={() => setMode('strict')} className="mt-1 h-4 w-4" />
                    <span>
                      <span className="font-bold">Strict</span>
                      <span className="block text-xs text-[var(--theme-text-muted)]">Every unread entry waits for all earlier entries, so only this list's first unread issue is available.</span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2 text-sm text-[var(--theme-text-primary)]">
                    <input type="radio" name={`custom-cbl-mode-${planId}`} value="loose" checked={mode === 'loose'} onChange={() => setMode('loose')} className="mt-1 h-4 w-4" />
                    <span>
                      <span className="font-bold">Loose</span>
                      <span className="block text-xs text-[var(--theme-text-muted)]">Entries stand alone unless you add a wait. Placement never blocks progress in another series.</span>
                    </span>
                  </label>
                </div>
                {mode === 'strict' && (
                  <p className="mt-2 text-xs text-[var(--theme-text-muted)]">Strict lists warn when you leave out unread issues from a series you placed here; saving does not silently gate the omitted issues.</p>
                )}
              </fieldset>

              <form onSubmit={search} className="flex flex-col gap-2 sm:flex-row">
                <input ref={issueSearchInput} onKeyDown={(event) => focusSearchResult(event, true)} aria-describedby="custom-cbl-search-help" aria-label="Search issues for custom CBL" value={issueQuery} onChange={(event) => setIssueQuery(event.target.value)} placeholder="Search your issues, e.g. All-Star Comics" maxLength={200} disabled={disabled || isPending} className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50" />
                <button type="submit" disabled={!issueQuery.trim() || disabled || isPending || issueSearchQuery.isFetching} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">{issueSearchQuery.isFetching ? 'Searching…' : 'Find issues'}</button>
              </form>

              <p id="custom-cbl-search-help" className="text-xs text-[var(--theme-text-muted)]">Find issues, then use the arrow keys to choose a result and Enter to add it. Escape returns to search.</p>

              {searchResults.length > 0 && (
                <div ref={issueSearchResults} className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-[var(--theme-border)] p-2" aria-label="Custom CBL issue search results">
                  {searchResults.map((candidate) => (
                    <button key={candidate.issue_id} onKeyDown={(event) => focusSearchResult(event)} type="button" onClick={() => addIssue(candidate)} disabled={disabled || isPending} className="flex min-h-10 w-full items-center justify-between gap-3 rounded-lg px-2 text-left text-sm text-[var(--theme-text-primary)] hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)] disabled:opacity-50">
                      <span>{candidate.series_name} #{candidate.issue_number}</span><span className="text-xs text-[var(--theme-text-dim)]">Add</span>
                    </button>
                  ))}
                </div>
              )}

              <ol className="space-y-2" aria-label="Custom CBL ordered issues">
                {entries.map((entry, index) => {
                  const label = `${entry.series_name} #${entry.issue_number}`
                  const waitText = waitDescription(entry, mode, requirements.get(entry.issue_id) ?? [], nameFor)
                  return (
                    <li key={entry.issue_id} className="rounded-xl border border-[var(--theme-border)] p-2">
                      <div className="flex items-center gap-2">
                        <span aria-hidden="true" className="w-7 shrink-0 text-center text-xs font-black text-[var(--theme-text-dim)]">{index + 1}</span>
                        <span className="min-w-0 flex-1 truncate text-sm text-[var(--theme-text-primary)]">
                          {label}
                          {entry.skipped && <span className="ml-2 rounded-full border border-[var(--theme-border)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">Skipped in this list</span>}
                        </span>
                        <button
                          type="button"
                          onClick={() => toggleCheckpoint(entry.issue_id)}
                          title="Crossover checkpoint metadata. It records where a crossover resumes and does not by itself make later entries wait."
                          aria-label={entry.is_checkpoint ? `Remove crossover checkpoint from ${label}` : `Mark ${label} as crossover checkpoint`}
                          disabled={disabled || isPending}
                          className={`min-h-9 rounded-lg border px-2 text-[10px] font-bold uppercase tracking-wider ${entry.is_checkpoint ? 'border-[var(--theme-comic-accent)] bg-[var(--theme-bg-panel)] text-[var(--theme-comic-accent)]' : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]'} disabled:opacity-50`}
                        >
                          {entry.is_checkpoint ? '⚑' : '⚐'}
                        </button>
                        <button type="button" aria-label={`Move ${label} earlier`} onClick={() => moveIssue(index, -1)} disabled={index === 0 || disabled || isPending} className="min-h-9 min-w-9 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30">↑</button>
                        <button type="button" aria-label={`Move ${label} later`} onClick={() => moveIssue(index, 1)} disabled={index === entries.length - 1 || disabled || isPending} className="min-h-9 min-w-9 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30">↓</button>
                        <button type="button" aria-label={`Remove ${label}`} onClick={() => removeIssue(entry.issue_id)} disabled={disabled || isPending} className="min-h-9 rounded-lg border border-[var(--theme-danger)] px-2 text-xs font-bold text-[var(--theme-danger)] disabled:opacity-50">Remove</button>
                      </div>
                      <div className="mt-2 flex flex-wrap items-end gap-3 pl-9">
                        <label className="text-xs text-[var(--theme-text-muted)]">
                          <span className="block font-semibold text-[var(--theme-text-primary)]">Wait behavior</span>
                          <select
                            aria-label={`Wait behavior for ${label}`}
                            value={entry.gate}
                            onChange={(event) => updateGate(entry.issue_id, toGate(event.target.value))}
                            disabled={disabled || isPending || entry.skipped}
                            className="mt-1 min-h-9 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 text-sm text-[var(--theme-text-primary)] disabled:opacity-50"
                          >
                            {GATE_ORDER.map((gate) => (
                              <option key={gate} value={gate}>{GATE_LABELS[gate]}</option>
                            ))}
                          </select>
                        </label>
                        <label className="flex min-h-9 items-center gap-2 text-xs text-[var(--theme-text-primary)]">
                          <input
                            type="checkbox"
                            aria-label={`Skip ${label} in this list`}
                            checked={entry.skipped}
                            onChange={() => toggleSkipped(entry.issue_id)}
                            disabled={disabled || isPending}
                            className="h-4 w-4"
                          />
                          Skip in this list
                        </label>
                      </div>
                      {waitText && <p className="mt-1 pl-9 text-xs text-[var(--theme-text-muted)]">{waitText}</p>}
                    </li>
                  )
                })}
              </ol>
              {entries.length === 0 && <p className="text-sm text-[var(--theme-text-muted)]">This custom CBL is empty. Search for issues above to build it.</p>}
              <p className="text-xs text-[var(--theme-text-muted)]">Skipping an issue here ignores it only in this list. It stays in your collection and other lists. Use your collection exclusions to remove a comic everywhere.</p>

              <button type="button" onClick={() => setReaderOpen((value) => !value)} aria-expanded={readerOpen} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-semibold text-[var(--theme-text-primary)]">{readerOpen ? 'Close list reader' : 'Read this list'}</button>
              {readerOpen && selectedId && <ReadingListReader key={selectedId} listId={selectedId} />}
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => saveMutation.mutate(null)} disabled={!dirty || !name.trim() || disabled || isPending} className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50">{saveMutation.isPending ? 'Saving…' : 'Save custom CBL'}</button>
                <button type="button" onClick={() => applyMutation.mutate()} disabled={dirty || entries.length === 0 || disabled || isPending} className="min-h-11 rounded-xl border border-[var(--theme-continuity-accent)] px-4 text-sm font-black text-[var(--theme-continuity-accent)] disabled:opacity-50">{applyMutation.isPending ? 'Applying…' : 'Apply to this Reading Plan'}</button>
                <button type="button" onClick={() => void exportList()} disabled={dirty || entries.length === 0 || disabled || isPending} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">Export .cbl</button>
                <button type="button" onClick={() => { if (selectedId && window.confirm(`Delete custom CBL “${persisted.name}”?`)) deleteMutation.mutate(selectedId) }} disabled={disabled || isPending} className="min-h-11 rounded-xl border border-[var(--theme-danger)] px-4 text-sm font-bold text-[var(--theme-danger)] disabled:opacity-50">Delete</button>
              </div>
              {dirty && <p className="text-xs text-[var(--theme-warning)]">Save this custom CBL before applying or exporting it.</p>}
            </div>
          )}

          {warnings.length > 0 && (
            <div className="rounded-xl border border-[var(--theme-warning)]/60 p-3" aria-live="polite">
              <p className="text-xs font-bold uppercase tracking-wider text-[var(--theme-warning)]">Coverage warnings</p>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-[var(--theme-text-muted)]" aria-label="Strict list coverage warnings">
                {warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          )}
          {cycleError && <p role="alert" className="text-sm text-[var(--theme-warning)]">{cycleError}</p>}
          {message && <p role="status" className="text-sm text-emerald-300">{message}</p>}
          {errorText && <p role="alert" className="text-sm text-red-300">{errorText}</p>}
        </div>
      )}

      <Modal
        isOpen={confirmationChanges !== null}
        title="Confirm waiting changes"
        onClose={() => saveMutation.reset()}
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            This edit changes which issues wait on which. Review the new waits, then confirm to save. Cancel keeps the saved list exactly as it is.
          </p>
          <ul className="space-y-2" aria-label="Waiting changes">
            {(confirmationChanges ?? []).map((change) => (
              <li key={change.issue_id} className="rounded-xl border border-[var(--theme-border)] p-3 text-sm text-[var(--theme-text-primary)]">
                {describePredecessorChange(change)}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={() => saveMutation.reset()} disabled={saveMutation.isPending} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">Cancel</button>
            <button
              type="button"
              onClick={() => saveMutation.mutate(saveErrorDetail?.predecessorChanges ?? null)}
              disabled={saveMutation.isPending}
              className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
            >
              {saveMutation.isPending ? 'Saving…' : 'Confirm and save'}
            </button>
          </div>
        </div>
      </Modal>
    </section>
  )
}
