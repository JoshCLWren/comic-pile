import { AUTH_TOKEN_STORAGE_KEY } from '../services/api'

export const RETURNING_VISITOR_STORAGE_KEY = 'comic-pile:returning-visitor'

function canUseLocalStorage(): boolean {
  return typeof localStorage !== 'undefined'
}

/**
 * Whether the visitor has a returning signal: an explicit flag set after a
 * prior successful sign-in/sign-up, or a stored auth token from a prior
 * session. First-time visitors (neither present) must not see "Welcome Back".
 */
export function isReturningVisitor(): boolean {
  if (!canUseLocalStorage()) {
    return false
  }
  try {
    if (localStorage.getItem(RETURNING_VISITOR_STORAGE_KEY) === '1') {
      return true
    }
    return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) !== null
  } catch {
    return false
  }
}

/** Record that this browser has completed an auth flow (copy/chrome only). */
export function markReturningVisitor(): void {
  if (!canUseLocalStorage()) {
    return
  }
  try {
    localStorage.setItem(RETURNING_VISITOR_STORAGE_KEY, '1')
  } catch {
    // Storage unavailable (private mode, SSR); auth chrome falls back to first-visit copy.
  }
}
