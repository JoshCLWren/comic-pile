import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { threadsApi } from '../../services/api-threads'
import type { RollState } from '../../types/rollState'
import type { ThreadListItem } from '../../types'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'

interface UseRollModalsParams {
  state: RollPageState & RollPageStateSetters
  bootstrap?: RollState | null
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
    isDirectReadOpen,
    setIsDirectReadOpen,
    setSelectedThread,
    isShuffleOpen,
    setIsShuffleOpen,
  } = state

  const [overrideThreads, setOverrideThreads] = useState<ThreadListItem[] | null>(null)

  useEffect(() => {
    if (!isOverrideOpen || overrideThreads) return

    let cancelled = false
    async function loadAllOverrideThreads() {
      const collected: ThreadListItem[] = []
      let pageToken: string | null = null
      do {
        const result = await threadsApi.list({ page_size: 200 }, pageToken ?? undefined)
        collected.push(...result.threads)
        pageToken = result.next_page_token ?? null
      } while (pageToken)

      if (!cancelled) {
        // Keep the full thread projection: RollModal filters choices, and
        // snoozed options also need the canonical series cover from this batch.
        setOverrideThreads(collected)
      }
    }

    loadAllOverrideThreads().catch(() => {
      if (!cancelled) setOverrideThreads([])
    })

    return () => {
      cancelled = true
    }
  }, [isOverrideOpen, overrideThreads])

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
    if (isDirectReadOpen && selectedThread) {
      setRestoreAction(() => setIsDirectReadOpen(true))
      return
    }
    if (isActionSheetOpen && selectedThread) {
      setRestoreAction(() => {
        setIsActionSheetOpen(true)
      })
      return
    }
    if (isShuffleOpen) {
      setRestoreAction(() => {
        setIsShuffleOpen(true)
      })
      return
    }
    clearRestoreAction()
  }, [
    clearRestoreAction,
    isActionSheetOpen,
    isDirectReadOpen,
    isOverrideOpen,
    isShuffleOpen,
    selectedThread,
    setIsActionSheetOpen,
    setIsDirectReadOpen,
    setIsOverrideOpen,
    setIsShuffleOpen,
    setRestoreAction,
    setShowMigrationDialog,
    setShowSimpleMigration,
    showMigrationDialog,
    showSimpleMigration,
    threadToMigrate,
  ])

  function handleOverrideSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // A manual series choice opens the exact-issue editor, not an automatic
    // Roll override. No persistent state changes on this path before Save.
    // The picker also displays owner-scoped snoozed entries from bootstrap.
    // Resolve those even when the paginated thread-list read has failed.
    const selected = overrideThreads?.find((thread) => String(thread.id) === overrideThreadId)
      ?? bootstrap?.snoozed_threads?.find((thread) => String(thread.id) === overrideThreadId)
    if (!selected) {
      setOverrideErrorMessage('Choose an owned series first.')
      return
    }
    setSelectedThread({ id: selected.id, title: selected.title, format: selected.format })
    setIsOverrideOpen(false)
    setOverrideThreadId('')
    setOverrideErrorMessage('')
    setIsDirectReadOpen(true)
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
