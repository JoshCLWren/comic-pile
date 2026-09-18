import type { ToastContextType } from '../contexts/ToastContext'

/** Storage key prefix for the per-user last-greeted reading session. */
export const SESSION_STORAGE_KEY_PREFIX = 'comic_pile_last_session_id'

/** User-facing greeting shown when a genuinely new reading session starts. */
export const SESSION_STARTED_TOAST_MESSAGE = 'Session started. Happy reading!'

// Shared, module-scoped de-dupe memory so every consumer (the current session
// query and the roll bootstrap) emits at most one greeting per reading-session
// transition, even when browser storage is unavailable or the write fails.
let lastGreetedKey: string | null = null
let lastGreetedSessionId: number | null = null

export interface SessionGreetingInput {
  sessionId: number
  userId?: number
  showToast: ToastContextType['showToast']
}

function buildStorageKey(userId: SessionGreetingInput['userId']): string {
  return `${SESSION_STORAGE_KEY_PREFIX}_${userId ?? 'anonymous'}`
}

function readStoredSessionId(storageKey: string): number | null {
  try {
    const storedSessionId = window.localStorage.getItem(storageKey)
    if (!storedSessionId) return null
    const parsed = parseInt(storedSessionId, 10)
    return Number.isFinite(parsed) ? parsed : null
  } catch {
    // Session loading must still succeed when browser storage is unavailable.
    return null
  }
}

function writeStoredSessionId(storageKey: string, sessionId: number): void {
  try {
    window.localStorage.setItem(storageKey, sessionId.toString())
  } catch {
    // Persisting the session id is best effort and must not hide API results.
  }
}

/**
 * Greets the user exactly once when a genuinely new reading session is
 * observed and persists that session identity as the last-greeted session.
 *
 * This is the single owner of the `comic_pile_last_session_id_*` storage key
 * and the session-started toast. Both `useSession` and `useRollBootstrap`
 * delegate here so all consumers share de-dupe state instead of racing on
 * private per-hook refs.
 */
export function trackSessionGreeting(input: SessionGreetingInput): void {
  const { sessionId } = input
  if (sessionId == null) return

  const storageKey = buildStorageKey(input.userId)
  const previousSessionId = readStoredSessionId(storageKey)
  const alreadyGreeted =
    lastGreetedKey === storageKey && lastGreetedSessionId === sessionId

  if (
    previousSessionId !== null &&
    sessionId !== previousSessionId &&
    !alreadyGreeted
  ) {
    input.showToast(SESSION_STARTED_TOAST_MESSAGE, 'info')
    lastGreetedKey = storageKey
    lastGreetedSessionId = sessionId
  }

  writeStoredSessionId(storageKey, sessionId)
}

/** Resets the shared in-memory greeting guard between tests. */
export function resetSessionGreetingMemory(): void {
  lastGreetedKey = null
  lastGreetedSessionId = null
}