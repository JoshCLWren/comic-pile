import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Modal from './Modal'
import { threadsApi } from '../services/api-threads'
import { customCBLApi } from '../services/api-custom-cbl'
import { useCrossoverGroups } from '../hooks/useCrossoverGroups'
import {
  invalidateAfterQueueMutation,
  invalidateCrossoverGroupsForThreads,
  invalidateReadingPlanReader,
} from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import { getApiErrorDetail } from '../utils/apiError' 

type SourceKind = 'reading_list' | 'reading_plan' | 'crossover'

interface MemberThread {
  id: number
  title: string
}

interface ContainerQueueActionsProps {
  sourceKind: SourceKind
  sourceId: number
  sourceName: string
  memberThreads: MemberThread[]
}

const BULK_MUTATION_CHUNK_SIZE = 1000

function uniqueMembers(memberThreads: MemberThread[]): MemberThread[] {
  const byId = new Map<number, MemberThread>()
  for (const thread of memberThreads) {
    if (thread.id > 0 && !byId.has(thread.id)) byId.set(thread.id, thread)
  }
  return Array.from(byId.values())
}

function chunkIds(ids: number[], size = BULK_MUTATION_CHUNK_SIZE): number[][] {
  const chunks: number[][] = []
  for (let index = 0; index < ids.length; index += size) {
    chunks.push(ids.slice(index, index + size))
  }
  return chunks
}

export default function ContainerQueueActions({
  sourceKind,
  sourceId,
  sourceName,
  memberThreads,
}: ContainerQueueActionsProps) {
  const queryClient = useQueryClient()
  const [removeOpen, setRemoveOpen] = useState(false)
  const [restoreOpen, setRestoreOpen] = useState(false)
  const [keptIds, setKeptIds] = useState<Set<number>>(new Set())
  const [actionError, setActionError] = useState<string | null>(null)

  const members = useMemo(() => uniqueMembers(memberThreads), [memberThreads])
  const memberIds = useMemo(() => members.map((thread) => thread.id), [members])

  // Resolve excluded/active status for every container member with a scoped lookup.
  const memberStatusQuery = useQuery({
    queryKey: queryKeys.excluded.memberStatus(memberIds),
    queryFn: async () => {
      const result = await threadsApi.checkExcludedStatus(memberIds)
      return {
        excluded_thread_ids: result.excluded_thread_ids.filter((id) => id > 0),
        active_thread_ids: (result.active_thread_ids ?? []).filter((id) => id > 0),
      }
    },
    enabled: memberIds.length > 0,
    staleTime: 30_000,
  })

  const excludedIdSet = useMemo(
    () => new Set(memberStatusQuery.data?.excluded_thread_ids ?? []),
    [memberStatusQuery.data],
  )
  const activeIdSet = useMemo(
    () => new Set(memberStatusQuery.data?.active_thread_ids ?? []),
    [memberStatusQuery.data],
  )

  // Members not currently excluded and currently active in the queue are removable.
  const removable = useMemo(
    () => members.filter((thread) => activeIdSet.has(thread.id) && !excludedIdSet.has(thread.id)),
    [members, activeIdSet, excludedIdSet],
  )
  // Members currently excluded are candidates for container-level restore.
  const restorable = useMemo(
    () => members.filter((thread) => excludedIdSet.has(thread.id)),
    [members, excludedIdSet],
  )

  // Batched, scoped overlap checks: only run while the remove dialog is open.
  const excludeListId = sourceKind === 'reading_list' ? sourceId : undefined
  const otherListsQuery = useQuery({
    queryKey: queryKeys.customCBLs.threadMemberships(memberIds, excludeListId),
    queryFn: async () => {
      const chunkSize = 1000
      const chunks: number[][] = []
      for (let index = 0; index < memberIds.length; index += chunkSize) {
        chunks.push(memberIds.slice(index, index + chunkSize))
      }
      const inOtherList = new Set<number>()
      const concurrency = 4
      for (let index = 0; index < chunks.length; index += concurrency) {
        const batch = chunks.slice(index, index + concurrency)
        const results = await Promise.all(
          batch.map((chunk) => customCBLApi.checkThreadMemberships(chunk, excludeListId)),
        )
        for (const result of results) {
          for (const id of result.thread_ids) inOtherList.add(id)
        }
      }
      return inOtherList
    },
    enabled: removeOpen && memberIds.length > 0,
    staleTime: 0,
    retry: 1,
    retryDelay: 0,
  })

  const {
    groupsByThreadId,
    isPending: otherCrossoversPending,
    error: otherCrossoversError,
  } = useCrossoverGroups(removeOpen ? memberIds : [])

  const otherCrossoversSet = useMemo(() => {
    const inOtherCrossover = new Set<number>()
    for (const [threadId, groups] of Object.entries(groupsByThreadId)) {
      const threadNum = Number(threadId)
      if (groups.some((group) => !(sourceKind === 'crossover' && group.id === sourceId))) {
        inOtherCrossover.add(threadNum)
      }
    }
    return inOtherCrossover
  }, [groupsByThreadId, sourceKind, sourceId])

  const inAnotherActiveList = useMemo(() => {
    const set = new Set<number>()
    for (const id of otherListsQuery.data ?? []) set.add(id)
    for (const id of otherCrossoversSet) set.add(id)
    return set
  }, [otherListsQuery.data, otherCrossoversSet])

  const overlapChecksPending = otherListsQuery.isPending || otherCrossoversPending
  const overlapChecksError = otherListsQuery.isError || otherCrossoversError != null
  const overlapChecksErrored = removeOpen && memberIds.length > 0 && !overlapChecksPending && overlapChecksError

  const invalidateContainerQueries = async () => {
    await invalidateAfterQueueMutation(queryClient)
    if (sourceKind === 'reading_plan') {
      await invalidateReadingPlanReader(queryClient, sourceId)
    }
  }

  const removeMutation = useMutation({
    mutationFn: async (threadIds: number[]) => {
      for (const chunk of chunkIds(threadIds)) {
        await threadsApi.bulkExclude({
          thread_ids: chunk,
          source: { kind: sourceKind, id: sourceId, name: sourceName },
        })
      }
    },
    onSuccess: async () => {
      await invalidateContainerQueries()
      setRemoveOpen(false)
      setKeptIds(new Set())
      setActionError(null)
    },
    onError: (error) => {
      setActionError(getApiErrorDetail(error) || 'Could not remove these series from the queue.')
    },
  })

  const restoreMutation = useMutation({
    mutationFn: async (threadIds: number[]) => {
      for (const chunk of chunkIds(threadIds)) {
        await threadsApi.bulkRestore(chunk)
      }
    },
    onSuccess: async () => {
      await invalidateContainerQueries()
      setRestoreOpen(false)
      setActionError(null)
    },
    onError: (error) => {
      setActionError(getApiErrorDetail(error) || 'Could not restore these series to the queue.')
    },
  })

  if (members.length === 0) return null

  const selectedForRemoval = removable.filter((thread) => !keptIds.has(thread.id))
  const isBusy = removeMutation.isPending || restoreMutation.isPending
  const keepToggleVisible = !overlapChecksPending && !overlapChecksError && inAnotherActiveList.size > 0
  const canConfirmRemove =
    !isBusy &&
    selectedForRemoval.length > 0 &&
    !overlapChecksPending &&
    !overlapChecksError

  const openRemove = () => {
    setActionError(null)
    setKeptIds(new Set())
    setRemoveOpen(true)
  }

  const openRestore = () => {
    setActionError(null)
    setRestoreOpen(true)
  }

  const toggleKeep = (id: number) => {
    setKeptIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const retryOverlapChecks = () => {
    void otherListsQuery.refetch()
    void invalidateCrossoverGroupsForThreads(queryClient, memberIds)
  }

  const memberStatusPending = memberStatusQuery.isPending
  const memberStatusError = memberStatusQuery.isError

  return (
    <section
      aria-label="Queue actions for this collection"
      className="surface-panel rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-bold text-[var(--theme-text-primary)]">Queue</h2>
          <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
            Remove or restore every series in this collection in one action. Reading progress and membership stay intact.
          </p>
          {memberStatusError && (
            <p role="alert" className="mt-2 text-sm text-[var(--theme-error)]">
              Could not determine which series are currently in the Queue.{' '}
              <button
                type="button"
                className="underline"
                onClick={() => {
                  void memberStatusQuery.refetch()
                }}
              >
                Try again
              </button>
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={openRemove}
            disabled={isBusy || memberStatusPending || memberStatusError || removable.length === 0}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
          >
            Remove all series from Queue
          </button>
          <button
            type="button"
            onClick={openRestore}
            disabled={isBusy || memberStatusPending || memberStatusError || restorable.length === 0}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
          >
            Restore all to Queue
          </button>
        </div>
      </div>

      <Modal
        isOpen={removeOpen}
        title="Remove all series from Queue"
        onClose={() => !isBusy && setRemoveOpen(false)}
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            These series will be removed from your Queue as one group. Reads, ratings, and list membership are kept and this can be undone.
          </p>
          {overlapChecksPending && (
            <p className="text-sm text-[var(--theme-text-dim)]">Checking for series in other active lists…</p>
          )}
          {overlapChecksErrored && (
            <p role="alert" className="text-sm text-[var(--theme-error)]">
              Could not check whether these series belong to other active lists.{' '}
              <button type="button" className="underline" onClick={retryOverlapChecks}>
                Try again
              </button>
            </p>
          )}
          {removable.length === 0 ? (
            <p className="text-sm text-[var(--theme-text-dim)]">No series from this collection are currently in your Queue.</p>
          ) : (
            <>
              {keepToggleVisible && (
                <p className="text-xs text-[var(--theme-text-dim)]">
                  Series also in another active list can be kept in the Queue.
                </p>
              )}
              <ul className="max-h-64 space-y-2 overflow-y-auto" aria-label="Series to remove">
                {removable.map((thread) => {
                  const alsoInOther = inAnotherActiveList.has(thread.id)
                  const kept = keptIds.has(thread.id)
                  return (
                    <li
                      key={thread.id}
                      className="flex items-center justify-between gap-3 rounded-xl border border-[var(--theme-border)] px-3 py-2"
                    >
                      <span className="min-w-0 truncate text-sm font-medium text-[var(--theme-text-primary)]">
                        {thread.title}
                      </span>
                      {alsoInOther && !overlapChecksPending && !overlapChecksError ? (
                        <label className="flex shrink-0 items-center gap-2 text-xs text-[var(--theme-text-muted)]">
                          <input
                            type="checkbox"
                            checked={kept}
                            onChange={() => toggleKeep(thread.id)}
                          />
                          Keep in Queue
                        </label>
                      ) : null}
                    </li>
                  )
                })}
              </ul>
              <p className="text-xs text-[var(--theme-text-dim)]">
                {selectedForRemoval.length} of {removable.length} series will be removed.
              </p>
            </>
          )}
          {actionError && (
            <p role="alert" className="text-sm text-[var(--theme-error)]">
              {actionError}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => setRemoveOpen(false)}
              disabled={isBusy}
              className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => removeMutation.mutate(selectedForRemoval.map((thread) => thread.id))}
              disabled={!canConfirmRemove}
              className="min-h-11 rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50"
            >
              {isBusy ? 'Removing…' : 'Remove from Queue'}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={restoreOpen}
        title="Restore all to Queue"
        onClose={() => !isBusy && setRestoreOpen(false)}
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Restore every excluded series from this collection to your Queue.
          </p>
          {restorable.length === 0 ? (
            <p className="text-sm text-[var(--theme-text-dim)]">No excluded series from this collection to restore.</p>
          ) : (
            <ul className="max-h-64 space-y-2 overflow-y-auto" aria-label="Series to restore">
              {restorable.map((thread) => (
                <li
                  key={thread.id}
                  className="rounded-xl border border-[var(--theme-border)] px-3 py-2 text-sm text-[var(--theme-text-primary)]"
                >
                  {thread.title}
                </li>
              ))}
            </ul>
          )}
          {actionError && (
            <p role="alert" className="text-sm text-[var(--theme-error)]">
              {actionError}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => setRestoreOpen(false)}
              disabled={isBusy}
              className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => restoreMutation.mutate(restorable.map((thread) => thread.id))}
              disabled={isBusy || restorable.length === 0}
              className="min-h-11 rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50"
            >
              {isBusy ? 'Restoring…' : 'Restore to Queue'}
            </button>
          </div>
        </div>
      </Modal>
    </section>
  )
}
