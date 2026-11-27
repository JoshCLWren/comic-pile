/**
 * Night Shift shared-surface contract (#5980). Replaces the retired
 * multi-theme surface tests: the shell, sidebar and More tray must render from
 * semantic roles only, with no appearance picker and no theme-specific markup.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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
import { queryClient } from '../query/queryClient'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  clearAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  getAccessToken: vi.fn<() => string | null>(),
  readStoredAccessToken: vi.fn<() => string | null>(),
  refreshSession: vi.fn(),
  isSessionRefreshRejected: vi.fn(() => false),
}))

vi.mock('../services/api', () => {
  const apiMock = { get: mocks.get, post: mocks.post, patch: mocks.patch }
  return {
    default: apiMock,
    api: apiMock,
    clearAccessToken: mocks.clearAccessToken,
    setAccessToken: mocks.setAccessToken,
    getAccessToken: mocks.getAccessToken,
    readStoredAccessToken: mocks.readStoredAccessToken,
    refreshSession: mocks.refreshSession,
    isSessionRefreshRejected: mocks.isSessionRefreshRejected,
  }
})

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  const isMobile = width < 768
  const isTablet = width >= 768 && width < 1024
  const isDesktop = width >= 1024
  window.matchMedia = vi.fn((query: string) => {
    if (query === '(max-width: 767px)') return cast<MediaQueryList>({ matches: isMobile, addListener: vi.fn(), removeListener: vi.fn() })
    if (query.includes('min-width: 768px')) return cast<MediaQueryList>({ matches: isTablet, addListener: vi.fn(), removeListener: vi.fn() })
    if (query.includes('min-width: 1024px')) return cast<MediaQueryList>({ matches: isDesktop, addListener: vi.fn(), removeListener: vi.fn() })
    return cast<MediaQueryList>({ matches: false, addListener: vi.fn(), removeListener: vi.fn() })
  })
  window.dispatchEvent(new Event('resize'))
}

let authenticated = false

function AuthStatus() {
  authenticated = useAuth().authState.status === 'authenticated'
  return null
}

function renderNavigation() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <BugReportRestoreProvider>
            <ToastProvider>
              <NavCollapseProvider>
                <AuthStatus />
                <Navigation onBugReportSubmit={vi.fn()} />
              </NavCollapseProvider>
            </ToastProvider>
          </BugReportRestoreProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  authenticated = false
  queryClient.clear()
  document.documentElement.removeAttribute('data-theme')
  localStorage.clear()
  mocks.get.mockReset()
  mocks.post.mockReset()
  mocks.patch.mockReset()
  mocks.getAccessToken.mockReset()
  mocks.readStoredAccessToken.mockReset()
  mocks.refreshSession.mockReset()
  mocks.getAccessToken.mockReturnValue('test-token')
  mocks.readStoredAccessToken.mockReturnValue(null)
  mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
  mocks.isSessionRefreshRejected.mockReturnValue(false)
})

describe('Night Shift shared surfaces (#5980)', () => {
  it('exposes no appearance picker in the expanded desktop sidebar', async () => {
    setViewport(1280)
    renderNavigation()
    const sidebar = await screen.findByRole('navigation', { name: 'Desktop navigation' })
    await waitFor(() => expect(authenticated).toBe(true))

    expect(within(sidebar).queryByRole('group', { name: 'Appearance' })).toBeNull()
    expect(within(sidebar).queryByRole('button', { name: /theme$/i })).toBeNull()
    expect(sidebar.querySelectorAll('[data-theme]')).toHaveLength(0)
    expect(sidebar.textContent).not.toMatch(/Classic|Ink.Gold|Command.Center|Appearance/)
    expect(sidebar.className).toContain('bg-[var(--theme-bg-panel)]')
    expect(sidebar.className).toContain('border-[var(--theme-border)]')
  })

  it('exposes no appearance picker in the collapsed desktop rail', async () => {
    setViewport(800)
    renderNavigation()
    const sidebar = await screen.findByRole('navigation', { name: 'Desktop navigation' })
    await waitFor(() => expect(authenticated).toBe(true))
    expect(sidebar.getAttribute('data-nav-collapsed')).toBe('true')

    expect(within(sidebar).queryByRole('group', { name: 'Appearance' })).toBeNull()
    expect(sidebar.querySelectorAll('[data-theme]')).toHaveLength(0)
  })

  it('exposes no appearance picker in the mobile More tray', async () => {
    setViewport(390)
    renderNavigation()
    await waitFor(() => expect(authenticated).toBe(true))

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'More pages' }))
    const tray = screen.getByRole('navigation', { name: 'More pages' })

    expect(tray.textContent).not.toMatch(/Appearance|Classic|Ink.Gold|Command.Center/)
    expect(tray.querySelectorAll('[data-theme]')).toHaveLength(0)
    expect(tray.className).toContain('border-[var(--theme-border)]')
    expect(tray.className).toContain('bg-[var(--theme-bg-page)]')
    for (const link of within(tray).getAllByRole('link')) {
      expect(link.className).toContain('text-[var(--theme-text-primary)]')
      expect(link.className).toContain('hover:bg-[var(--theme-bg-panel)]')
    }
  })

  it('does not react to obsolete saved appearance values', async () => {
    localStorage.setItem('comic-pile-theme', 'ink-gold')
    document.documentElement.setAttribute('data-theme', 'command-center')
    setViewport(1280)
    renderNavigation()
    const sidebar = await screen.findByRole('navigation', { name: 'Desktop navigation' })
    await waitFor(() => expect(authenticated).toBe(true))

    // Old values may linger in storage or the DOM from a previous build; the
    // rendered shell must contain only semantic Night Shift bindings.
    expect(sidebar.textContent).not.toMatch(/Classic|Ink.Gold|Command.Center|Appearance/)
    expect(sidebar.querySelectorAll('[data-theme]')).toHaveLength(0)
    expect(mocks.patch).not.toHaveBeenCalled()
  })
})

describe('Night Shift semantic surface classes', () => {
  it('binds shared surfaces to the canonical roles', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8')
    expect(css).toContain('.surface-panel {\n  background: var(--theme-bg-panel);')
    expect(css).toContain('.surface-glass {\n  background: var(--theme-bg-panel);')
    expect(css).toContain('.surface-modal {\n  background: var(--theme-bg-panel);')
    expect(css).toContain('.form-control:focus {\n  outline: none;\n  border-color: var(--theme-focus-ring);')
    expect(css).not.toContain('rgba(17, 14, 10, 0.95)')
  })
})
