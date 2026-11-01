import { FormEvent, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { Link, useSearchParams } from 'react-router-dom'
import {
  ContinuityIssueRangeSelector,
  ContinuityThreadSelector,
  type SelectedIssueRange,
} from '../components/continuity'
import { type DependencyGroup, type DependencyGroupMember } from '../services/api-dependency-groups'
import type { Issue } from '../types'
import Breadcrumbs from '../components/Breadcrumbs'
import ConfirmDialog from '../components/ConfirmDialog'
import GlossaryLink from '../components/GlossaryLink'
import type { ThreadListItem } from '../types'
import { isString } from '../utils/runtimeChecks'
import {
  useCrossoverGroupsList,
  useAllThreads,
  useCrossoverIssuesForRange,
  useCreateCrossoverGroup,
  useRenameCrossoverGroup,
  useDeleteCrossoverGroup,
  useAddCrossoverMember,
  useAddCrossoverIssueRange,
  useRemoveCrossoverMember,
  type CrossoverApiDeps,
} from '../hooks/useCrossovers'

type PositionedIssue = Issue & { position: number }

function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (isString(detail) && detail.trim()) return detail
  }
  return error instanceof Error && error.message ? error.message : fallback
}

function memberLabel(member: DependencyGroupMember): string {
  const seriesTitle = member.series_title?.trim()
  const seriesName = seriesTitle ? seriesTitle : 'Unavailable comic'
  if (member.issue_id !== null && member.issue_number?.trim()) {
    return `${seriesName} #${member.issue_number}`
  }
  if (member.thread_id !== null) {
    return `${seriesName} (whole series)`
  }
  return 'Unavailable comic'
}

export interface CrossoversPageProps {
  /**
   * Optional service seams. Production callers omit this and use the real
   * services; tests inject faithful in-memory implementations instead of
   * replacing the service modules themselves.
   */
  api?: CrossoverApiDeps
}

export default function CrossoversPage({ api = {} }: CrossoversPageProps) {
  const [searchParams] = useSearchParams()
  const requestedGroupId = searchParams.get('group')
  const startsAtParam = searchParams.get('starts_at')
  const deepLinkAppliedRef = useRef(false)

  // The thread/enumeration selector only renders inside an expanded crossover,
  // so its bounded all-series read waits for an actual expansion. A deep link
  // sets the expansion after the group list resolves, which starts the read.
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const {
    data: groups = [],
    isPending: isLoadingGroups,
    error: groupsError,
    refetch: refetchGroups,
  } = useCrossoverGroupsList(api)

  const {
    data: threads = [],
    isPending: isLoadingThreads,
    error: threadsError,
  } = useAllThreads(api, { enabled: expandedId !== null })

  const createMutation = useCreateCrossoverGroup(api)
  const renameMutation = useRenameCrossoverGroup(api)
  const deleteMutation = useDeleteCrossoverGroup(api)
  const addMemberMutation = useAddCrossoverMember(api)
  const addRangeMutation = useAddCrossoverIssueRange(api)
  const removeMemberMutation = useRemoveCrossoverMember(api)

  const [name, setName] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingName, setEditingName] = useState('')
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [memberThread, setMemberThread] = useState<ThreadListItem | null>(null)
  const [rangeThread, setRangeThread] = useState<ThreadListItem | null>(null)
  const [rangeSelection, setRangeSelection] = useState<SelectedIssueRange | null>(null)
  const [membershipMessage, setMembershipMessage] = useState<string | null>(null)
  const [pendingDeleteGroup, setPendingDeleteGroup] = useState<DependencyGroup | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const {
    data: rangeIssues = [],
    isPending: isPendingRangeIssues,
    error: rangeIssuesError,
  } = useCrossoverIssuesForRange(rangeThread?.id ?? null, api)
  const isLoadingRangeIssues = rangeThread !== null && isPendingRangeIssues

  const threadLoadError = threadsError ? errorMessage(threadsError, 'Unable to load comics for selection.') : null
  const rangeLoadError = rangeIssuesError
    ? errorMessage(rangeIssuesError, 'Unable to load issues for this series.')
    : rangeThread && rangeIssues.length === 0 && !isLoadingRangeIssues
      ? `${rangeThread.title} has no issues to add.`
      : null

  const isAnyMutationPending =
    createMutation.isPending ||
    renameMutation.isPending ||
    deleteMutation.isPending ||
    addMemberMutation.isPending ||
    addRangeMutation.isPending ||
    removeMemberMutation.isPending

  const mutationGuardRef = useRef(false)

  useEffect(() => {
    if (deepLinkAppliedRef.current) return
    if (!requestedGroupId || groups.length === 0) return
    const requestedId = Number(requestedGroupId)
    if (!Number.isInteger(requestedId)) return
    if (!groups.some((group) => group.id === requestedId)) return
    deepLinkAppliedRef.current = true
    setExpandedId(requestedId)
  }, [requestedGroupId, groups])

  const clearRangeState = () => {
    setRangeThread(null)
    setRangeSelection(null)
  }

  const clearMembershipState = () => {
    setMemberThread(null)
    clearRangeState()
    setMembershipMessage(null)
  }

  const toggleExpanded = (groupId: number) => {
    if (mutationGuardRef.current) return
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
    if (mutationGuardRef.current) return
    mutationGuardRef.current = true
    setCreateError(null)
    try {
      await createMutation.mutateAsync(trimmedName)
      setName('')
    } catch (error) {
      setCreateError(errorMessage(error, 'Unable to create crossover.'))
    } finally {
      mutationGuardRef.current = false
    }
  }

  const saveRename = async (groupId: number) => {
    const trimmedName = editingName.trim()
    if (!trimmedName) {
      setMutationError('Enter a crossover name.')
      return
    }
    if (mutationGuardRef.current) return
    mutationGuardRef.current = true
    setMutationError(null)
    try {
      await renameMutation.mutateAsync({ groupId, name: trimmedName })
      setEditingId(null)
      setEditingName('')
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to rename crossover.'))
    } finally {
      mutationGuardRef.current = false
    }
  }

  /**
   * Opens the in-page delete confirmation. The native `window.confirm` this
   * replaces cannot be accepted by browser QA automation, which made it
   * impossible to verify any crossover deletion end to end.
   */
  const requestDeleteGroup = (group: DependencyGroup) => {
    setDeleteError(null)
    setPendingDeleteGroup(group)
  }

  const cancelDeleteGroup = () => {
    setDeleteError(null)
    setPendingDeleteGroup(null)
  }

  const confirmDeleteGroup = async () => {
    const group = pendingDeleteGroup
    if (!group || mutationGuardRef.current) return
    mutationGuardRef.current = true
    setDeleteError(null)
    try {
      await deleteMutation.mutateAsync(group.id)
      if (expandedId === group.id) setExpandedId(null)
      setPendingDeleteGroup(null)
    } catch (error) {
      // Keep the confirmation open so the failure is visible and retryable,
      // matching the queue's destructive dialogs.
      setDeleteError(errorMessage(error, 'Unable to delete crossover.'))
    } finally {
      mutationGuardRef.current = false
    }
  }

  const addThreadMember = async (event: FormEvent<HTMLFormElement>, groupId: number) => {
    event.preventDefault()
    if (!memberThread) {
      setMutationError('Choose a comic series to add.')
      return
    }
    if (mutationGuardRef.current) return
    mutationGuardRef.current = true
    setMutationError(null)
    setMembershipMessage(null)
    try {
      await addMemberMutation.mutateAsync({
        groupId,
        target: { thread_id: memberThread.id },
      })
      const threadTitle = memberThread.title
      setMemberThread(null)
      setMembershipMessage(`${threadTitle} added to crossover as 1 thread member.`)
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to add thread to crossover.'))
    } finally {
      mutationGuardRef.current = false
    }
  }

  const selectRangeThread = (thread: ThreadListItem | null) => {
    setRangeThread(thread)
    setRangeSelection(null)
  }

  const addRange = async (event: FormEvent<HTMLFormElement>, groupId: number) => {
    event.preventDefault()
    if (!rangeThread || !rangeSelection) {
      setMutationError('Choose a series and an inclusive first and last issue.')
      return
    }
    // SAFETY: the range selector only offers position-ordered issues, so each selected issue carries a numeric position.
    const startPosition = (rangeSelection.startIssue as PositionedIssue).position
    // SAFETY: the end issue is subject to the same position-ordered invariant as the start issue.
    const endPosition = (rangeSelection.endIssue as PositionedIssue).position
    if (!Number.isInteger(startPosition) || !Number.isInteger(endPosition) || startPosition < 1 || endPosition < startPosition) {
      setMutationError('Choose a valid issue range in reading order.')
      return
    }
    if (mutationGuardRef.current) return
    mutationGuardRef.current = true
    setMutationError(null)
    setMembershipMessage(null)
    try {
      const result = await addRangeMutation.mutateAsync({
        groupId,
        threadId: rangeThread.id,
        startPosition,
        endPosition,
      })
      const successMessage = `${result.added_issue_ids.length} added, ${result.already_present_issue_ids.length} already present.`
      setMembershipMessage(successMessage)
      clearRangeState()
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to add issue range.'))
    } finally {
      mutationGuardRef.current = false
    }
  }

  const removeMember = async (groupId: number, memberId: number) => {
    if (mutationGuardRef.current) return
    mutationGuardRef.current = true
    setMutationError(null)
    setMembershipMessage(null)
    try {
      await removeMemberMutation.mutateAsync({ groupId, memberId })
      setMembershipMessage('Comic removed from crossover.')
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to remove crossover member.'))
    } finally {
      mutationGuardRef.current = false
    }
  }

  return (
    <section className="space-y-6 pb-28" aria-labelledby="crossovers-heading">
      <Breadcrumbs
        items={[{ label: 'Reading plans', to: '/continuity-plans' }, { label: 'Crossover events' }]}
      />
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <h1 id="crossovers-heading" className="text-2xl font-black text-[var(--theme-text-primary)]">Crossover events</h1>
          <p className="max-w-2xl text-sm text-[var(--theme-text-muted)]">
            Labels for connected comics so you can recognize a story across series. Membership is not a
            reading order — progress, next unread issues, and blockers live on a{' '}
            <Link to="/continuity-plans" className="font-bold text-[var(--theme-continuity-accent)] underline underline-offset-2">
              Reading Plan
            </Link>
            .{' '}
            <GlossaryLink id="crossover">What is a crossover?</GlossaryLink>
          </p>
        </div>
      </header>

      <details className="max-w-xl rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4">
        <summary className="min-h-11 cursor-pointer text-sm font-bold text-[var(--theme-text-primary)]">
          Manage event labels
        </summary>
        <form onSubmit={createGroup} className="mt-3 space-y-2" aria-label="Create crossover">
          <label htmlFor="crossover-name" className="block text-sm font-medium text-[var(--theme-text-primary)]">New crossover</label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input id="crossover-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={200} className="min-w-0 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2.5 text-[var(--theme-text-primary)]" placeholder="Age of Apocalypse" disabled={createMutation.isPending || isLoadingGroups} />
            <button type="submit" disabled={createMutation.isPending || isLoadingGroups} className="rounded-xl bg-[var(--theme-primary-action)] px-4 py-2.5 font-bold text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50">{createMutation.isPending ? 'Creating…' : 'Create crossover'}</button>
          </div>
          {createError && <p role="alert" className="text-sm text-[var(--theme-danger)]">{createError}</p>}
        </form>
      </details>

      {mutationError && <p role="alert" className="rounded-xl border border-[var(--theme-danger)] bg-[var(--theme-danger)]/10 p-3 text-sm text-[var(--theme-danger)]">{mutationError}</p>}
      {isLoadingGroups ? <p role="status">Loading crossovers…</p> : groupsError ? <div role="alert"><p>{errorMessage(groupsError, 'Unable to load crossovers.')}</p><button type="button" onClick={() => void refetchGroups()}>Try again</button></div> : groups.length === 0 ? <p className="max-w-xl text-sm text-[var(--theme-text-dim)]">No crossovers yet. Create your first one above to get started.</p> : (
        <ul className="grid gap-3" aria-label="Your crossovers">
          {groups.map((group) => {
            const isEditing = editingId === group.id
            const isExpanded = expandedId === group.id
            return (
              <li key={group.id} className="rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4">
                {isEditing ? (
                  <div className="flex gap-2">
                    <input aria-label={`Rename ${group.name}`} value={editingName} onChange={(event) => setEditingName(event.target.value)} disabled={isAnyMutationPending} className="min-w-0 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2" />
                    <button type="button" onClick={() => void saveRename(group.id)} disabled={isAnyMutationPending}>Save</button>
                    <button type="button" onClick={() => setEditingId(null)} disabled={isAnyMutationPending}>Cancel</button>
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-3">
                    <button type="button" onClick={() => toggleExpanded(group.id)} disabled={isAnyMutationPending} aria-expanded={isExpanded} className="min-w-0 text-left">
                      <span className="block text-lg font-black text-[var(--theme-text-primary)]">{group.name}</span>{" "}
                      <span className="text-sm text-[var(--theme-text-dim)]">
                        {group.memberships.length} {group.memberships.length === 1 ? 'member' : 'members'}
                        {(group.total_issues ?? 0) > 0 && (
                          <span className="ml-2">
                            Progress: {group.read_issues}/{group.total_issues} ({group.reading_progress})
                          </span>
                        )}
                      </span>
                    </button>
                    <div className="flex gap-2">
                      <Link to={`/crossovers/${group.id}`} className="rounded-lg bg-[var(--theme-primary-action)] px-3 py-1 text-sm font-bold text-stone-950 hover:bg-[var(--theme-primary-action-hover)]">View</Link>
                      {isExpanded && (
                        <>
                          <button type="button" onClick={() => { setEditingId(group.id); setEditingName(group.name) }} disabled={isAnyMutationPending}>Rename</button>
                          <button type="button" onClick={() => requestDeleteGroup(group)} disabled={isAnyMutationPending}>Delete</button>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {isExpanded && !isEditing && (
                  <div className="mt-4 space-y-4 border-t border-[var(--theme-border)] pt-4 text-sm text-[var(--theme-text-muted)]">
                    {requestedGroupId === String(group.id) && startsAtParam && (
                      <p role="status" className="text-xs font-bold text-[var(--theme-continuity-accent)]">Starts at #{startsAtParam}</p>
                    )}
                    {group.memberships.length === 0 ? <p>This crossover has no comics yet.</p> : (
                      <ul className="grid gap-2" aria-label={`${group.name} members`}>
                        {group.memberships.map((member) => {
                          const label = memberLabel(member)
                          return (
                            <li key={member.id} className="flex items-center justify-between gap-3 rounded-xl border border-[var(--theme-border)] px-3 py-2">
                              <span>{label}</span>
                              <button type="button" onClick={() => void removeMember(group.id, member.id)} disabled={isAnyMutationPending} aria-label={`Remove ${label} from ${group.name}`}>Remove</button>
                            </li>
                          )
                        })}
                      </ul>
                    )}

                    <form onSubmit={(event) => void addThreadMember(event, group.id)} aria-label={`Add thread to ${group.name}`} className="grid gap-2 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 sm:grid-cols-[1fr_auto]">
                      <div className="min-w-0">
                        <ContinuityThreadSelector threads={threads} value={memberThread} onChange={setMemberThread} label="Current thread of series" placeholder="Search comics by title" isLoading={isLoadingThreads} error={threadLoadError} disabled={isAnyMutationPending} />
                        <p className="mt-1 text-xs text-[var(--theme-text-dim)]">Adds one thread membership for the series. Use the issue range form below to add specific issues.</p>
                      </div>
                      <button type="submit" disabled={isAnyMutationPending || !memberThread} className="self-end rounded-lg bg-[var(--theme-primary-action)] px-3 py-2 font-bold text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50">{addMemberMutation.isPending ? 'Saving…' : 'Add thread'}</button>
                    </form>

                    <form onSubmit={(event) => void addRange(event, group.id)} aria-label={`Add issue range to ${group.name}`} className="grid gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
                      <ContinuityThreadSelector threads={threads} value={rangeThread} onChange={(thread) => selectRangeThread(thread)} label="Comic series for issue range" placeholder="Search comics by title" isLoading={isLoadingThreads} error={threadLoadError} disabled={isAnyMutationPending || isLoadingRangeIssues} />
                      <div className="min-w-0">
                        {rangeThread ? <ContinuityIssueRangeSelector thread={rangeThread} issues={rangeIssues} value={rangeSelection} onChange={setRangeSelection} label={`Issues from ${rangeThread.title}`} isLoading={isLoadingRangeIssues} error={rangeLoadError} disabled={isAnyMutationPending} /> : <p className="text-xs text-[var(--theme-text-dim)]">Choose a comic series, then choose the first and last issue by comic issue number.</p>}
                      </div>
                      <button type="submit" disabled={isAnyMutationPending || isLoadingRangeIssues || !rangeSelection} className="self-end rounded-lg bg-[var(--theme-primary-action)] px-3 py-2 font-bold text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50">{addRangeMutation.isPending ? 'Adding…' : 'Add range'}</button>
                    </form>
                    {membershipMessage && <p role="status" className="text-[var(--theme-personal-accent)]">{membershipMessage}</p>}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <ConfirmDialog
        isOpen={pendingDeleteGroup !== null}
        title="Delete Crossover"
        isPending={deleteMutation.isPending}
        error={deleteError}
        confirmLabel="Delete Crossover"
        pendingLabel="Deleting…"
        onConfirm={() => void confirmDeleteGroup()}
        onCancel={cancelDeleteGroup}
        testId="delete-crossover-dialog"
      >
        <p className="text-sm text-[var(--theme-text-muted)]">
          Permanently delete{' '}
          <span className="font-bold text-[var(--theme-text-primary)]">{pendingDeleteGroup?.name}</span>?
        </p>
        <p className="text-sm text-[var(--theme-text-muted)]">
          This removes the crossover label together with its comic memberships. The comics
          themselves and their reading progress are not deleted.
        </p>
      </ConfirmDialog>
    </section>
  )
}
