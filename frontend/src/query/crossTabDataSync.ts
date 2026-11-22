import { isObject, isString } from '../utils/runtimeChecks'

/**
 * Cross-tab data-change notifications (#5686).
 *
 * The auth `BroadcastChannel` (`comic-pile-auth`) carries credential events
 * only. This channel carries committed product-data changes, so an already
 * open view in another tab can invalidate the affected queries instead of
 * serving a stale cache until the reader manually reloads.
 *
 * Delivery is best-effort: when `BroadcastChannel` is unavailable or blocked,
 * publishers and subscribers are no-ops and each view falls back to its own
 * tab-focus refresh.
 */
const DATA_SYNC_CHANNEL = 'comic-pile-data'

export type CrossTabDataChange = { readonly type: 'reading-plans-changed' }

const CROSS_TAB_CHANGE_TYPES: readonly string[] = ['reading-plans-changed']

function isCrossTabDataChange(value: unknown): value is CrossTabDataChange {
  if (!isObject(value) || !isString(value.type)) return false
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
 * A posted message is never delivered back to the posting tab, so the local
 * mutation path remains the single refresh for the tab that made the change.
 *
 * @param change - The validated change payload to publish.
 */
export function broadcastCrossTabChange(change: CrossTabDataChange): void {
  const channel = openDataChannel()
  if (!channel) return
  try {
    channel.postMessage(change)
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

/**
 * Listen for committed data changes made by other tabs.
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
    if (isCrossTabDataChange(event.data)) listener(event.data)
  }
  channel.addEventListener('message', onMessage)
  return () => {
    channel.removeEventListener('message', onMessage)
    channel.close()
  }
}
