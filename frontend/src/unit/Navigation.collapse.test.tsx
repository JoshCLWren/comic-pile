import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AuthProvider } from '../App'
import Navigation from '../components/Navigation'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { NavCollapseProvider } from '../contexts/NavCollapseContext'
import { ToastProvider } from '../contexts/ToastProvider'

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
  refreshSession: vi.fn(),
  isSessionRefreshRejected: () => false,
}))

const STORAGE_KEY = 'comic-pile-nav-collapsed'

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  window.dispatchEvent(new Event('resize'))
}

function renderNavigation(initialEntry = '/') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <ToastProvider>
            <NavCollapseProvider>
              <Navigation onBugReportSubmit={vi.fn()} />
            </NavCollapseProvider>
          </ToastProvider>
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('navigation collapse behavior (#2285)', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme')
    localStorage.clear()
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.patch.mockReset()
    mocks.clearAccessToken.mockReset()
    mocks.setAccessToken.mockReset()
    mocks.getAccessToken.mockReset()
    mocks.readStoredAccessToken.mockReset()
    mocks.getAccessToken.mockReturnValue('test-token')
    mocks.readStoredAccessToken.mockReturnValue(null)
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
  })

  it('defaults to the collapsed rail on tablet portrait widths', async () => {
    setViewport(820)
    renderNavigation()

    const desktopNav = await screen.findByRole('navigation', { name: /desktop navigation/i })
    await waitFor(() => {
      expect(within(desktopNav).getByRole('link', { name: /roll page/i })).toBeInTheDocument()
    })
    expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')
    expect(within(desktopNav).getByRole('button', { name: /expand navigation/i })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('defaults to the expanded sidebar on wide desktop', async () => {
    setViewport(1440)
    renderNavigation()

    const desktopNav = await screen.findByRole('navigation', { name: /desktop navigation/i })
    await waitFor(() => {
      expect(within(desktopNav).getByRole('link', { name: /roll page/i })).toBeInTheDocument()
    })
    expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'false')
    expect(within(desktopNav).getByRole('button', { name: /collapse navigation/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(within(desktopNav).getByText('Roll')).toBeVisible()
    expect(within(desktopNav).getByText('Queue')).toBeVisible()
  })

  it('reclaims the full 288px by default only on desktop while keeping labels compact on the rail', async () => {
    setViewport(800)
    renderNavigation()

    const desktopNav = await screen.findByRole('navigation', { name: /desktop navigation/i })
    await waitFor(() => {
      expect(within(desktopNav).getByRole('link', { name: /roll page/i })).toBeInTheDocument()
    })
    expect(within(desktopNav).queryByText('Roll')).not.toBeInTheDocument()
    expect(within(desktopNav).getByRole('link', { name: /roll page/i })).toHaveAttribute(
      'title',
      'Roll',
    )
    expect(within(desktopNav).getByRole('link', { name: /queue page/i })).toHaveAttribute(
      'title',
      'Queue',
    )
  })

  it('toggles the rail with the button and persists the choice to localStorage', async () => {
    setViewport(800)
    const user = userEvent.setup()
    renderNavigation()

    const desktopNav = await screen.findByRole('navigation', { name: /desktop navigation/i })
    await waitFor(() => {
      expect(within(desktopNav).getByRole('link', { name: /roll page/i })).toBeInTheDocument()
    })

    await user.click(within(desktopNav).getByRole('button', { name: /expand navigation/i }))

    expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'false')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('false')

    await user.click(within(desktopNav).getByRole('button', { name: /collapse navigation/i }))

    expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('true')
  })

  it('restores a persisted choice even when the viewport default disagrees', async () => {
    localStorage.setItem(STORAGE_KEY, 'true')
    setViewport(1440)
    renderNavigation()

    const desktopNav = await screen.findByRole('navigation', { name: /desktop navigation/i })
    await waitFor(() => {
      expect(within(desktopNav).getByRole('button', { name: /expand navigation/i }))
        .toBeInTheDocument()
    })
    expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')
  })

  it('keeps themes, identity, and logout reachable inside the compact rail', async () => {
    setViewport(800)
    renderNavigation()

    const desktopNav = await screen.findByRole('navigation', { name: /desktop navigation/i })
    await waitFor(() => {
      expect(within(desktopNav).getByRole('button', { name: /expand navigation/i }))
        .toBeInTheDocument()
    })
    await waitFor(() => {
      expect(within(desktopNav).getByRole('group', { name: /appearance/i })).toBeInTheDocument()
    })

    for (const name of ['Classic theme', 'Ink-gold theme', 'Command center theme']) {
      expect(within(desktopNav).getByRole('button', { name })).toBeInTheDocument()
    }
    expect(within(desktopNav).getByRole('button', { name: /log out/i })).toBeInTheDocument()

    const themeButtons = within(desktopNav)
      .getByRole('group', { name: /appearance/i })
      .querySelectorAll('button[data-theme]')
    expect(themeButtons).toHaveLength(3)
  })

  it('toggles with the keyboard', async () => {
    setViewport(800)
    const user = userEvent.setup()
    renderNavigation()

    const desktopNav = await screen.findByRole('navigation', { name: /desktop navigation/i })
    const toggle = await within(desktopNav).findByRole('button', { name: /expand navigation/i })

    toggle.focus()
    await user.keyboard('{Enter}')

    expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'false')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('false')
  })
})