import { render, screen, waitFor, within } from './testingLibrary'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { AuthProvider } from '../App'
import Navigation from '../components/Navigation'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { NavCollapseProvider } from '../contexts/NavCollapseContext'
import { ToastProvider } from '../contexts/ToastProvider'
import { cast } from '../utils/cast'
import api, * as authTransport from '../services/api'

const originalApiMethods = { get: api.get, post: api.post }
const mockApiGet = vi.fn<typeof api.get>()
const mockApiPost = vi.fn<typeof api.post>()
const mockSetAccessToken = vi.fn<typeof authTransport.setAccessToken>()
const mockClearAccessToken = vi.fn<typeof authTransport.clearAccessToken>()
const mockGetAccessToken = vi.fn<typeof authTransport.getAccessToken>(() => 'test-token')
const mockRefreshSession = vi.fn<typeof authTransport.refreshSession>()
const mockIsSessionRefreshRejected = vi.fn<typeof authTransport.isSessionRefreshRejected>()

beforeEach(() => {
  Object.assign(api, { get: mockApiGet, post: mockApiPost })
  vi.spyOn(authTransport, 'setAccessToken').mockImplementation(mockSetAccessToken)
  vi.spyOn(authTransport, 'clearAccessToken').mockImplementation(mockClearAccessToken)
  vi.spyOn(authTransport, 'getAccessToken').mockImplementation(mockGetAccessToken)
  vi.spyOn(authTransport, 'refreshSession').mockImplementation(mockRefreshSession)
  vi.spyOn(authTransport, 'isSessionRefreshRejected').mockImplementation(mockIsSessionRefreshRejected)
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    value: 390,
  })
  window.matchMedia = vi.fn((query: string) => {
    if (query === '(max-width: 767px)') return cast<MediaQueryList>({ matches: true, addListener: vi.fn(), removeListener: vi.fn() })
    if (query.includes('min-width: 768px')) return cast<MediaQueryList>({ matches: false, addListener: vi.fn(), removeListener: vi.fn() })
    if (query.includes('min-width: 1024px')) return cast<MediaQueryList>({ matches: false, addListener: vi.fn(), removeListener: vi.fn() })
    return cast<MediaQueryList>({ matches: false, addListener: vi.fn(), removeListener: vi.fn() })
  })
  window.dispatchEvent(new Event('resize'))
  mockApiGet.mockReset()
  mockApiPost.mockReset()
  mockSetAccessToken.mockReset()
  mockClearAccessToken.mockReset()
  mockGetAccessToken.mockReset()
  mockRefreshSession.mockReset()
  mockIsSessionRefreshRejected.mockReset()
  mockGetAccessToken.mockReturnValue('test-token')
  mockIsSessionRefreshRejected.mockReturnValue(false)
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  mockSetAccessToken.mockImplementation(() => undefined)
})

afterEach(() => {
  Object.assign(api, originalApiMethods)
  vi.restoreAllMocks()
})

test('renders recognizable icon primitives in the mobile footer', async () => {
  render(
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
    </MemoryRouter>,
  )

  const mobileNav = await screen.findByRole('navigation', { name: /mobile navigation/i })
  await waitFor(() => {
    expect(within(mobileNav).getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  })
  expect(within(mobileNav).getByText('Roll')).toBeVisible()
  expect(within(mobileNav).getByText('Queue')).toBeVisible()
  expect(within(mobileNav).getByText('History')).toBeVisible()
  expect(within(mobileNav).getByText('Reading plans')).toBeVisible()

  const rollIcon = within(mobileNav).getByRole('link', { name: /roll page/i })
    .querySelector('svg[data-nav-icon="roll"]')
  expect(rollIcon).not.toBeNull()
  expect(rollIcon?.querySelector('rect[rx="4"]')).not.toBeNull()
  expect(rollIcon?.querySelectorAll('circle')).toHaveLength(5)

  const queueIcon = within(mobileNav).getByRole('link', { name: /queue page/i })
    .querySelector('svg[data-nav-icon="queue"]')
  expect(queueIcon).not.toBeNull()
  expect(queueIcon?.querySelectorAll('circle')).toHaveLength(3)
  expect(queueIcon?.querySelectorAll('path')).toHaveLength(3)

  const historyIcon = within(mobileNav).getByRole('link', { name: /history page/i })
    .querySelector('svg[data-nav-icon="history"]')
  expect(historyIcon?.querySelector('path[d^="M3 12a9 9"]')).not.toBeNull()
  expect(historyIcon?.querySelector('path[d="M12 7v5l4 2"]')).not.toBeNull()

  const plansIcon = within(mobileNav).getByRole('link', { name: /reading plans page/i })
    .querySelector('svg[data-nav-icon="planner"]')
  expect(plansIcon?.querySelector('circle[cx="12"]')).not.toBeNull()
  expect(plansIcon?.querySelector('path[d="m15.5 8.5-2 5-5 2 2-5 5-2Z"]')).not.toBeNull()

  const moreIcon = within(mobileNav).getByRole('button', { name: /more pages/i })
    .querySelector('svg[data-nav-icon="more"]')
  expect(moreIcon).not.toBeNull()
  expect(moreIcon?.querySelectorAll('circle')).toHaveLength(4)
})
