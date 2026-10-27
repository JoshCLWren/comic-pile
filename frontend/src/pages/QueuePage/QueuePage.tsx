import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useRollNudge } from './useRollNudge'
import LoadingSpinner from '../../components/LoadingSpinner'
import { useInfiniteScroll } from '../../hooks/useInfiniteScroll'
import { useCreateThread, useReactivateThread, useUpdateThread } from '../../hooks/useThread'
import { useExcludedThreads, useMoveToPosition, useQueueThreads, useRestoreThread, useShuffleQueue } from '../../hooks/useQueue'
import { useSession } from '../../hooks/useSession'
import { useToast } from '../../contexts/useToast'
import { invalidateAfterIssueEdit, invalidateAfterQueueMutation } from '../../query/cacheEffects'
import { queryClient } from '../../query/queryClient'
import { PositionMenuProvider } from '../../contexts/PositionMenuProvider'
import type { ThreadListItem, ThreadCreatePayload, ThreadUpdatePayload } from '../../types'
import CompletedThreadsSection from './CompletedThreadsSection'
import ExcludedThreadsSection from './ExcludedThreadsSection'
import { QueueControls } from './QueueControls'
import { QueueList } from './QueueList'
import { QueueBoundaryNotice } from './QueueBoundaryNotice'
import { QueueModals } from './QueueModals'
import DeleteThreadDialog from './DeleteThreadDialog'
import RemoveThreadDialog from './RemoveThreadDialog'
import ShuffleQueueDialog from './ShuffleQueueDialog'
import QueueBulkMapSeriesDialog from '../../components/QueueBulkMapSeriesDialog'
import { useQueueBulkMapping } from './useQueueBulkMapping'
import { useQueueFilters, type QueueSortBy } from './useQueueFilters'
import { useQueueListLoading } from './useQueueListLoading'
import { useQueueThreadActions } from './useQueueThreadActions'
import { useQueueThreadCards } from './useQueueThreadCards'
import { useQueueModals as useQueueModalsHook } from './useQueueModals'

/**
 * Route entry for the Queue page. The component composes the focused
 * retained feature modules (`QueueControls`, `QueueList`, `QueueModals`,
 * `CompletedThreadsSection`, `ExcludedThreadsSection`, and the row renderer
 * `useQueueThreadCards`) plus the page-level navigation/error boundary
 * concerns. Data ownership stays in the page so a second cache layer is
 * never introduced.
 */
export default function QueuePage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [sortBy, setSortBy] = useState<QueueSortBy>('position')
  const [searchQuery, setSearchQuery] = useState('')
  const isSearching = searchQuery.trim() !== ''

  const queueLoader = useQueueThreads(searchQuery, sortBy)
  const {
    data: threads,
    isPending,
    isError,
    nextPageToken,
    loadMore,
    activeCount,
  } = queueLoader

  // Series that show the per-row `Map series` repair action (everything except
  // fully mapped or non-issue-tracked rows) are the bulk action's scope, and an
  // open run keeps reading the cursor so the batch covers the whole queue.
  const bulkMapping = useQueueBulkMapping(queueLoader)
  const { data: session, refetch: refetchSession } = useSession()
  const createMutation = useCreateThread()
  const updateMutation = useUpdateThread()
  const reactivateMutation = useReactivateThread()
  const moveToPositionMutation = useMoveToPosition()
  const shuffleQueueMutation = useShuffleQueue()
  // Excluded rows have a separate bounded read because the active queue omits them.
  const { threads: excludedThreads } = useExcludedThreads(true)
  const restoreMutation = useRestoreThread()
  const [restoreError, setRestoreError] = useState<string | null>(null)

  const handleRestore = useCallback(
    async (threadId: number) => {
      setRestoreError(null)
      try {
        await restoreMutation.mutate(threadId)
      } catch {
        setRestoreError(
          'Could not restore that series to the queue. Check your connection and try again.',
        )
      }
    },
    [restoreMutation],
  )

  const { activeThreads, completedThreads, filteredThreads } = useQueueFilters(
    threads,
    sortBy,
    searchQuery,
  )
  const authoritativeActiveCount = activeCount ?? activeThreads.length
  // True while the Queue list is still fetching; the list uses it to tell
  // "still fetching" apart from a settled zero-match (#3912).
  const queueListLoading = useQueueListLoading()

  const navigateToRoll = useCallback(
    (_thread: ThreadListItem, response: unknown) => {
      navigate('/', { state: { rollResponse: response } })
    },
    [navigate],
  )
  const actions = useQueueThreadActions({
    navigateToRoll,
    refetchSession,
  })

  const submitCreate = useCallback(
    (input: ThreadCreatePayload) =>
      // SAFETY: useCreateThread exposes mutateAsync, so this resolves to the created thread record
      createMutation.mutate(input) as Promise<{ id?: number }>,
    [createMutation],
  )
  const submitEdit = useCallback(
    (input: { id: number; data: ThreadUpdatePayload }) => updateMutation.mutate(input),
    [updateMutation],
  )
  const submitReactivate = useCallback(
    (input: { thread_id: number; issues_to_add: number }) => reactivateMutation.mutate(input),
    [reactivateMutation],
  )

  const rollNudge = useRollNudge()

  const modals = useQueueModalsHook({
    threads,
    onCreated: rollNudge.onCreated,
    // Refetch so a confirmed edit reconciles the Queue immediately: a finished
    // series leaves the active list and shifted rows keep their rank (#4181).
    onUpdated: queueLoader.refetch,
    onReactivated: async () => {},
    refetchSession: async () => {
      await refetchSession()
    },
    submitCreate,
    submitEdit,
    submitReactivate,
    isPendingCreate: createMutation.isPending,
    isPendingEdit: updateMutation.isPending,
    showRollNudge: rollNudge.showRollNudge,
    onDismissRollNudge: rollNudge.onDismissRollNudge,
    onRollNudgeNavigate: rollNudge.onRollNudgeNavigate,
  })

  const handleIssueChanged = useCallback(() => {
    if (modals.editingThread) void invalidateAfterIssueEdit(queryClient, modals.editingThread.id)
  }, [modals.editingThread])

  // Row rendering (blocking, crossovers, snooze state) lives in the extracted
  // module so this page stays a thin route composition.
  const { renderThreadCard, boundaryError, retryBoundaries } = useQueueThreadCards({
    actions,
    activeThreads,
    modals,
    session,
    positionActionsAvailable: sortBy === 'position',
  })

  const handleRepositionConfirm = useCallback(
    async (targetPosition: number) => {
      if (!modals.repositioningThread) return
      if (targetPosition < 1 || targetPosition > authoritativeActiveCount) {
        showToast('Invalid position specified. Please choose a valid position.', 'error')
        return
      }
      try {
        await moveToPositionMutation.mutate({
          id: modals.repositioningThread.id,
          position: targetPosition,
        })
        modals.closeRepositionModal()
      } catch {
        modals.closeRepositionModal()
        showToast('Failed to reposition thread. Please try again.', 'error')
      }
    },
    [modals, moveToPositionMutation, authoritativeActiveCount, showToast],
  )

  const handleLoadMore = useCallback(() => void loadMore().catch(() => undefined), [loadMore])

  const { sentinelRef } = useInfiniteScroll({
    onLoadMore: handleLoadMore,
    hasMore: !!nextPageToken,
    isLoading: isPending,
  })

  const mobileAddEnabled = !modals.isAnyModalOpen
  const shuffleDisabled = authoritativeActiveCount < 2

  if (isPending && !threads?.length) {
    return <LoadingSpinner fullScreen />
  }

  return (
    <PositionMenuProvider>
      <div className="space-y-6 md:space-y-10 pb-[calc(10rem_+_env(safe-area-inset-bottom))] md:pb-10">
        <QueueControls
          activeCount={authoritativeActiveCount}
          shuffleDisabled={shuffleDisabled}
          shufflePending={shuffleQueueMutation.isPending}
          onShuffle={actions.requestShuffle}
          onCreateThread={modals.showCreateModal}
          onAddFromComicVine={modals.showAddSeriesComicVineModal}
          onBulkMapSeries={bulkMapping.openBulkMap}
          bulkMapDisabled={bulkMapping.bulkMapDisabled}
          sortBy={sortBy}
          onSortChange={setSortBy}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />

        {mobileAddEnabled && (
          <button
            type="button"
            onClick={modals.showCreateModal}
            className="md:hidden fixed bottom-[calc(6rem_+_env(safe-area-inset-bottom))] right-4 h-14 w-14 rounded-full bg-[var(--theme-primary-action)] text-stone-950 font-black text-3xl shadow-[0_4px_20px_color-mix(in_srgb,var(--theme-primary-action)_40%,transparent)] z-50 flex items-center justify-center hover:bg-[var(--theme-primary-action-hover)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--theme-bg-page)]"
            aria-label="Add Series"
          >
            +
          </button>
        )}

        <QueueBoundaryNotice isError={boundaryError} onRetry={retryBoundaries} />

        <QueueList
          activeThreads={activeThreads}
          filteredThreads={filteredThreads}
          reorderError={actions.reorderError}
          renderItem={renderThreadCard}
          isSearching={isSearching}
          sentinelRef={sentinelRef}
          hasNextPage={!!nextPageToken}
          isLoading={queueListLoading}
          onAddSeries={modals.showCreateModal}
        />

        <CompletedThreadsSection
          threads={completedThreads}
          onReactivate={modals.openReactivateModal}
        />

        <ExcludedThreadsSection
          threads={excludedThreads}
          isRestoring={restoreMutation.isPending}
          error={restoreError}
          onRestore={handleRestore}
        />

        {isError && threads !== null && (
          <div role="alert" className="text-sm text-red-400 text-center px-2 space-y-2">
            <p>Couldn&apos;t load the next batch of series.</p>
            {nextPageToken && (
              <button
                type="button"
                onClick={handleLoadMore}
                className="mx-auto block rounded-md bg-amber-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-amber-500 transition-colors"
                data-testid="queue-load-more-retry"
              >
                Try again
              </button>
            )}
          </div>
        )}

        {isPending && threads !== null && threads.length > 0 && (
          <div className="px-2 flex justify-center py-4" data-testid="queue-loading-more">
            <LoadingSpinner />
          </div>
        )}

        <QueueModals
          openModal={modals.openModal}
          createForm={modals.createForm}
          editForm={modals.editForm}
          createError={modals.createError}
          setCreateForm={modals.setCreateForm}
          setEditForm={modals.setEditForm}
          issuePreview={modals.issuePreview}
          issueParseError={modals.issueParseError}
          issueParseWarnings={modals.issueParseWarnings}
          issueParseBreakdown={modals.issueParseBreakdown}
          editingThread={modals.editingThread}
          repositioningThread={modals.repositioningThread}
          dependencyThread={modals.dependencyThread}
          threadToMigrate={modals.threadToMigrate}
          showMigrationDialog={modals.showMigrationDialog}
          reactivateThreadId={modals.reactivateThreadId}
          setReactivateThreadId={modals.setReactivateThreadId}
          issuesToAdd={modals.issuesToAdd}
          setIssuesToAdd={modals.setIssuesToAdd}
          activeThreads={activeThreads}
          completedThreads={completedThreads}
          queueSize={authoritativeActiveCount}
          onCreateSubmit={modals.handleCreateSubmit}
          onEditSubmit={modals.handleEditSubmit}
          onReactivateSubmit={modals.handleReactivateSubmit}
          onRepositionConfirm={handleRepositionConfirm}
          onDependencyChanged={() => invalidateAfterQueueMutation(queryClient)}
          onCloseCreate={modals.closeCreateModal}
          onCloseEdit={modals.closeEditModal}
          onCloseReactivate={modals.closeReactivateModal}
          onCloseReposition={modals.closeRepositionModal}
          onCloseDependency={modals.closeDependenciesModal}
          onMigrationComplete={modals.handleMigrationComplete}
          onMigrationSkip={modals.handleMigrationSkip}
          onCloseMigration={modals.closeMigrationDialog}
          onOpenMigrationDialog={modals.openMigrationDialog}
          onOpenDependencies={modals.editingThread ? () => modals.openDependenciesModal(modals.editingThread!) : undefined}
          onIssueChanged={handleIssueChanged}
          onIssuesLoaded={modals.markIssuesLoaded}
          isPendingCreate={modals.isPendingCreate}
          isPendingEdit={modals.isPendingEdit}
          isPendingReactivate={reactivateMutation.isPending}
          isIssuesLoading={modals.isIssuesLoading}
          showRollNudge={modals.showRollNudge}
          onDismissRollNudge={modals.dismissRollNudge}
          onRollNudgeNavigate={modals.rollNudgeNavigate}
          onCloseAddSeriesComicVine={modals.closeAddSeriesComicVineModal}
        />

        <DeleteThreadDialog
          thread={actions.pendingDeleteThread}
          isPending={actions.isDeletePending}
          error={actions.deleteError}
          onConfirm={() => void actions.confirmDelete()}
          onCancel={actions.cancelDelete}
        />

        <RemoveThreadDialog
          thread={actions.pendingRemoveThread}
          isPending={actions.isRemovePending}
          error={actions.removeError}
          onConfirm={() => void actions.confirmRemove()}
          onCancel={actions.cancelRemove}
        />

        <ShuffleQueueDialog
          isOpen={actions.isShuffleConfirmOpen}
          seriesCount={authoritativeActiveCount}
          isPending={shuffleQueueMutation.isPending}
          error={actions.shuffleError}
          onConfirm={() => void actions.confirmShuffle()}
          onCancel={actions.cancelShuffle}
        />

        <QueueBulkMapSeriesDialog {...bulkMapping.dialogProps} />
      </div>
    </PositionMenuProvider>
  )
}
