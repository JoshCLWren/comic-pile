/**
 * Browser-owned Roll pending selection.
 *
 * A pending roll is an exact selection of one owned issue, not a server session.
 * It lives in browser storage, partitioned by the signed-in user so one reader
 * can never see another reader's selection. Reload restores it, a `storage`
 * event and a BroadcastChannel mirror it into other tabs, and only a committed
 * read/rate of that exact issue (or an explicit Reset) clears it. A failed
 * request, a cancel, or a direct read of an unrelated issue leaves it intact.
 *
 * Only classification facts are stored: an issue id, a thread id, an optional
 * display number/result and a timestamp. No server session identity, greeting
 * state, payload, or user data is retained beyond the partitioning key.
 */

export interface RollPendingSelection {
  /** Exact owned issue the reader is about to read. */
  issue_id: number
  /** Owning thread of `issue_id`. */
  thread_id: number
  /** Optional display number kept for the restored rating view. */
  issue_number?: string | null
  /** Die result attached to the offer, when one was rolled. */
  result?: number | null
  /** Client clock time of the most recent write. */
  selected_at: number
}

import {
  isNumber,
  isObject,
  isString,
  isWindowDefined,
} from '../utils/runtimeChecks'

const STORAGE_KEY_PREFIX = 'comic-pile:roll:pending:v1:'
const BROADCAST_CHANNEL_NAME = 'comic-pile:roll:pending'
const ANONYMOUS_KEY = 'anonymous'

type Listener = () => void

/** Cached snapshots keep `getSnapshot` referentially stable per user key. */
const snapshots = new Map<string, RollPendingSelection | null>()
const listeners = new Map<string, Set<Listener>>()

function channel(): BroadcastChannel | null {
  try {
    return globalThis.BroadcastChannel != null
      ? new BroadcastChannel(BROADCAST_CHANNEL_NAME)
      : null
  } catch {
    return null
  }
}

let broadcast: BroadcastChannel | null = null

function publish(key: string, selection: RollPendingSelection | null, origin: 'local' | 'remote'): void {
  snapshots.set(key, selection)
  for (const listener of listeners.get(key) ?? []) listener()
  if (origin === 'local') {
    broadcast ??= channel()
    try {
      broadcast?.postMessage({ key, selection })
    } catch {
      // Storage events still mirror the change when a channel is unavailable.
    }
  }
}

/** Decode one untrusted numeric field into a positive safe integer, or null. */
function positiveInteger(value: unknown): number | null {
  if (!isNumber(value) || !Number.isSafeInteger(value) || value <= 0) return null
  return value
}

/** Parse untrusted stored JSON into a validated selection, or null. */
export function parsePendingSelection(raw: string | null | undefined): RollPendingSelection | null {
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!isObject(parsed)) return null
    const issueId = positiveInteger(parsed.issue_id)
    const threadId = positiveInteger(parsed.thread_id)
    if (issueId === null || threadId === null) return null
    const selectedAt = positiveInteger(parsed.selected_at)
    const selection: RollPendingSelection = {
      issue_id: issueId,
      thread_id: threadId,
      selected_at: selectedAt ?? Date.now(),
    }
    if (isString(parsed.issue_number)) selection.issue_number = parsed.issue_number
    if (isNumber(parsed.result)) selection.result = parsed.result
    return selection
  } catch {
    return null
  }
}

/** Build the storage key for one signed-in reader. */
export function pendingSelectionStorageKey(userId: number | string | null | undefined): string {
  const id = userId == null || userId === '' ? ANONYMOUS_KEY : String(userId)
  return `${STORAGE_KEY_PREFIX}${encodeURIComponent(id)}`
}

/** Read the current browser-owned selection for one reader. */
export function readPendingSelection(userId: number | string | null | undefined): RollPendingSelection | null {
  const key = pendingSelectionStorageKey(userId)
  if (snapshots.has(key)) return snapshots.get(key) ?? null
  let raw: string | null = null
  try {
    raw = globalThis.localStorage?.getItem(key) ?? null
  } catch {
    // Private browsing must still allow a pending selection for this tab.
  }
  const selection = parsePendingSelection(raw)
  snapshots.set(key, selection)
  return selection
}

/**
 * Persist an exact selection. Concurrent tabs converge because every write is
 * validated from the complete stored record before it replaces the snapshot.
 */
export function writePendingSelection(
  userId: number | string | null | undefined,
  selection: RollPendingSelection,
): void {
  const key = pendingSelectionStorageKey(userId)
  const stored: RollPendingSelection = {
    issue_id: selection.issue_id,
    thread_id: selection.thread_id,
    selected_at: selection.selected_at > 0 ? selection.selected_at : Date.now(),
  }
  if (selection.issue_number != null) stored.issue_number = selection.issue_number
  if (selection.result != null) stored.result = selection.result
  try {
    globalThis.localStorage?.setItem(key, JSON.stringify(stored))
  } catch {
    // The in-memory snapshot still serves this tab when storage is blocked.
  }
  publish(key, stored, 'local')
}

/**
 * Clear the selection, optionally only when it still names `issueId`.
 *
 * Passing an issue id makes success paths safe against races: a newer offer
 * cannot be cleared by the response of an older rate.
 */
export function clearPendingSelection(
  userId: number | string | null | undefined,
  issueId?: number,
): void {
  const key = pendingSelectionStorageKey(userId)
  const current = readPendingSelection(userId)
  if (issueId !== undefined && (current == null || current.issue_id !== issueId)) return
  try {
    globalThis.localStorage?.removeItem(key)
  } catch {
    // The in-memory snapshot is still cleared below.
  }
  publish(key, null, 'local')
}

/** Clear every browser-owned selection for this reader (logout / Reset). */
export function clearAllPendingSelections(userId: number | string | null | undefined): void {
  clearPendingSelection(userId)
}

/**
 * Subscribe one reader's selection. Storage events cover cross-browser-process
 * changes; the BroadcastChannel covers same-process tabs even when storage is
 * blocked. Returns an unsubscribe function suitable for `useSyncExternalStore`.
 */
export function subscribePendingSelection(
  userId: number | string | null | undefined,
  listener: Listener,
): () => void {
  const key = pendingSelectionStorageKey(userId)
  let set = listeners.get(key)
  if (!set) {
    set = new Set<Listener>()
    listeners.set(key, set)
  }
  set.add(listener)

  const handleStorage = (event: StorageEvent): void => {
    if (event.key !== key) return
    publish(key, parsePendingSelection(event.newValue), 'remote')
  }
  const handleMessage = (event: MessageEvent<{ key?: unknown; selection?: unknown }>): void => {
    const data = event.data
    if (!isObject(data) || data.key !== key) return
    const raw = isObject(data.selection) ? JSON.stringify(data.selection) : null
    publish(key, parsePendingSelection(raw), 'remote')
  }

  let storageListener: ((event: StorageEvent) => void) | null = null
  try {
    if (isWindowDefined() && window.addEventListener != null) {
      storageListener = handleStorage
      window.addEventListener('storage', storageListener)
    }
  } catch {
    storageListener = null
  }

  broadcast ??= channel()
  broadcast?.addEventListener('message', handleMessage)

  return () => {
    set!.delete(listener)
    if (set!.size === 0) listeners.delete(key)
    if (storageListener) window.removeEventListener('storage', storageListener)
    broadcast?.removeEventListener('message', handleMessage)
  }
}

/** Test hook: forget cached snapshots and listeners without touching storage. */
export function resetRollPendingSelectionMemory(): void {
  snapshots.clear()
  listeners.clear()
  try {
    broadcast?.close()
  } catch {
    // Ignore a channel already closed by the host.
  }
  broadcast = null
}
