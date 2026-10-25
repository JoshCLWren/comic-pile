import { useEffect } from 'react'
import type { RollBootstrapResponse, RollBootstrapThread } from '../../types/rollBootstrap'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import type { ThreadMetadata } from './types'

interface UseRollPendingSessionParams {
  state: RollPageState & RollPageStateSetters
  bootstrap?: RollBootstrapResponse | null
  rollPool: RollBootstrapThread[]
}

/**
 * Hydrates an existing pending roll into the rating view whenever the
 * bootstrap payload exposes one. This is the active-session recovery boundary:
 * it restores the full rating context without issuing any additional request,
 * so a reload or navigation never loses an in-flight read.
 */
export function useRollPendingSession({ state, bootstrap, rollPool }: UseRollPendingSessionParams): void {
  const {
    suppressPendingAutoOpenRef,
    ignoredPendingThreadIdRef,
    selectedThreadId,
    activeRatingThread,
    isRatingView,
    setSelectedThreadId,
    setRolledResult,
    setActiveRatingThread,
    setRating,
    setErrorMessage,
    setIsRatingView,
    setIsActionSheetOpen,
    setIsOverrideOpen,
    setIsDieModalOpen,
  } = state

  useEffect(() => {
    if (suppressPendingAutoOpenRef.current) return
    const pendingThreadId = bootstrap?.pending_thread_id
    if (!pendingThreadId) {
      // No pending read means the snapshot can no longer name a thread the
      // reader already left, so the consumed-id guard has served its purpose.
      ignoredPendingThreadIdRef.current = null
      return
    }

    const pendingId = Number(pendingThreadId)
    // A committed Skip consumed this pending read, but its authoritative
    // refresh failed, so `bootstrap` is still the pre-skip snapshot. Hydrating
    // it here would reopen the series the reader just skipped (#4142). Ignore
    // that exact id until a newer snapshot reports a different pending read.
    if (ignoredPendingThreadIdRef.current === pendingId) return
    ignoredPendingThreadIdRef.current = null

    const isCurrentPendingSelection = Number(selectedThreadId) === pendingId
    const hasHydratedPendingMetadata = Boolean(activeRatingThread?.title)

    if (isRatingView && isCurrentPendingSelection && hasHydratedPendingMetadata) return

    const pendingFromSession =
      bootstrap?.active_thread && bootstrap.active_thread.id === pendingId
        ? {
            id: bootstrap.active_thread.id,
            title: bootstrap.active_thread.title,
            format: bootstrap.active_thread.format,
            issues_remaining: bootstrap.active_thread.issues_remaining ?? 0,
            queue_position: bootstrap.active_thread.queue_position ?? 0,
            total_issues: bootstrap.active_thread.total_issues ?? null,
            reading_progress: bootstrap.active_thread.reading_progress ?? null,
            issue_id: bootstrap.active_thread.issue_id ?? null,
            issue_number: bootstrap.active_thread.issue_number ?? null,
            next_issue_id: bootstrap.active_thread.next_issue_id ?? null,
            next_issue_number: bootstrap.active_thread.next_issue_number ?? null,
            last_rolled_result:
              bootstrap.last_rolled_result ?? bootstrap.active_thread.last_rolled_result ?? null,
          }
        : null

    const pendingFromPool =
      !pendingFromSession && rollPool.length > 0
        ? rollPool.find((thread) => thread.id === pendingId)
        : null

    const pendingResult =
      pendingFromSession?.last_rolled_result ?? bootstrap?.last_rolled_result ?? null
    // SAFETY: both pendingFromSession and pendingFromPool carry ThreadMetadata when present; the union falls back to null.
    const pendingMetadata = (pendingFromSession ?? pendingFromPool) as ThreadMetadata | null
    const shouldInitializeRatingView = !isRatingView || !isCurrentPendingSelection

    setSelectedThreadId(pendingId)
    if (pendingResult !== null && pendingResult !== undefined) setRolledResult(pendingResult)
    if (pendingMetadata && pendingMetadata.title) {
      setActiveRatingThread({
        id: pendingMetadata.id ?? pendingId,
        title: pendingMetadata.title,
        format: pendingMetadata.format ?? '',
        issues_remaining: pendingMetadata.issues_remaining ?? 0,
        queue_position: pendingMetadata.queue_position ?? 0,
        total_issues: pendingMetadata.total_issues ?? null,
        reading_progress: pendingMetadata.reading_progress ?? null,
        issue_id: pendingMetadata.issue_id ?? null,
        issue_number: pendingMetadata.issue_number ?? null,
        next_issue_id: pendingMetadata.next_issue_id ?? null,
        next_issue_number: pendingMetadata.next_issue_number ?? null,
        last_rolled_result: pendingMetadata.last_rolled_result ?? pendingResult,
      })
    }
    if (shouldInitializeRatingView) {
      setRating(3.0)
      setErrorMessage('')
      setIsRatingView(true)
    }
    setIsActionSheetOpen(false)
    setIsOverrideOpen(false)
    setIsDieModalOpen(false)
  }, [
    bootstrap?.pending_thread_id,
    bootstrap?.active_thread,
    bootstrap?.last_rolled_result,
    rollPool,
    activeRatingThread,
    isRatingView,
    selectedThreadId,
    suppressPendingAutoOpenRef,
    ignoredPendingThreadIdRef,
    setSelectedThreadId,
    setRolledResult,
    setActiveRatingThread,
    setRating,
    setErrorMessage,
    setIsRatingView,
    setIsActionSheetOpen,
    setIsOverrideOpen,
    setIsDieModalOpen,
  ])
}