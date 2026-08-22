import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import LoadingSpinner from '../../components/LoadingSpinner'
import { useInfiniteScroll } from '../../hooks/useInfiniteScroll'
import { useCreateThread, useReactivateThread, useUpdateThread } from '../../hooks/useThread'
import { useMoveToPosition, useQueueThreads, useShuffleQueue } from '../../hooks/useQueue'
import { useSession } from '../../hooks/useSession'
import { invalidateAfterQueueMutation } from '../../query/cacheEffects'
import { queryClient } from '../../query/queryClient'
import { PositionMenuProvider } from '../../contexts/PositionMenuProvider'
import type { Thread } from '../../types'
import QueueThreadCard from './QueueThreadCard'
import CompletedThreadsSection from './CompletedThreadsSection'
import { QueueControls } from './QueueControls'
import { QueueList } from './QueueList'
import { QueueModals } from './QueueModals'
import { useQueueFilters, type QueueSortBy } from './useQueueFilters'
import { useQueueThreadActions } from './useQueueThreadActions'
import { useQueueModals as useQueueModalsHook } from './useQueueModals'

/**
 * Route entry for the Queue page. The component composes the focused
 * retained feature modules (`QueueControls`, `QueueList`, `QueueModals`,
 * `CompletedThreadsSection`) plus the page-level navigation/error boundary
 * concerns. Data ownership stays in the page so a second cache layer is
 * never introduced.
 */
export default function QueuePage() {
  const navigate = useNavigate()
  const [sortBy, setSortBy] = useState<QueueSortBy>('position')
  const [searchQuery, setSearchQuery] = useState('')
  const isSearching = searchQuery.trim() !== ''

  const {
    data: threads,
    isPending,
    isError,
    nextPageToken,
    loadMore,
  } = useQueueThreads(searchQuery, sortBy)
  const { data: session, refetch: refetchSession } = useSession()
  const createMutation = useCreateThread()
  const updateMutation = useUpdateThread()
  const reactivateMutation = useReactivateThread()
  const moveToPositionMutation = useMoveToPosition()
  const shuffleQueueMutation = useShuffleQueue()

  const { activeThreads, completedThreads, filteredThreads } = useQueueFilters(
    threads,
    sortBy,
  )

  const navigateToRoll = useCallback(
    (_thread: Thread, response: unknown) => {
      navigate('/', { state: { rollResponse: response } })
    },
    [navigate],
  )

  const actions = useQueueThreadActions({
    navigateToRoll,
    refetchSession: () => refetchSession(),
  })

  const submitCreate = useCallback(
    (input: { title: string; format: string; issues_remaining: number; notes: string | null }) =>
      createMutation.mutate(input) as Promise<{ id?: number }>,
    [createMutation],
  )
  const submitEdit = useCallback(
    (input: {
      id: number
      data: { title: string; format: string; notes: string | null; issues_remaining?: number }
    }) => updateMutation.mutate(input),
    [updateMutation],
  )
  const submitReactivate = useCallback(
    (input: { thread_id: number; issues_to_add: number }) => reactivateMutation.mutate(input),
    [reactivateMutation],
  )

  const modals = useQueueModalsHook({
    threads,
    onCreated: () => {},
    onUpdated: () => {},
    onReactivated: () => {},
    refetchSession: () => refetchSession(),
    submitCreate,
    submitEdit,
    submitReactivate,
    isPendingCreate: createMutation.isPending,
    isPendingEdit: updateMutation.isPending,
  })

  const handleRepositionConfirm = useCallback(
    async (targetPosition: number) => {
      if (!modals.repositioningThread) return
      if (targetPosition < 1 || targetPosition > activeThreads.length) {
        window.alert('Invalid position specified. Please choose a valid position.')
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
        window.alert('Failed to reposition thread. Please try again.')
      }
    },
    [modals, moveToPositionMutation, activeThreads.length],
  )

  const renderThreadCard = useCallback(
    (thread: Thread, index: number) => {
      const isDragOver = actions.dragOverThreadId === thread.id
      const isBlocked = thread.is_blocked
      const blockingReasons: string[] = thread.blocking_reasons ?? []
      const isSnoozed = session?.snoozed_threads?.some((t) => t.id === thread.id) ?? false
      const snoozeIcon = isSnoozed ? '🔔' : '😴'
      const snoozeLabel = isSnoozed ? 'Unsnooze' : 'Snooze'
      const snoozeDisabled = !isSnoozed && session?.pending_thread_id !== thread.id
      const readDisabled = isBlocked
      const readDisabledReason = blockingReasons.length > 0 ? blockingReasons.join('\n') : 'Blocked by dependency'

      return (
        <QueueThreadCard
          key={thread.id}
          thread={thread}
          index={index}
          isBlocked={isBlocked}
          blockingReasons={blockingReasons}
          isDragOver={isDragOver}
          snoozeIcon={snoozeIcon}
          snoozeLabel={snoozeLabel}
          snoozeDisabled={snoozeDisabled}
          readDisabled={readDisabled}
          readDisabledReason={readDisabledReason}
          onCardClick={() => navigate(`/thread/${thread.id}`)}
          onDragStart={actions.handleDragStart(thread.id)}
          onDragEnd={actions.handleDragEnd}
          onDragOver={actions.handleDragOver(thread.id)}
          onDrop={actions.handleDrop(thread.id, activeThreads)}
          onRead={() => void actions.handleThreadRead(thread)}
          onOpenThread={() => navigate(`/thread/${thread.id}`)}
          onSnooze={() => void actions.handleSnoozeToggle(thread, isSnoozed)}
          onActionDelete={() => actions.handleDelete(thread.id)}
          onMoveToFront={() => actions.handleMoveToFront(thread.id)}
          onMoveToBack={() => actions.handleMoveToBack(thread.id)}
          onReposition={() => modals.openRepositionModal(thread)}
          onEdit={() => modals.showEditModal(thread)}
          onDependencies={() => modals.openDependenciesModal(thread)}
          onDelete={() => actions.handleDelete(thread.id)}
        />
      )
    },
    [actions, activeThreads, modals, navigate, session],
  )

  const handleLoadMore = useCallback(() => {
    void loadMore().catch(() => undefined)
  }, [loadMore])

  const { sentinelRef } = useInfiniteScroll({
    onLoadMore: handleLoadMore,
    hasMore: !!nextPageToken,
    isLoading: isPending,
  })

  const mobileAddEnabled = !modals.isAnyModalOpen
  const shuffleDisabled = activeThreads.length < 2

  // Keep already-rendered rows visible while an additional page loads, but
  // preserve the full-screen initial loading state before Queue has any data.
  if (isPending && !threads?.length) {
    return <LoadingSpinner fullScreen />
  }

  return (
    <PositionMenuProvider>
      <div className="space-y-6 md:space-y-10 pb-10">
        <QueueControls
          activeCount={activeThreads.length}
          shuffleDisabled={shuffleDisabled}
          shufflePending={shuffleQueueMutation.isPending}
          onShuffle={actions.handleShuffle}
          onCreateThread={modals.showCreateModal}
          sortBy={sortBy}
          onSortChange={setSortBy}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />

        {mobileAddEnabled && (
          <button
            type="button"
            onClick={modals.showCreateModal}
            className="md:hidden fixed bottom-24 right-4 h-14 w-14 rounded-full bg-amber-600 text-white font-black text-3xl shadow-[0_4px_20px_rgba(212,137,14,0.4)] z-50 flex items-center justify-center hover:bg-amber-500 transition-colors"
            aria-label="Add Thread"
          >
            +
          </button>
        )}

        <QueueList
          activeThreads={activeThreads}
          filteredThreads={filteredThreads}
          reorderError={actions.reorderError}
          renderItem={renderThreadCard}
          isSearching={isSearching}
        />

        <CompletedThreadsSection
          threads={completedThreads}
          onReactivate={modals.openReactivateModal}
        />

        {isError && threads !== null && (
          <div role="alert" className="text-sm text-red-400 text-center px-2 space-y-2">
            <p>Couldn&apos;t load the next batch of threads.</p>
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

        {nextPageToken && (
          <div
            ref={sentinelRef}
            className="h-4"
            data-testid="queue-infinite-scroll-sentinel"
            aria-hidden="true"
          />
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
          setCreateForm={modals.setCreateForm}
          setEditForm={modals.setEditForm}
          issuePreview={modals.issuePreview}
          issueParseError={modals.issueParseError}
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
          onCreateSubmit={modals.handleCreateSubmit}
          onEditSubmit={modals.handleEditSubmit}
          onReactivateSubmit={modals.handleReactivateSubmit}
          onRepositionConfirm={handleRepositionConfirm}
          onDependencyChanged={() => void invalidateAfterQueueMutation(queryClient)}
          onCloseCreate={modals.closeCreateModal}
          onCloseEdit={modals.closeEditModal}
          onCloseReactivate={modals.closeReactivateModal}
          onCloseReposition={modals.closeRepositionModal}
          onCloseDependency={modals.closeDependenciesModal}
          onMigrationComplete={modals.handleMigrationComplete}
          onMigrationSkip={modals.handleMigrationSkip}
          onCloseMigration={modals.closeMigrationDialog}
          onOpenMigrationDialog={modals.openMigrationDialog}
          isPendingCreate={modals.isPendingCreate}
          isPendingEdit={modals.isPendingEdit}
          isPendingReactivate={reactivateMutation.isPending}
        />
      </div>
    </PositionMenuProvider>
  )
}

// Re-export the type for unit tests that previously imported it from QueuePage.
export type { QueueSortBy }
