/**
 * Best-effort server synchronization for the locally selected theme.
 *
 * A theme choice applies instantly and survives reloads through the
 * localStorage mirror (see theme.ts). Server persistence is reconciled in the
 * background so the preference also follows the user across devices.
 *
 * When the preferences API is unavailable — for example 503 responses while a
 * transient database outage passes (issue #1872) — the latest selection is now
 * retried with bounded backoff instead of being dropped permanently, repeated
 * failures notify the user once per outage episode rather than once per click,
 * and a successful bootstrap read converges the server to the stored local
 * choice on the next reload.
 */

import api from './api'
import type { ThemeId } from './theme'

/** Delays between persistence retries after the first attempt fails. */
const DEFAULT_RETRY_DELAYS_MS: readonly number[] = [1000, 4000]

export type FailureNotifier = () => void

let retryDelaysMs: readonly number[] = DEFAULT_RETRY_DELAYS_MS

let pendingTheme: ThemeId | null = null
let generation = 0
const pendingTimers = new Set<ReturnType<typeof setTimeout>>()
let notifiedThisEpisode = false
let lastFailureNotifier: FailureNotifier | undefined
let onlineHandler: (() => void) | null = null

function clearPendingTimers(): void {
  for (const timer of pendingTimers) {
    clearTimeout(timer)
  }
  pendingTimers.clear()
}

function scheduleCallback(delayMs: number, callback: () => void): void {
  const timer = setTimeout(() => {
    pendingTimers.delete(timer)
    callback()
  }, delayMs)
  pendingTimers.add(timer)
}

async function attemptPersist(theme: ThemeId): Promise<void> {
  await api.patch('/v1/users/me/preferences', { theme })
}

/**
 * Run one flush chain for a generation until it succeeds, exhausts its retry
 * budget, or is superseded by a newer selection.
 */
async function runFlush(
  flushGeneration: number,
  attemptIndex: number,
  onFailure?: FailureNotifier,
): Promise<void> {
  const theme = pendingTheme
  if (flushGeneration !== generation || theme === null) return

  try {
    await attemptPersist(theme)
  } catch (error) {
    if (flushGeneration !== generation || pendingTheme === null) return

    if (attemptIndex < retryDelaysMs.length) {
      scheduleCallback(retryDelaysMs[attemptIndex] ?? 0, () => {
        void runFlush(flushGeneration, attemptIndex + 1, onFailure)
      })
      return
    }

    // The retry budget is exhausted for this episode. Tell the user once —
    // not once per failing click — and try again quietly when connectivity
    // returns. The local mirror already preserves the choice either way.
    if (!notifiedThisEpisode) {
      notifiedThisEpisode = true
      console.error('Failed to persist theme preference:', error)
      onFailure?.()
    }
    attachOnlineRetry()
    return
  }

  if (flushGeneration !== generation) return
  pendingTheme = null
  notifiedThisEpisode = false
}

function attachOnlineRetry(): void {
  if (onlineHandler !== null || typeof window === 'undefined') return
  onlineHandler = () => {
    if (pendingTheme === null) return
    startFlush(lastFailureNotifier)
  }
  window.addEventListener('online', onlineHandler)
}

function startFlush(onFailure?: FailureNotifier): void {
  generation += 1
  clearPendingTimers()
  void runFlush(generation, 0, onFailure)
}

/**
 * Queue the latest theme selection for background persistence.
 *
 * Any still-pending write is replaced (last selection wins) and the flush
 * chain restarts with a full retry budget. ``onFailure`` runs at most once
 * per outage episode when every attempt has failed.
 */
export function persistThemePreference(
  theme: ThemeId,
  onFailure?: FailureNotifier,
): void {
  if (onFailure) {
    lastFailureNotifier = onFailure
  }
  pendingTheme = theme
  startFlush(onFailure)
}

/**
 * Silently push a previously stored local choice to the server during app
 * bootstrap. Used to converge server state after an earlier outage prevented
 * persistence; never notifies because the user did not act in this session.
 */
export function reconcileStoredThemeWithServer(theme: ThemeId): void {
  persistThemePreference(theme)
}

/** Replace the retry backoff schedule (test hook). */
export function setThemePreferenceRetryDelaysForTests(
  delaysMs: readonly number[],
): void {
  retryDelaysMs = delaysMs
}

/** Cancel pending writes, timers, and listeners (test isolation hook). */
export function resetThemePreferenceSyncForTests(): void {
  generation += 1
  pendingTheme = null
  clearPendingTimers()
  notifiedThisEpisode = false
  lastFailureNotifier = undefined
  if (onlineHandler !== null && typeof window !== 'undefined') {
    window.removeEventListener('online', onlineHandler)
  }
  onlineHandler = null
}
