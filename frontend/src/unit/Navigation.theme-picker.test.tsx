import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from '../App'
import Navigation from '../components/Navigation'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { NavCollapseProvider } from '../contexts/NavCollapseContext'
import { ToastProvider } from '../contexts/ToastProvider'
import { cast } from '../utils/cast'
import { readStoredThemePreference } from '../services/theme'
import {
  resetThemePreferenceSyncForTests,
  setThemePreferenceRetryDelaysForTests,
} from '../services/themePreferenceSync'
import { PreferencesSync } from '../hooks/usePreferences'
import { queryClient } from '../query/queryClient'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  clearAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  getAccessToken: vi.fn<() => string | null>(),
  readStoredAccessToken: vi.fn<() => string | null>(),
}))

vi.mock('../services/api', () => {
  const apiMock = {
    get: mocks.get,
    post: mocks.post,
    patch: mocks.patch,
  }
  return {
    default: apiMock,
    api: apiMock,
    preferencesApi: {
      get: (options?: { timeout?: number; skipAuthRedirect?: boolean }) =>
        apiMock.get('/v1/users/me/preferences', options),
      patch: (data: { theme?: string | null }) =>
        apiMock.patch('/v1/users/me/preferences', data),
    },
    clearAccessToken: mocks.clearAccessToken,
    setAccessToken: mocks.setAccessToken,
    getAccessToken: mocks.getAccessToken,
    readStoredAccessToken: mocks.readStoredAccessToken,
    refreshSession: vi.fn(),
    isSessionRefreshRejected: () => false,
  }
})

function axiosError(status: number): Error & { isAxiosError: true; response: { status: number } } {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status },
  })
}

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  const isMobile = width < 768
  const isTablet = width >= 768 && width < 1024
  const isDesktop = width >= 1024
  window.matchMedia = vi.fn((query: string) => {
    if (query === '(max-width: 767px)') return cast<MediaQueryList>({ matches: isMobile, addListener: vi.fn(), removeListener: vi.fn() })
    if (query.includes('min-width: 768px')) return cast<MediaQueryList>({ matches: isTablet, addListener: vi.fn(), removeListener: vi.fn() })
    if (query.includes('min-width: 1024px')) return cast<MediaQueryList>({ matches: isDesktop, addListener: vi.fn(), removeListener: vi.fn() })
    return cast<MediaQueryList>({ matches: true, addListener: vi.fn(), removeListener: vi.fn() })
  })
  window.dispatchEvent(new Event('resize'))
}

const PREFERENCES_CONFIG = { timeout: 15000, skipAuthRedirect: true }

async function waitForPreferencesApplied() {
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('/v1/users/me/preferences', PREFERENCES_CONFIG))
  await waitFor(() => expect(queryClient.getQueryState(['preferences', 'detail'])?.status).toBe('success'))
}

function renderNavigation() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <BugReportRestoreProvider>
            <ToastProvider>
              <NavCollapseProvider>
                <Navigation onBugReportSubmit={vi.fn()} />
                <PreferencesSyncConsumer />
              </NavCollapseProvider>
            </ToastProvider>
          </BugReportRestoreProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function PreferencesSyncConsumer() {
  const { isAuthenticated } = useAuth()
  return <PreferencesSync isAuthenticated={isAuthenticated} />
}

describe('desktop appearance picker (issue #1792)', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme')
    localStorage.clear()
    resetThemePreferenceSyncForTests()
    setThemePreferenceRetryDelaysForTests([0, 0])
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.patch.mockReset()
    mocks.getAccessToken.mockReset()
    mocks.readStoredAccessToken.mockReset()
    mocks.getAccessToken.mockReturnValue('test-token')
    mocks.readStoredAccessToken.mockReturnValue(null)
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
    delete window.__COMIC_PILE_ACCESS_TOKEN
    setViewport(1024)
  })

  it('exposes the theme selector on a desktop viewport where the More tray is unavailable', async () => {
    renderNavigation()

    const group = await screen.findByRole('group', { name: /appearance/i })
    expect(group).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Classic theme' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ink Gold theme' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Command Center theme' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /more pages/i })).not.toBeInTheDocument()
  })

  it('marks the default theme as pressed on first load', async () => {
    renderNavigation()

    const classic = await screen.findByRole('button', { name: 'Classic theme' })
    expect(classic).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Ink Gold theme' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('reflects the locally persisted theme on load', async () => {
    localStorage.setItem('comic-pile-theme', 'command-center')

    renderNavigation()

    const commandCenter = await screen.findByRole('button', { name: 'Command Center theme' })
    expect(commandCenter).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Classic theme' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('switches themes immediately and persists through the preferences contract', async () => {
    const user = userEvent.setup()
    renderNavigation()
    await waitForPreferencesApplied()

    await user.click(await screen.findByRole('button', { name: 'Ink Gold theme' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
    expect(screen.getByRole('button', { name: 'Ink Gold theme' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Classic theme' })).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'ink-gold' }),
    )
    expect(readStoredThemePreference()).toBe('ink-gold')
  })

  it('retries a transient preference failure and converges without an error', async () => {
    mocks.patch.mockRejectedValueOnce(axiosError(503))
    const user = userEvent.setup()
    renderNavigation()
    await waitForPreferencesApplied()

    await user.click(await screen.findByRole('button', { name: 'Command Center theme' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'command-center')
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(2))
    expect(readStoredThemePreference()).toBe('command-center')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows one bounded error per outage episode despite repeated failing clicks', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    mocks.patch.mockRejectedValue(axiosError(503))
    const user = userEvent.setup()
    renderNavigation()
    await waitForPreferencesApplied()

    await user.click(await screen.findByRole('button', { name: 'Command Center theme' }))
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(3))

    await user.click(screen.getByRole('button', { name: 'Ink Gold theme' }))
    await waitFor(() => expect(mocks.patch.mock.calls.length).toBeGreaterThanOrEqual(4))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())

    await waitFor(() => expect(mocks.patch.mock.calls.length).toBeGreaterThanOrEqual(6))
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('alert')).toHaveTextContent(/saving your preference failed/i)
    expect(consoleError).toHaveBeenCalledTimes(1)
    consoleError.mockRestore()
  })

  it('syncs the picker to a server-resolved theme applied after mount', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'ink-gold', user_id: 1 })

    renderNavigation()
    await waitForPreferencesApplied()

    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold'),
    )
    expect(await screen.findByRole('button', { name: 'Ink Gold theme' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})

describe('mobile More tray keeps the theme selector (issue #1792)', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme')
    localStorage.clear()
    mocks.get.mockReset()
    mocks.patch.mockReset()
    mocks.getAccessToken.mockReset()
    mocks.readStoredAccessToken.mockReset()
    mocks.getAccessToken.mockReturnValue('test-token')
    mocks.readStoredAccessToken.mockReturnValue(null)
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
    delete window.__COMIC_PILE_ACCESS_TOKEN
    setViewport(390)
  })

  it('offers every theme inside the More tray on mobile', async () => {
    const user = userEvent.setup()
    renderNavigation()
    await waitForPreferencesApplied()

    await user.click(await screen.findByRole('button', { name: /more pages/i }))

    const tray = within(screen.getByRole('navigation', { name: /more pages/i }))
    expect(tray.getByRole('button', { name: 'Classic theme' })).toHaveAttribute('aria-pressed', 'true')
    expect(tray.getByRole('button', { name: 'Ink-gold theme' })).toBeInTheDocument()
    expect(tray.getByRole('button', { name: 'Command center theme' })).toBeInTheDocument()

    await user.click(tray.getByRole('button', { name: 'Ink-gold theme' }))
    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'ink-gold' }),
    )
  })
})