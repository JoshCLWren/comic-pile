import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { applyCommittedReadingPlan, applyCreatedCustomCBL, applyUpdatedCustomCBL, applyDeletedCustomCBL } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import {
  customCBLApi,
  type CustomCBL,
  type CustomCBLEntry,
  type CustomCBLIssueSearchResult,
} from '../services/api-custom-cbl'
import type { ContinuityPlan } from '../services/api-continuity-plans'

interface CustomCBLBuilderProps {
  planId: number
  disabled?: boolean
  onApplied?: (plan: ContinuityPlan) => void
  onPendingChange?: (pending: boolean) => void
}

function normalizePositions(entries: CustomCBLEntry[]): CustomCBLEntry[] {
  return entries.map((entry, position) => ({ ...entry, position }))
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
  }
}

function sameIssueOrder(left: CustomCBLEntry[], right: CustomCBLEntry[]): boolean {
  return left.length === right.length && left.every((entry, index) => entry.issue_id === right[index]?.issue_id)
}

export default function CustomCBLBuilder({
  planId,
  disabled = false,
  onApplied,
  onPendingChange,
}: CustomCBLBuilderProps) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
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
    setName(list.name)
    setDescription(list.description ?? '')
    setEntries(normalizePositions(list.entries))
    setMessage(null)
    setExportError(null)
  }, [detailQuery.data])

  const createMutation = useMutation({
    mutationFn: () => customCBLApi.create({ name: newName.trim(), issue_ids: [] }),
    onSuccess: async (created) => {
      await applyCreatedCustomCBL(queryClient, created)
      setSelectedId(created.id)
      setNewName('')
      setMessage('Custom CBL created.')
    },
  })
  const saveMutation = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error('Choose a custom CBL first.')
      return customCBLApi.update(selectedId, {
        name: name.trim(),
        description: description.trim() || null,
        issue_ids: entries.map((entry) => entry.issue_id),
      })
    },
    onSuccess: async (saved) => {
      await applyUpdatedCustomCBL(queryClient, saved)
      setEntries(normalizePositions(saved.entries))
      setMessage('Custom CBL saved.')
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (listId: number) => customCBLApi.delete(listId),
    onSuccess: async () => {
      if (selectedId) await applyDeletedCustomCBL(queryClient, selectedId)
      setSelectedId(null)
      setName('')
      setDescription('')
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
      !sameIssueOrder(entries, persisted.entries)
    )
  }, [description, entries, name, persisted])

  const searchResults = (issueSearchQuery.data ?? []).filter(
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
    setMessage(null)
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

  const error = exportError ?? createMutation.error ?? saveMutation.error ?? deleteMutation.error ?? applyMutation.error ?? detailQuery.error ?? listsQuery.error

  return (
    <section className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-card)] p-3" aria-labelledby="custom-cbl-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 id="custom-cbl-heading" className="text-sm font-black text-[var(--theme-text-primary)]">Custom CBLs</h3>
          <p className="mt-1 text-xs text-[var(--theme-text-muted)]">Build an ordered list from real ComicPile issues, then apply it to this Reading Plan.</p>
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
              <select value={selectedId ?? ''} onChange={(event) => setSelectedId(event.target.value ? Number(event.target.value) : null)} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50">
                <option value="">Choose a custom CBL</option>
                {(listsQuery.data ?? []).map((list) => <option key={list.id} value={list.id}>{list.name} · {list.issue_count} issues</option>)}
              </select>
            </label>
          )}

          {selectedId && persisted && (
            <div className="space-y-4 rounded-xl border border-[var(--theme-border)] p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">Name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm normal-case tracking-normal text-[var(--theme-text-primary)] disabled:opacity-50" /></label>
                <label className="text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">Description<input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm normal-case tracking-normal text-[var(--theme-text-primary)] disabled:opacity-50" /></label>
              </div>

              <form onSubmit={search} className="flex flex-col gap-2 sm:flex-row">
                <input aria-label="Search issues for custom CBL" value={issueQuery} onChange={(event) => setIssueQuery(event.target.value)} placeholder="Search your issues, e.g. All-Star Comics" maxLength={200} disabled={disabled || isPending} className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50" />
                <button type="submit" disabled={!issueQuery.trim() || disabled || isPending || issueSearchQuery.isFetching} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">{issueSearchQuery.isFetching ? 'Searching…' : 'Find issues'}</button>
              </form>

              {searchResults.length > 0 && (
                <div className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-[var(--theme-border)] p-2" aria-label="Custom CBL issue search results">
                  {searchResults.map((candidate) => (
                    <button key={candidate.issue_id} type="button" onClick={() => addIssue(candidate)} disabled={disabled || isPending} className="flex min-h-10 w-full items-center justify-between gap-3 rounded-lg px-2 text-left text-sm text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50">
                      <span>{candidate.series_name} #{candidate.issue_number}</span><span className="text-xs text-[var(--theme-text-dim)]">Add</span>
                    </button>
                  ))}
                </div>
              )}

              <ol className="space-y-2" aria-label="Custom CBL ordered issues">
                {entries.map((entry, index) => (
                  <li key={entry.issue_id} className="flex items-center gap-2 rounded-xl border border-[var(--theme-border)] p-2">
                    <span className="w-7 shrink-0 text-center text-xs font-black text-[var(--theme-text-dim)]">{index + 1}</span>
                    <span className="min-w-0 flex-1 truncate text-sm text-[var(--theme-text-primary)]">{entry.series_name} #{entry.issue_number}</span>
                    <button type="button" aria-label={`Move ${entry.series_name} #${entry.issue_number} earlier`} onClick={() => moveIssue(index, -1)} disabled={index === 0 || disabled || isPending} className="min-h-9 min-w-9 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30">↑</button>
                    <button type="button" aria-label={`Move ${entry.series_name} #${entry.issue_number} later`} onClick={() => moveIssue(index, 1)} disabled={index === entries.length - 1 || disabled || isPending} className="min-h-9 min-w-9 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30">↓</button>
                    <button type="button" aria-label={`Remove ${entry.series_name} #${entry.issue_number}`} onClick={() => removeIssue(entry.issue_id)} disabled={disabled || isPending} className="min-h-9 rounded-lg border border-red-900 px-2 text-xs font-bold text-red-300 disabled:opacity-50">Remove</button>
                  </li>
                ))}
              </ol>
              {entries.length === 0 && <p className="text-sm text-[var(--theme-text-muted)]">This custom CBL is empty. Search for issues above to build it.</p>}

              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => saveMutation.mutate()} disabled={!dirty || !name.trim() || disabled || isPending} className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50">{saveMutation.isPending ? 'Saving…' : 'Save custom CBL'}</button>
                <button type="button" onClick={() => applyMutation.mutate()} disabled={dirty || entries.length === 0 || disabled || isPending} className="min-h-11 rounded-xl border border-[var(--theme-continuity-accent)] px-4 text-sm font-black text-[var(--theme-continuity-accent)] disabled:opacity-50">{applyMutation.isPending ? 'Applying…' : 'Apply to this Reading Plan'}</button>
                <button type="button" onClick={() => void exportList()} disabled={dirty || entries.length === 0 || disabled || isPending} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">Export .cbl</button>
                <button type="button" onClick={() => { if (selectedId && window.confirm(`Delete custom CBL “${persisted.name}”?`)) deleteMutation.mutate(selectedId) }} disabled={disabled || isPending} className="min-h-11 rounded-xl border border-red-900 px-4 text-sm font-bold text-red-300 disabled:opacity-50">Delete</button>
              </div>
              {dirty && <p className="text-xs text-amber-300">Save this custom CBL before applying or exporting it.</p>}
            </div>
          )}

          {message && <p role="status" className="text-sm text-emerald-300">{message}</p>}
          {error && <p role="alert" className="text-sm text-red-300">{error instanceof Error ? error.message : 'Custom CBL operation failed.'}</p>}
        </div>
      )}
    </section>
  )
}
