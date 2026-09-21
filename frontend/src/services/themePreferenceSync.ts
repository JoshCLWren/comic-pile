/**
 * Notification state for theme preference persistence failures.
 *
 * Preference reads and writes now flow through React Query hooks
 * (`usePreferences` / `useUpdatePreferences`), so React Query's built-in
 * mutation retry handles transient persistence failures with the backoff
 * schedule configured below. This module tracks whether a persistent failure
 * notification has already been shown for the current outage episode so the
 * user is told once per outage rather than once per click (issue #1872).
 */

/** Delays between preference-save retries after the first attempt fails. */
const DEFAULT_RETRY_DELAYS_MS: readonly number[] = [1000, 4000]

let retryDelaysMs: readonly number[] = DEFAULT_RETRY_DELAYS_MS

let notifiedThisEpisode = false

/** Replace the retry backoff schedule (test hook). */
export function setThemePreferenceRetryDelaysForTests(
  delaysMs: readonly number[],
): void {
  retryDelaysMs = delaysMs
}

/** Cancel pending failure-notification state (test isolation hook). */
export function resetThemePreferenceSyncForTests(): void {
  notifiedThisEpisode = false
  retryDelaysMs = DEFAULT_RETRY_DELAYS_MS
}

/** Current retry backoff schedule used by the preferences mutation. */
export function getThemePreferenceRetryDelays(): readonly number[] {
  return retryDelaysMs
}

/** Whether a persistent theme save failure was already reported this episode. */
export function hasNotifiedThemeFailureThisEpisode(): boolean {
  return notifiedThisEpisode
}

/** Record that a persistent theme save failure was reported this episode. */
export function markThemeFailureNotifiedThisEpisode(): void {
  notifiedThisEpisode = true
}

/** End the failure-notification episode (for example after a successful save). */
export function clearThemeFailureNotifiedThisEpisode(): void {
  notifiedThisEpisode = false
}
