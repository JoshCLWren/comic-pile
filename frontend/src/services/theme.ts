/**
 * Client-side theme runtime shared by the app bootstrap and the appearance
 * picker (issue #1611).
 *
 * The selected theme must take effect immediately and survive reloads even
 * when the preferences API is unavailable (for example during a transient
 * database outage that surfaces as 503 responses). The last local choice is
 * therefore mirrored in localStorage and only ever reconciled — never silently
 * downgraded — by server preference data.
 */

export const THEME_IDS = ['classic', 'ink-gold', 'command-center'] as const

export type ThemeId = (typeof THEME_IDS)[number]

export const DEFAULT_THEME: ThemeId = 'classic'

const THEME_STORAGE_KEY = 'comic-pile-theme'

/**
 * Monotonic token incremented on every local selection. Async server
 * reconciliation captures the token before awaiting and skips applying stale
 * results when a newer local choice exists.
 */
let selectionToken = 0

function isBrowser(): boolean {
  return typeof document !== 'undefined' && typeof localStorage !== 'undefined'
}

/** Check whether a raw value is a supported theme id. */
export function isSupportedTheme(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value)
}

/** Read the locally persisted theme preference, or null when absent/invalid. */
export function readStoredThemePreference(): ThemeId | null {
  if (!isBrowser()) {
    return null
  }
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return isSupportedTheme(stored) ? stored : null
  } catch {
    // Storage can be unavailable (private mode, disabled cookies). A missing
    // mirror degrades to classic defaults; it never breaks rendering.
    return null
  }
}

/** Persist the theme preference locally. Storage failures are non-fatal. */
export function writeStoredThemePreference(theme: ThemeId): void {
  if (!isBrowser()) {
    return
  }
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Non-fatal: the rendered attribute still applies for this page session.
  }
}

/** Return the currently applied theme, or null when none/unset is applied. */
export function getAppliedTheme(): ThemeId | null {
  if (typeof document === 'undefined') {
    return null
  }
  const current = document.documentElement.getAttribute('data-theme')
  return isSupportedTheme(current) ? current : null
}

/** Apply a supported theme to the document root. */
export function applyTheme(theme: ThemeId): void {
  document.documentElement.setAttribute('data-theme', theme)
}

/**
 * Guarantee some valid theme is rendered without ever downgrading one already
 * resolved: keep an applied theme as-is, otherwise restore the stored local
 * choice, otherwise seed the default so semantic tokens always have values.
 */
export function ensureThemeApplied(): void {
  if (!isBrowser() || getAppliedTheme() !== null) {
    return
  }
  applyTheme(readStoredThemePreference() ?? DEFAULT_THEME)
}

/** Restore the locally persisted choice before any network access happens. */
export function restoreStoredTheme(): void {
  ensureThemeApplied()
}

/**
 * Capture the selection-generation token used to detect stale async server
 * reconciliation attempts.
 */
export function getThemeSelectionToken(): number {
  return selectionToken
}

/**
 * Record a user's theme selection: bump the race token, persist locally, and
 * apply immediately. Returns null when the requested theme is unsupported.
 */
export function selectTheme(themeId: string): ThemeId | null {
  if (!isSupportedTheme(themeId)) {
    return null
  }
  selectionToken += 1
  writeStoredThemePreference(themeId)
  applyTheme(themeId)
  return themeId
}
