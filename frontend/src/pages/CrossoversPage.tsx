import { FormEvent, useCallback, useEffect, useState } from 'react'
import axios from 'axios'
import {
  ContinuityIssueRangeSelector,
  ContinuityThreadSelector,
  type SelectedIssueRange,
} from '../components/continuity'
import { threadsApi } from '../services/api'
import {
  dependencyGroupsApi,
  type DependencyGroup,
} from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import type { Issue, Thread } from '../types'

type PositionedIssue = Issue & { position: number }

async function fetchAllIssues(threadId: number): Promise<PositionedIssue[]> {
  const issues: PositionedIssue[] = []
  const seenPageTokens = new Set<string>()
  let nextPageToken: string | null = null

  while (true) {
    const data = await issuesApi.list(threadId, {
      page_size: 100,
      ...(nextPageToken ? { page_token: nextPageToken } : {}),
    })
    const pageIssues = data.issues as PositionedIssue[]
    if (pageIssues.some((issue) => !Number.isInteger(issue.position) || issue.position < 1)) {
      throw new Error('Comic issue order is unavailable for this series.')
    }
    issues.push(...pageIssues)
    if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) return issues
    seenPageTokens.add(data.next_page_token)
    nextPageToken = data.next_page_token
  }
}

async function fetchAllThreads(): Promise<Thread[]> {
  const threads: Thread[] = []
  const seenPageTokens = new Set<string>()
  let nextPageToken: string | null = null

  while (true) {
    const data = await threadsApi.list({ page_size: 100 }, nextPageToken)
    threads.push(...data.threads)
    if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) return threads
    seenPageTokens.add(data.next_page_token)
    nextPageToken = data.next_page_token
  }
}

function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return error instanceof Error && error.message ? error.message : fallback
}

export default function CrossoversPage() {
  const [groups, setGroups] = useState<DependencyGroup[]>([])
  const [threads, setThreads] = useState<Thread[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [threadLoadError, setThreadLoadError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingName, setEditingName] = useState('')
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [memberThread, setMemberThread] = useState<Thread | null>(null)
  const [rangeThread, setRangeThread] = useState<Thread | null>(null)
  const [rangeIssues, setRangeIssues] = useState<PositionedIssue[]>([])
  const [rangeSelection, setRangeSelection] = useState<SelectedIssueRange | null>(null)
  const [isLoadingRangeIssues, setIsLoadingRangeIssues] = useState(false)
  const [rangeLoadError, setRangeLoadError] = useState<string | null>(null)
  const [membershipMessage, setMembershipMessage] = useState<string | null>(null)

  const loadGroups = useCallback(async () => {
    setIsLoading(true)
    setLoadError(null)
    try {
      setGroups(await dependencyGroupsApi.list())
    } catch (error) {
      setLoadError(errorMessage(error, 'Unable to load crossovers.'))
    } finally {
      setIsLoading(false)
    }
  }, [])

  const loadThreads = useCallback(async () => {
    setThreadLoadError(null)
    try {
      setThreads(await fetchAllThreads())
    } catch (error) {
      setThreads([])
      setThreadLoadError(errorMessage(error, 'Unable to load comics for selection.'))
    }
  }, [])

  useEffect(() => {
    void loadGroups()
    void loadThreads()
  }, [loadGroups, loadThreads])

  const clearRangeState = () => {
    setRangeThread(null)
    setRangeIssues([])
    setRangeSelection(null)
    setRangeLoadError(null)
    setIsLoadingRangeIssues(false)
  }

  const clearMembershipState = () => {
    setMemberThread(null)
    clearRangeState()
    setMembershipMessage(null)
  }

  const toggleExpanded = (groupId: number) => {
    if (busyId !== null) return
    setExpandedId((current) => (current === groupId ? null : groupId))
    clearMembershipState()
    setMutationError(null)
  }

  const createGroup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName) {
      setCreateError('Enter a crossover name.')
      return
    }
    setCreateError(null)
    setIsCreating(true)
    try {
      const created = await dependencyGroupsApi.create(trimmedName)
      setGroups((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)))
      setName('')
    } catch (error) {
      setCreateError(errorMessage(error, 'Unable to create crossover.'))
    } finally {
      setIsCreating(false)
    }
  }

  const saveRename = async (groupId: number) => {
    const trimmedName = editingName.trim()
    if (!trimmedName) {
      setMutationError('Enter a crossover name.')
      return
    }
    setMutationError(null)
    setBusyId(groupId)
    try {
      const renamed = await dependencyGroupsApi.rename(groupId, trimmedName)
      setGroups((current) => current.map((group) => (group.id === groupId ? renamed : group)).sort((a, b) => a.name.localeCompare(b.name)))
      setEditingId(null)
      setEditingName('')
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to rename crossover.'))
    } finally {
      setBusyId(null)
    }
  }

  const deleteGroup = async (group: DependencyGroup) => {
    if (busyId !== null || !window.confirm(`Delete “${group.name}”? Its comic memberships will be removed.`)) return
    setMutationError(null)
    setBusyId(group.id)
    try {
      await dependencyGroupsApi.delete(group.id)
      setGroups((current) => current.filter((item) => item.id !== group.id))
      if (expandedId === group.id) setExpandedId(null)
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to delete crossover.'))
    } finally {
      setBusyId(null)
    }
  }

  const addThreadMember = async (event: FormEvent<HTMLFormElement>, groupId: number) => {
    event.preventDefault()
    if (!memberThread) {
      setMutationError('Choose a comic series to add.')
      return
    }
    setMutationError(null)
    setMembershipMessage(null)
    setBusyId(groupId)
    try {
      const member = await dependencyGroupsApi.addMember(groupId, { thread_id: memberThread.id })
      setGroups((current) => current.map((group) => group.id === groupId ? { ...group, memberships: [...group.memberships, member] } : group))
      setMemberThread(null)
      setMembershipMessage(`${memberThread.title} added to crossover.`)
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to add thread to crossover.'))
    } finally {
      setBusyId(null)
    }
  }

  const selectRangeThread = async (thread: Thread | null) => {
    setRangeThread(thread)
    setRangeIssues([])
    setRangeSelection(null)
    setRangeLoadError(null)
    if (!thread) return
    setIsLoadingRangeIssues(true)
    try {
      const issues = await fetchAllIssues(thread.id)
      setRangeIssues(issues)
      if (issues.length === 0) setRangeLoadError(`${thread.title} has no issues to add.`)
    } catch (error) {
      setRangeIssues([])
      setRangeLoadError(errorMessage(error, 'Unable to load issues for this series.'))
    } finally {
      setIsLoadingRangeIssues(false)
    }
  }

  const addRange = async (event: FormEvent<HTMLFormElement>, groupId: number) => {
    event.preventDefault()
    if (!rangeThread || !rangeSelection) {
      setMutationError('Choose a series and an inclusive first and last issue.')
      return
    }
    const startPosition = (rangeSelection.startIssue as PositionedIssue).position
    const endPosition = (rangeSelection.endIssue as PositionedIssue).position
    if (!Number.isInteger(startPosition) || !Number.isInteger(endPosition) || startPosition < 1 || endPosition < startPosition) {
      setMutationError('Choose a valid issue range in reading order.')
      return
    }
    setMutationError(null)
    setMembershipMessage(null)
    setBusyId(groupId)
    try {
      const result = await dependencyGroupsApi.addIssueRange(groupId, rangeThread.id, startPosition, endPosition)
      const successMessage = `${result.added_issue_ids.length} added, ${result.already_present_issue_ids.length} already present.`
      setMembershipMessage(successMessage)
      clearRangeState()
      try {
        const refreshed = await dependencyGroupsApi.get(groupId)
        setGroups((current) => current.map((group) => (group.id === groupId ? refreshed : group)))
      } catch (error) {
        setMembershipMessage(`${successMessage} Saved, but the latest memberships could not be refreshed: ${errorMessage(error, 'Unable to refresh crossover memberships.')}`)
      }
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to add issue range.'))
    } finally {
      setBusyId(null)
    }
  }

  const removeMember = async (groupId: number, memberId: number) => {
    if (busyId !== null) return
    setMutationError(null)
    setMembershipMessage(null)
    setBusyId(groupId)
    try {
      await dependencyGroupsApi.removeMember(groupId, memberId)
      setGroups((current) => current.map((group) => group.id === groupId ? { ...group, memberships: group.memberships.filter((member) => member.id !== memberId) } : group))
      setMembershipMessage('Comic removed from crossover.')
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to remove crossover member.'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="space-y-6" aria-labelledby="crossovers-heading">
      <header>
        <p className="text-xs font-bold uppercase tracking-[0.25em] text-amber-500">Continuity</p>
        <h1 id="crossovers-heading" className="mt-1 text-3xl font-black text-stone-100">Crossovers</h1>
        <p className="mt-2 max-w-2xl text-sm text-stone-400">Name connected comics so their continuity is easy to recognize across ComicPile. Membership does not create a reading block by itself.</p>
      </header>

      <form onSubmit={createGroup} className="rounded-2xl border border-stone-700 bg-stone-900/70 p-4" aria-label="Create crossover">
        <label htmlFor="crossover-name" className="block text-sm font-bold text-stone-200">New crossover</label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input id="crossover-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={200} className="min-w-0 flex-1 rounded-xl border border-stone-600 bg-stone-950 px-3 py-2.5 text-stone-100" placeholder="Age of Apocalypse" disabled={isCreating || isLoading} />
          <button type="submit" disabled={isCreating || isLoading} className="rounded-xl bg-amber-500 px-4 py-2.5 font-bold text-stone-950 disabled:opacity-50">{isCreating ? 'Creating…' : 'Create crossover'}</button>
        </div>
        {createError && <p role="alert" className="mt-2 text-sm text-red-400">{createError}</p>}
      </form>

      {mutationError && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/40 p-3 text-sm text-red-300">{mutationError}</p>}
      {isLoading ? <p role="status">Loading crossovers…</p> : loadError ? <div role="alert"><p>{loadError}</p><button type="button" onClick={() => void loadGroups()}>Try again</button></div> : groups.length === 0 ? <p>No crossovers yet</p> : (
        <ul className="grid gap-3" aria-label="Your crossovers">
          {groups.map((group) => {
            const isEditing = editingId === group.id
            const isBusy = busyId === group.id
            const hasPendingMutation = busyId !== null
            const isExpanded = expandedId === group.id
            return (
              <li key={group.id} className="rounded-2xl border border-stone-700 bg-stone-900/60 p-4">
                {isEditing ? (
                  <div className="flex gap-2">
                    <input aria-label={`Rename ${group.name}`} value={editingName} onChange={(event) => setEditingName(event.target.value)} disabled={isBusy} className="min-w-0 flex-1 rounded-xl border border-stone-600 bg-stone-950 px-3 py-2" />
                    <button type="button" onClick={() => void saveRename(group.id)} disabled={isBusy}>Save</button>
                    <button type="button" onClick={() => setEditingId(null)} disabled={isBusy}>Cancel</button>
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-3">
                    <button type="button" onClick={() => toggleExpanded(group.id)} disabled={hasPendingMutation} aria-expanded={isExpanded} className="min-w-0 text-left">
                      <span className="block text-lg font-black text-stone-100">{group.name}</span>
                      <span className="text-sm text-stone-500">{group.memberships.length} {group.memberships.length === 1 ? 'member' : 'members'}</span>
                    </button>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => { setEditingId(group.id); setEditingName(group.name) }} disabled={hasPendingMutation}>Rename</button>
                      <button type="button" onClick={() => void deleteGroup(group)} disabled={hasPendingMutation}>Delete</button>
                    </div>
                  </div>
                )}

                {isExpanded && !isEditing && (
                  <div className="mt-4 space-y-4 border-t border-stone-800 pt-4 text-sm text-stone-400">
                    {group.memberships.length === 0 ? <p>This crossover has no comics yet.</p> : (
                      <ul className="grid gap-2" aria-label={`${group.name} members`}>
                        {group.memberships.map((member) => (
                          <li key={member.id} className="flex items-center justify-between gap-3 rounded-xl border border-stone-800 px-3 py-2">
                            <span>{member.issue_id !== null ? `Issue ${member.issue_id}` : `Thread ${member.thread_id}`}</span>
                            <button type="button" onClick={() => void removeMember(group.id, member.id)} disabled={hasPendingMutation} aria-label={`Remove ${member.issue_id !== null ? `issue ${member.issue_id}` : `thread ${member.thread_id}`} from ${group.name}`}>Remove</button>
                          </li>
                        ))}
                      </ul>
                    )}

                    <form onSubmit={(event) => void addThreadMember(event, group.id)} aria-label={`Add thread to ${group.name}`} className="grid gap-2 rounded-xl border border-stone-800 bg-stone-950/50 p-3 sm:grid-cols-[1fr_auto]">
                      <ContinuityThreadSelector threads={threads} value={memberThread} onChange={setMemberThread} label="Whole comic series" placeholder="Search comics by title" error={threadLoadError} disabled={hasPendingMutation} />
                      <button type="submit" disabled={hasPendingMutation || !memberThread} className="self-end rounded-lg bg-violet-500 px-3 py-2 font-bold text-stone-950 disabled:opacity-50">{isBusy ? 'Saving…' : 'Add series'}</button>
                    </form>

                    <form onSubmit={(event) => void addRange(event, group.id)} aria-label={`Add issue range to ${group.name}`} className="grid gap-3 rounded-xl border border-stone-800 bg-stone-950/50 p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
                      <ContinuityThreadSelector threads={threads} value={rangeThread} onChange={(thread) => void selectRangeThread(thread)} label="Comic series for issue range" placeholder="Search comics by title" error={threadLoadError} disabled={hasPendingMutation || isLoadingRangeIssues} />
                      <div className="min-w-0">
                        {rangeThread ? <ContinuityIssueRangeSelector thread={rangeThread} issues={rangeIssues} value={rangeSelection} onChange={setRangeSelection} label={`Issues from ${rangeThread.title}`} isLoading={isLoadingRangeIssues} error={rangeLoadError} disabled={hasPendingMutation} /> : <p className="text-xs text-stone-500">Choose a comic series, then choose the first and last issue by comic issue number.</p>}
                      </div>
                      <button type="submit" disabled={hasPendingMutation || isLoadingRangeIssues || !rangeSelection} className="self-end rounded-lg bg-amber-500 px-3 py-2 font-bold text-stone-950 disabled:opacity-50">{isBusy ? 'Adding…' : 'Add range'}</button>
                    </form>
                    {membershipMessage && <p role="status" className="text-emerald-400">{membershipMessage}</p>}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
