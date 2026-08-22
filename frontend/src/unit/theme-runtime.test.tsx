import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import type { AuthContextValue } from '../App'
import { AuthProvider, useAuth } from '../App'
import Navigation from '../components/Navigation'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import {
  DEFAULT_THEME,
  ensureThemeApplied,
  getThemeSelectionToken,
  isSupportedTheme,
  readStoredThemePreference,
  restoreStoredTheme,
  selectTheme,
} from '../services/theme'
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  clearAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  getAccessToken: vi.fn<() => string | null>(),
  readStoredAccessToken: vi.fn<() => string | null>(),
}))

vi.mock('../services/api', () => ({
  default: {
    get: mocks.get,
    post: mocks.post,
    patch: mocks.patch,
  },
  clearAccessToken: mocks.clearAccessToken,
  setAccessToken: mocks.setAccessToken,
  getAccessToken: mocks.getAccessToken,
  readStoredAccessToken: mocks.readStoredAccessToken,
}))

let auth: AuthContextValue | null = null

function ThemeConsumer() {
  auth = useAuth()
  return null
}

const AUTH_ME_CONFIG = { timeout: 15000, skipAuthRedirect: true }
const PREFERENCES_CONFIG = { timeout: 15000, skipAuthRedirect: true }

function axiosError(status: number): Error & { isAxiosError: true; response: { status: number } } {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status },
  })
}

function renderProvider() {
  return render(
    <AuthProvider>
      <ThemeConsumer />
    </AuthProvider>,
  )
}

function renderNavigation() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

function bootstrapMocks(themeResponse: unknown) {
  mocks.get
    .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
    .mockResolvedValueOnce(themeResponse)
}

function resetApiMocks() {
  mocks.get.mockReset()
  mocks.post.mockReset()
  mocks.patch.mockReset()
  mocks.clearAccessToken.mockReset()
  mocks.setAccessToken.mockReset()
  mocks.getAccessToken.mockReset()
  mocks.readStoredAccessToken.mockReset()
  mocks.readStoredAccessToken.mockReturnValue(null)
}

describe('semantic theme runtime bootstrap', () => {
  beforeEach(() => {
    auth = null
    document.documentElement.removeAttribute('data-theme')
    localStorage.clear()
    resetApiMocks()
    mocks.getAccessToken.mockReturnValue('test-token')
    delete window.__COMIC_PILE_ACCESS_TOKEN
  })

  it('applies the classic default for users with no explicit preference', async () => {
    bootstrapMocks({ theme: 'classic', user_id: 1 })
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    expect(document.documentElement).toHaveAttribute('data-theme', 'classic')
  })

  it('resolves a persisted non-default theme from the server on reload', async () => {
    bootstrapMocks({ theme: 'ink-gold', user_id: 1 })
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
  })

  it('falls back to classic when the persisted theme id is unknown or stale', async () => {
    bootstrapMocks({ theme: 'neon-vaporwave', user_id: 1 })
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    expect(document.documentElement).toHaveAttribute('data-theme', 'classic')
  })

  it('seeds classic and still authenticates when the preference fetch fails with no local choice', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockRejectedValueOnce(new Error('preferences unavailable'))
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    // With no stored or rendered theme the runtime seeds the default so the
    // semantic tokens are never unset (issue #1611).
    expect(document.documentElement).toHaveAttribute('data-theme', 'classic')
    expect(mocks.get).toHaveBeenNthCalledWith(2, '/v1/users/me/preferences', PREFERENCES_CONFIG)
  })

  it('keeps the locally stored theme when the preference fetch fails with a 503-style outage', async () => {
    localStorage.setItem('comic-pile-theme', 'ink-gold')
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockRejectedValueOnce(axiosError(503))
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    // Regression for issue #1611: a transient preferences outage must never
    // reset the user's chosen theme to classic on load.
    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
  })

  it('keeps the locally stored theme when the server returns a stale preference', async () => {
    localStorage.setItem('comic-pile-theme', 'ink-gold')
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    // After an outage the stored local choice must not be silently downgraded
    // by older server preference data.
    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
  })

  it('never downgrades an already-rendered theme when the preference fetch fails', async () => {
    document.documentElement.setAttribute('data-theme', 'command-center')
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockRejectedValueOnce(new Error('preferences unavailable'))
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    expect(document.documentElement).toHaveAttribute('data-theme', 'command-center')
  })

  it('ignores stale server preference data when a newer local selection exists', async () => {
    let resolvePreferences: ((value: { theme: string; user_id: number }) => void) | undefined
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockImplementationOnce(
        () =>
          new Promise<{ theme: string; user_id: number }>((resolve) => {
            resolvePreferences = resolve
          }),
      )
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))

    // The user picks a theme while the bootstrap request is still in flight.
    act(() => {
      selectTheme('ink-gold')
    })
    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')

    await act(async () => {
      resolvePreferences?.({ theme: 'classic', user_id: 1 })
    })
    // The older server response must not clobber the fresher local choice.
    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
  })

  it('requests preferences with the same bounded bootstrap config as the session check', async () => {
    bootstrapMocks({ theme: 'command-center', user_id: 1 })
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    expect(mocks.get).toHaveBeenNthCalledWith(1, '/v1/auth/me', AUTH_ME_CONFIG)
    expect(mocks.get).toHaveBeenNthCalledWith(2, '/v1/users/me/preferences', PREFERENCES_CONFIG)
    expect(document.documentElement).toHaveAttribute('data-theme', 'command-center')
  })

  it('resolves the persisted theme when bootstrap recovers the session silently', async () => {
    mocks.get
      .mockRejectedValueOnce(axiosError(401))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'command-center', user_id: 1 })
    mocks.post.mockResolvedValueOnce({ access_token: 'new-token', refresh_token: 'new-refresh' })
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'command-center'))
    expect(mocks.get).toHaveBeenNthCalledWith(3, '/v1/users/me/preferences', PREFERENCES_CONFIG)
  })

  it('resolves the persisted theme after a fresh login on a new client', async () => {
    mocks.getAccessToken.mockReturnValue(null)
    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.post.mockRejectedValueOnce(axiosError(401))
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(false))

    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'ink-gold', user_id: 1 })

    await act(async () => {
      await auth!.login('fresh-token')
    })

    await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold'))
    expect(mocks.get).toHaveBeenNthCalledWith(3, '/v1/users/me/preferences', { skipAuthRedirect: true })
  })
})

describe('Appearance picker in the More tray', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 390,
    })
    window.dispatchEvent(new Event('resize'))
    auth = null
    document.documentElement.removeAttribute('data-theme')
    localStorage.clear()
    resetApiMocks()
    mocks.getAccessToken.mockReturnValue('test-token')
    delete window.__COMIC_PILE_ACCESS_TOKEN
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
  })

  async function openMoreTray() {
    renderNavigation()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /more pages/i }))
    return user
  }

  it('switches to ink-gold immediately and persists through the preferences contract', async () => {
    const user = await openMoreTray()

    await user.click(screen.getByRole('button', { name: 'Ink-gold theme' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'ink-gold' }),
    )
  })

  it('switches to command-center immediately and persists the choice', async () => {
    const user = await openMoreTray()

    await user.click(screen.getByRole('button', { name: 'Command center theme' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'command-center')
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'command-center' }),
    )
  })

  it('keeps the rendered theme when persisting the preference fails', async () => {
    mocks.patch.mockRejectedValueOnce(axiosError(503))
    const user = await openMoreTray()

    await user.click(screen.getByRole('button', { name: 'Ink-gold theme' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(1))
  })

  it('mirrors the selection into localStorage even when the PATCH fails', async () => {
    mocks.patch.mockRejectedValueOnce(axiosError(503))
    const user = await openMoreTray()

    await user.click(screen.getByRole('button', { name: 'Command center theme' }))

    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(1))
    expect(readStoredThemePreference()).toBe('command-center')
    expect(localStorage.getItem('comic-pile-theme')).toBe('command-center')
  })

  it('survives a reload during an outage: stored choice renders instead of classic', async () => {
    // First visit: pick ink-gold while the preferences API is down.
    mocks.patch.mockRejectedValue(axiosError(503))
    const user = await openMoreTray()
    await user.click(screen.getByRole('button', { name: 'Ink-gold theme' }))
    await waitFor(() => expect(readStoredThemePreference()).toBe('ink-gold'))

    // "Reload": the runtime restores the stored theme before any network work
    // and the bootstrap preference fetch fails again with a 503.
    document.documentElement.removeAttribute('data-theme')
    resetApiMocks()
    mocks.getAccessToken.mockReturnValue('test-token')
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockRejectedValueOnce(axiosError(503))

    restoreStoredTheme()
    renderProvider()

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
  })

  it('activates a theme with the keyboard', async () => {
    await openMoreTray()
    const user = userEvent.setup()

    screen.getByRole('button', { name: 'Classic theme' }).focus()
    await user.tab()
    await user.keyboard('{Enter}')

    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'ink-gold' }),
    )
  })
})

describe('theme service primitives', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme')
    localStorage.clear()
  })

  it('validates theme ids strictly', () => {
    expect(isSupportedTheme('ink-gold')).toBe(true)
    expect(isSupportedTheme('classic')).toBe(true)
    expect(isSupportedTheme('command-center')).toBe(true)
    expect(isSupportedTheme('neon-vaporwave')).toBe(false)
    expect(isSupportedTheme(null)).toBe(false)
    expect(isSupportedTheme(undefined)).toBe(false)
    expect(isSupportedTheme(42)).toBe(false)
  })

  it('ignores unsupported stored values instead of applying them', () => {
    localStorage.setItem('comic-pile-theme', 'neon-vaporwave')
    expect(readStoredThemePreference()).toBeNull()

    ensureThemeApplied()
    expect(document.documentElement).toHaveAttribute('data-theme', DEFAULT_THEME)
  })

  it('never downgrades a rendered theme in ensureThemeApplied', () => {
    document.documentElement.setAttribute('data-theme', 'command-center')

    ensureThemeApplied()

    expect(document.documentElement).toHaveAttribute('data-theme', 'command-center')
  })

  it('advances the selection token only for supported selections', () => {
    const before = getThemeSelectionToken()

    expect(selectTheme('not-a-theme')).toBeNull()
    expect(getThemeSelectionToken()).toBe(before)

    act(() => {
      selectTheme('ink-gold')
    })
    expect(getThemeSelectionToken()).toBe(before + 1)
    expect(readStoredThemePreference()).toBe('ink-gold')
    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
  })
})
