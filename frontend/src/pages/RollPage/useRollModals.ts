import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { threadsApi } from '../../services/api'
import { getApiErrorDetail } from '../../utils/apiError'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { RollResponse, Thread } from '../../types'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import type { ThreadMetadata } from './types'

interface UseRollModalsParams {
  state: RollPageState & RollPageStateSetters
  bootstrap?: RollBootstrapResponse | null
  overrideMutation: { mutate: (payload: { thread_id: number }) => Promise<RollResponse> }
  enterRatingView: (
    threadId: number | null,
    result?: number | null,
    metadata?: ThreadMetadata | null,
  ) => Promise<void>
  setRestoreAction: (action: () => void) => void
  clearRestoreAction: () => void
}

/**
 * Owns Roll modal coordination: the manual-override picker (loaded lazily
 * only after the modal opens), the die selector, the thread action sheet, and
 * the migration dialogs. It also restores the currently open modal after a bug
 * report so the user returns to the exact interaction they left.
 */
export function useRollModals({
  state,
  bootstrap,
  overrideMutation,
  enterRatingView,
  setRestoreAction,
  clearRestoreAction,
}: UseRollModalsParams) {
  const {
    isOverrideOpen,
    setIsOverrideOpen,
    overrideThreadId,
    setOverrideThreadId,
    setOverrideErrorMessage,
    showSimpleMigration,
    setShowSimpleMigration,
    showMigrationDialog,
    setShowMigrationDialog,
    threadToMigrate,
    isActionSheetOpen,
    selectedThread,
    setIsActionSheetOpen,
  } = state

  const [overrideThreads, setOverrideThreads] = useState<Thread[] | null>(null)

  useEffect(() => {
    if (!isOverrideOpen || overrideThreads) return

    let cancelled = false
    const snoozedThreads = bootstrap?.snoozed_threads ?? []
    const snoozedIds = new Set(snoozedThreads.map((thread) => thread.id))

    async function loadAllOverrideThreads() {
      const collected: Thread[] = []
      let pageToken: string | null = null
      do {
        const result = await threadsApi.list({ page_size: 200 }, pageToken ?? undefined)
        collected.push(...result.threads)
        pageToken = result.next_page_token ?? null
      } while (pageToken)

      if (!cancelled) {
        setOverrideThreads(
          collected.filter((thread) => thread.status === 'active' && !snoozedIds.has(thread.id)),
        )
      }
    }

    loadAllOverrideThreads().catch(() => {
      if (!cancelled) setOverrideThreads([])
    })

    return () => {
      cancelled = true
    }
  }, [isOverrideOpen, overrideThreads, bootstrap])

  useEffect(() => {
    if (showSimpleMigration) {
      setRestoreAction(() => {
        setShowSimpleMigration(true)
      })
      return
    }
    if (showMigrationDialog && threadToMigrate) {
      setRestoreAction(() => {
        setShowMigrationDialog(true)
      })
      return
    }
    if (isOverrideOpen) {
      setRestoreAction(() => {
        setIsOverrideOpen(true)
      })
      return
    }
    if (isActionSheetOpen && selectedThread) {
      setRestoreAction(() => {
        setIsActionSheetOpen(true)
      })
      return
    }
    clearRestoreAction()
  }, [
    clearRestoreAction,
    isActionSheetOpen,
    isOverrideOpen,
    selectedThread,
    setIsActionSheetOpen,
    setIsOverrideOpen,
    setRestoreAction,
    setShowMigrationDialog,
    setShowSimpleMigration,
    showMigrationDialog,
    showSimpleMigration,
    threadToMigrate,
  ])

  function handleOverrideSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!overrideThreadId) return
    overrideMutation
      .mutate({ thread_id: Number(overrideThreadId) })
      .then((response) => {
        setIsOverrideOpen(false)
        setOverrideThreadId('')
        setOverrideErrorMessage('')
        enterRatingView(response.thread_id, response.result, response)
      })
      .catch((error: unknown) => {
        setOverrideErrorMessage(getApiErrorDetail(error))
      })
  }

  function openOverrideModal() {
    setOverrideThreads(null)
    setIsOverrideOpen(true)
  }

  function closeOverrideModal() {
    setIsOverrideOpen(false)
    setOverrideErrorMessage('')
  }

  return { overrideThreads, handleOverrideSubmit, openOverrideModal, closeOverrideModal }
}