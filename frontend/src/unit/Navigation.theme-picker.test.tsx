import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AuthProvider } from '../App'
import Navigation from '../components/Navigation'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { ToastProvider } from '../contexts/ToastProvider'
import { readStoredThemePreference } from '../services/theme'

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

function axiosError(status: number): Error & { isAxiosError: true; response: { status: number } } {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status },
  })
}

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  window.dispatchEvent(new Event('resize'))
}

function renderNavigation() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <ToastProvider>
            <Navigation onBugReportSubmit={vi.fn()} />
          </ToastProvider>
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('desktop appearance picker (issue #1792)', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme')
    localStorage.clear()
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
    expect(screen.getByRole('button', { name: 'Classic' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ink Gold' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Command Center' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /more pages/i })).not.toBeInTheDocument()
  })

  it('marks the default theme as pressed on first load', async () => {
    renderNavigation()

    const classic = await screen.findByRole('button', { name: 'Classic' })
    expect(classic).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Ink Gold' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('reflects the locally persisted theme on load', async () => {
    localStorage.setItem('comic-pile-theme', 'command-center')

    renderNavigation()

    const commandCenter = await screen.findByRole('button', { name: 'Command Center' })
    expect(commandCenter).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Classic' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('switches themes immediately and persists through the preferences contract', async () => {
    const user = userEvent.setup()
    renderNavigation()

    await user.click(await screen.findByRole('button', { name: 'Ink Gold' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold')
    expect(screen.getByRole('button', { name: 'Ink Gold' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Classic' })).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'ink-gold' }),
    )
    expect(readStoredThemePreference()).toBe('ink-gold')
  })

  it('keeps the applied theme when the preference PATCH fails', async () => {
    mocks.patch.mockRejectedValueOnce(axiosError(503))
    const user = userEvent.setup()
    renderNavigation()

    await user.click(await screen.findByRole('button', { name: 'Command Center' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'command-center')
    expect(screen.getByRole('button', { name: 'Command Center' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(1))
    expect(readStoredThemePreference()).toBe('command-center')
    expect(await screen.findByRole('alert')).toHaveTextContent(/saving your preference failed/i)
  })

  it('syncs the picker to a server-resolved theme applied after mount', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'ink-gold', user_id: 1 })

    renderNavigation()

    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute('data-theme', 'ink-gold'),
    )
    expect(await screen.findByRole('button', { name: 'Ink Gold' })).toHaveAttribute(
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
