/**
 * Shared sidebar polish regressions (#3011, updated for #5980).
 *
 * Night Shift removed the appearance control, so these assertions now guard
 * the remaining product behavior: the brand list and the sidebar footer share
 * one horizontal gutter, the footer stays free of theme-only controls, and
 * the compact rail keeps identity, bug report and logout reachable.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../App'
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
  getAccessToken: vi.fn<() => string | null>(),
  readStoredAccessToken: vi.fn<() => string | null>(),
}))

vi.mock('../services/api', () => {
  const apiMock = { get: mocks.get, post: mocks.post, patch: mocks.patch }
  return {
    default: apiMock,
    api: apiMock,
    clearAccessToken: vi.fn(),
    setAccessToken: vi.fn(),
    getAccessToken: mocks.getAccessToken,
    readStoredAccessToken: mocks.readStoredAccessToken,
    refreshSession: vi.fn(),
    isSessionRefreshRejected: () => false,
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
    return cast<MediaQueryList>({ matches: true, addListener: vi.fn(), removeListener: vi.fn() })
  })
  window.dispatchEvent(new Event('resize'))
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
              </NavCollapseProvider>
            </ToastProvider>
          </BugReportRestoreProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function expandedSidebar() {
  renderNavigation()
  const sidebar = await screen.findByRole('navigation', { name: 'Desktop navigation' })
  await waitFor(() => expect(within(sidebar).getByText('reader')).toBeInTheDocument())
  return sidebar
}

describe('shared sidebar footer stays compact (#3011, #5980)', () => {
  beforeEach(() => {
    localStorage.clear()
    queryClient.clear()
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.patch.mockReset()
    mocks.getAccessToken.mockReset()
    mocks.readStoredAccessToken.mockReset()
    mocks.getAccessToken.mockReturnValue('test-token')
    mocks.readStoredAccessToken.mockReturnValue(null)
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
    setViewport(1280)
  })

  it('keeps one horizontal gutter for the brand list and the sidebar footer', async () => {
    const sidebar = await expandedSidebar()

    const brand = within(sidebar).getByText('Comic Pile')
    const [scroller, footer] = Array.from(sidebar.querySelectorAll(':scope > div'))

    expect(brand.closest('div')?.parentElement).toBe(scroller)
    expect(scroller?.className).toContain('px-4')
    expect(footer?.className).toContain('px-4')
    expect(footer?.className).not.toContain('px-2')
    expect(within(sidebar).getByText('reader').className).toContain('truncate')
  })

  it('keeps logout available without a theme-only control in the footer', async () => {
    const sidebar = await expandedSidebar()
    const [scroller, footer] = Array.from(sidebar.querySelectorAll(':scope > div'))

    expect(within(sidebar).getByRole('button', { name: 'Log out' })).toBeInTheDocument()
    expect(footer?.querySelectorAll('button[data-theme]')).toHaveLength(0)
    expect(within(sidebar).queryByRole('group', { name: /appearance/i })).toBeNull()
    expect(scroller?.textContent).not.toMatch(/Classic|Ink.Gold|Command.Center/)
  })
})
