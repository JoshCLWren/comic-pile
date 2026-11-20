/**
 * Roll sidebar polish regressions (#3011).
 *
 * The desktop navigation is shared by every authenticated screen, so these
 * assertions guard the two product changes that reach all of them:
 * - the appearance control no longer dominates the sidebar footer, and keeps
 *   the same compact treatment as the collapsed rail;
 * - the brand and user blocks share one horizontal gutter, expanded and
 *   collapsed, and never sit flush against the viewport edge.
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

vi.mock('../services/api-preferences', () => ({
  preferencesApi: {
    get: (options?: { timeout?: number; skipAuthRedirect?: boolean }) =>
      mocks.get('/v1/users/me/preferences', options),
    patch: (data: { theme?: string | null }) => mocks.patch('/v1/users/me/preferences', data),
  },
}))

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
  await waitFor(() =>
    expect(within(sidebar).getByRole('button', { name: 'Classic theme' })).toBeInTheDocument(),
  )
  return sidebar
}

describe('Roll sidebar appearance control stays compact (#3011)', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme')
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

  it('keeps the expanded appearance control on one non-wrapping row', async () => {
    const sidebar = await expandedSidebar()
    const group = within(sidebar).getByRole('group', { name: 'Appearance' })
    const buttons = within(group).getAllByRole('button')
    expect(buttons).toHaveLength(3)

    // The control must not wrap or reflow: no `flex-wrap` on the group, and no
    // nested wrapper that could push the options onto a second line.
    expect(group.className).not.toContain('flex-wrap')
    expect(group.querySelectorAll('button')).toHaveLength(3)
    expect(group.textContent).toContain('Theme')
  })

  it('gives the compact theme options a legible, full-size hit target', async () => {
    const sidebar = await expandedSidebar()
    const group = within(sidebar).getByRole('group', { name: 'Appearance' })
    const buttons = within(group).getAllByRole('button')

    for (const button of buttons) {
      // The expanded control and the collapsed rail are the same control in two
      // states, so they share one typographic and hit-target treatment.
      expect(button.className).toContain('h-7')
      expect(button.className).toContain('w-7')
      expect(button.className).toContain('text-[10px]')
      expect(button.className).not.toMatch(/text-\[[0-9]px\]/)
      // Abbreviated glyphs need a full accessible name and a tooltip.
      expect(button).toHaveAccessibleName()
      expect(button.getAttribute('title')).toBe(button.getAttribute('aria-label'))
    }
  })

  it('keeps one horizontal gutter for the brand list and the sidebar footer', async () => {
    const sidebar = await expandedSidebar()

    const brand = within(sidebar).getByText('Comic Pile')
    const [scroller, footer] = Array.from(sidebar.querySelectorAll(':scope > div'))

    // Brand block and nav list share the expanded gutter...
    expect(brand.closest('div')?.parentElement).toBe(scroller)
    expect(scroller?.className).toContain('px-4')
    // ...and the footer below the divider uses the same one, so the username,
    // appearance control, bug report, and logout all align with the brand.
    expect(footer?.className).toContain('px-4')
    expect(footer?.className).not.toContain('px-2')
    expect(within(sidebar).getByText('reader').className).toContain('truncate')
  })
})
