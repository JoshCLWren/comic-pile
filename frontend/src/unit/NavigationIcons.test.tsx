import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import { AuthProvider } from '../App'
import Navigation from '../components/Navigation'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'

vi.mock('../contexts/useToast', () => ({
  useToast: () => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] }),
}))

const mockApiGet = vi.fn()
const mockApiPost = vi.fn()
const mockSetAccessToken = vi.fn()
const mockClearAccessToken = vi.fn()
const mockGetAccessToken = vi.fn(() => 'test-token')

vi.mock('../services/api', () => ({
  default: {
    get: (...args: Parameters<typeof mockApiGet>) => mockApiGet(...args),
    post: (...args: Parameters<typeof mockApiPost>) => mockApiPost(...args),
  },
  setAccessToken: (...args: Parameters<typeof mockSetAccessToken>) => mockSetAccessToken(...args),
  clearAccessToken: (...args: Parameters<typeof mockClearAccessToken>) => mockClearAccessToken(...args),
  getAccessToken: () => mockGetAccessToken(),
}))

beforeEach(() => {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    value: 390,
  })
  window.dispatchEvent(new Event('resize'))
  mockApiGet.mockReset()
  mockApiPost.mockReset()
  mockSetAccessToken.mockReset()
  mockClearAccessToken.mockReset()
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  mockSetAccessToken.mockImplementation(() => undefined)
})

test('renders recognizable icon primitives in the mobile footer', async () => {
  render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>,
  )

  const mobileNav = await screen.findByRole('navigation', { name: /mobile navigation/i })
  await waitFor(() => {
    expect(within(mobileNav).getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  })

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

  const crossoversIcon = within(mobileNav).getByRole('link', { name: /crossovers page/i })
    .querySelector('svg[data-nav-icon="crossovers"]')
  expect(crossoversIcon?.querySelector('path[d="m17 14 3 3-3 3"]')).not.toBeNull()
  expect(crossoversIcon?.querySelector('path[d="m17 4 3 3-3 3"]')).not.toBeNull()

  const moreIcon = within(mobileNav).getByRole('button', { name: /more pages/i })
    .querySelector('svg[data-nav-icon="more"]')
  expect(moreIcon).not.toBeNull()
  expect(moreIcon?.querySelectorAll('circle')).toHaveLength(4)
})
