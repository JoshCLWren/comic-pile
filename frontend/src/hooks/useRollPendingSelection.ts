import { useCallback, useContext, useSyncExternalStore } from 'react'
import { AuthContext } from '../contexts/AuthContext'
import type { RollResponse } from '../types'
import {
  clearAllPendingSelections,
  clearPendingSelection,
  readPendingSelection,
  subscribePendingSelection,
  writePendingSelection,
  type RollPendingSelection,
} from '../services/rollPendingSelection'

/**
 * The minimal offer shape needed to seed an exact browser-owned selection.
 *
 * `thread_id`, `issue_id` and `result` are nullable here because the roll wire
 * response can omit an exact selection; the seeder validates them before use.
 */
export type RollOfferSeed = Omit<
  Pick<RollResponse, 'thread_id' | 'issue_id' | 'issue_number' | 'result'>,
  'thread_id' | 'result'
> & {
  thread_id: number | null
  result: number | null
}

export interface UseRollPendingSelectionResult {
  /** The exact issue restored from browser storage, or null when idle. */
  pending: RollPendingSelection | null
  /** Persist the exact issue a successful offer selected. */
  seedFromOffer: (offer: RollOfferSeed) => void
  /** Persist an explicit selection (used by direct reads and recovery). */
  select: (selection: Omit<RollPendingSelection, 'selected_at'>) => void
  /** Clear an idle/cancelled selection, optionally only for one issue. */
  clear: (issueId?: number) => void
  /** Clear every selection for this reader (logout, account switch, Reset). */
  clearAll: () => void
}

/**
 * Browser-owned pending roll selection, partitioned by the signed-in reader.
 *
 * Auth is read optionally so the hook also works in isolated unit tests and
 * before the provider has resolved. When no user is known the selection is
 * stored under an anonymous partition; once a user appears its own partition
 * is read, so an account switch can never leak one reader's pending issue.
 */
export function useRollPendingSelection(): UseRollPendingSelectionResult {
  const auth = useContext(AuthContext)
  const userId = auth?.user?.id ?? null

  const subscribe = useCallback(
    (listener: () => void) => subscribePendingSelection(userId, listener),
    [userId],
  )
  const getSnapshot = useCallback(() => readPendingSelection(userId), [userId])

  const pending = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  const seedFromOffer = useCallback(
    (offer: RollOfferSeed) => {
      if (offer.thread_id == null || offer.issue_id == null) return
      const selection: RollPendingSelection = {
        thread_id: offer.thread_id,
        issue_id: offer.issue_id,
        selected_at: Date.now(),
      }
      if (offer.issue_number != null) selection.issue_number = offer.issue_number
      if (offer.result != null) selection.result = offer.result
      writePendingSelection(userId, selection)
    },
    [userId],
  )

  const select = useCallback(
    (selection: Omit<RollPendingSelection, 'selected_at'>) => {
      writePendingSelection(userId, { ...selection, selected_at: Date.now() })
    },
    [userId],
  )

  const clear = useCallback(
    (issueId?: number) => clearPendingSelection(userId, issueId),
    [userId],
  )

  const clearAll = useCallback(() => clearAllPendingSelections(userId), [userId])

  return { pending, seedFromOffer, select, clear, clearAll }
}
