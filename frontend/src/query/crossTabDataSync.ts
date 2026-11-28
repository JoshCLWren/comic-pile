import { isObject, isString } from '../utils/runtimeChecks'

/**
 * Cross-tab data-change notifications (#5686, #5862).
 *
 * The auth `BroadcastChannel` (`comic-pile-auth`) carries credential events
 * only. This channel carries committed product-data changes, so an already
 * open view in another tab can invalidate the affected queries instead of
 * serving a stale cache until the reader manually reloads. Plan writes (#5686)
 * and Thread title edits (#5862) both announce themselves here.
 *
 * Delivery is best-effort: when `BroadcastChannel` is unavailable or blocked,
 * publishers and subscribers are no-ops and each view falls back to its own
 * tab-focus refresh.
 */
const DATA_SYNC_CHANNEL = 'comic-pile-data'

/** Identifies this tab so a subscriber never reacts to its own broadcast. */
const TAB_ID: string =
  globalThis.crypto?.randomUUID?.() ?? `tab-${Math.random().toString(36).slice(2)}`

export type CrossTabDataChange = {
  readonly type: 'reading-plans-changed' | 'thread-metadata-changed'
  readonly senderId: string
}

const CROSS_TAB_CHANGE_TYPES: readonly string[] = [
  'reading-plans-changed',
  'thread-metadata-changed',
]

function isCrossTabDataChange(value: unknown): value is CrossTabDataChange {
  if (!isObject(value) || !isString(value.type) || !isString(value.senderId)) return false
  return CROSS_TAB_CHANGE_TYPES.includes(value.type)
}

function openDataChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === 'undefined') return null
  try {
    return new BroadcastChannel(DATA_SYNC_CHANNEL)
  } catch {
    // Private-mode or policy-blocked channels must never break the write.
    return null
  }
}

/**
 * Announce a committed change to every other tab in this browser.
 *
 * The payload carries this tab's sender ID so a subscriber in the same tab can
 * ignore it. That guards against double-refresh when the writing tab holds its
 * own subscriber (BroadcastChannel only excludes the posting channel object, not
 * other channel objects in the same tab).
 *
 * @param change - The change payload to publish; `senderId` is added here.
 */
export function broadcastCrossTabChange(
  change: Omit<CrossTabDataChange, 'senderId'>,
): void {
  const channel = openDataChannel()
  if (!channel) return
  try {
    channel.postMessage({ ...change, senderId: TAB_ID })
  } catch {
    // Best-effort delivery: the writing tab already refreshed its own cache.
  } finally {
    channel.close()
  }
}

/** Announce a committed plan create, update, or delete. */
export function notifyReadingPlansChanged(): void {
  broadcastCrossTabChange({ type: 'reading-plans-changed' })
}

/** Announce a committed Thread title edit (#5862). */
export function notifyThreadMetadataChanged(): void {
  broadcastCrossTabChange({ type: 'thread-metadata-changed' })
}

/**
 * Listen for committed data changes made by other tabs.
 *
 * Messages published by this same tab are ignored so the writing tab's local
 * mutation path remains the single refresh for its own write.
 *
 * @param listener - Receives each validated change payload.
 * @returns Cleanup that removes the listener and closes the channel.
 */
export function subscribeToCrossTabChanges(
  listener: (change: CrossTabDataChange) => void,
): () => void {
  const channel = openDataChannel()
  if (!channel) return () => {}
  const onMessage = (event: MessageEvent<unknown>): void => {
    if (isCrossTabDataChange(event.data) && event.data.senderId !== TAB_ID) {
      listener(event.data)
    }
  }
  channel.addEventListener('message', onMessage)
  return () => {
    channel.removeEventListener('message', onMessage)
    channel.close()
  }
}
