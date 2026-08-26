import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, beforeEach, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
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

vi.mock('../services/api', () => {
  return {
    default: {
      get: (...args: Parameters<typeof mockApiGet>) => mockApiGet(...args),
      post: (...args: Parameters<typeof mockApiPost>) => mockApiPost(...args),
    },
    setAccessToken: (...args: Parameters<typeof mockSetAccessToken>) => mockSetAccessToken(...args),
    clearAccessToken: (...args: Parameters<typeof mockClearAccessToken>) => mockClearAccessToken(...args),
    getAccessToken: () => mockGetAccessToken(),
  }
})

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
})

const renderWithAuth = (initialEntry = '/') => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  mockSetAccessToken.mockImplementation(() => undefined)

  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>
  )
}

const renderWithoutAuth = () => {
  mockApiGet.mockRejectedValue(new Error('unauthenticated'))
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>
  )
}

test('renders retained navigation links when authenticated', async () => {
  renderWithAuth()

  await waitFor(() => {
    const mobileNav = screen.getByRole('navigation', { name: /mobile navigation/i })
    expect(within(mobileNav).getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  })
  const mobileNav = screen.getByRole('navigation', { name: /mobile navigation/i })
  expect(within(mobileNav).getByRole('link', { name: /queue page/i })).toBeInTheDocument()
  expect(within(mobileNav).getByRole('link', { name: /history page/i })).toBeInTheDocument()
  expect(within(mobileNav).getByRole('link', { name: /crossovers page/i })).toBeInTheDocument()
  expect(within(mobileNav).getByText('Roll')).toBeVisible()
  expect(within(mobileNav).getByText('Queue')).toBeVisible()
  expect(within(mobileNav).getByText('History')).toBeVisible()
  expect(within(mobileNav).getByText('Crossovers')).toBeVisible()
  expect(within(mobileNav).getByText('More')).toBeVisible()
  expect(within(mobileNav).queryByRole('link', { name: /analytics page/i })).not.toBeInTheDocument()
})

test('marks More as the only active destination on submenu routes', async () => {
  renderWithAuth('/glossary')

  const moreButton = await screen.findByRole('button', { name: /more pages/i })
  expect(moreButton).toHaveClass('active')
  expect(document.querySelectorAll('.nav-item.active')).toHaveLength(1)
})

test('dismisses the More tray only when tapping outside it', async () => {
  renderWithAuth()
  const user = userEvent.setup()
  const moreButton = await screen.findByRole('button', { name: /more pages/i })

  await user.click(moreButton)
  const moreNavigation = screen.getByRole('navigation', { name: /more pages/i })
  expect(moreButton).toHaveAttribute('aria-expanded', 'true')

  fireEvent.pointerDown(within(moreNavigation).getByRole('link', { name: /help/i }))
  expect(moreNavigation).toBeInTheDocument()
  expect(moreButton).toHaveAttribute('aria-expanded', 'true')

  fireEvent.pointerDown(moreButton)
  expect(moreNavigation).toBeInTheDocument()
  expect(moreButton).toHaveAttribute('aria-expanded', 'true')

  fireEvent.pointerDown(document.body)
  await waitFor(() => expect(moreButton).toHaveAttribute('aria-expanded', 'false'))
  expect(screen.queryByRole('navigation', { name: /more pages/i })).not.toBeInTheDocument()
})

test('does not render when not authenticated', async () => {
  const { container } = renderWithoutAuth()

  await waitFor(() => {
    expect(container).toBeEmptyDOMElement()
  })
})

test('puts the mobile Sign out action inside More', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  renderWithAuth()
  const user = userEvent.setup()

  expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument()
  await user.click(await screen.findByRole('button', { name: /more pages/i }))
  expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
})

test('shows loading and non-auth failure states and logs out gracefully', async () => {
  mockApiGet.mockResolvedValueOnce({ username: 'user', email: 'user@example.com' })
    .mockRejectedValueOnce(new Error('server unavailable'))
    .mockRejectedValueOnce(new Error('server unavailable'))
  render(
    <MemoryRouter initialEntries={['/queue']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /more pages/i }))
  mockApiPost.mockRejectedValueOnce(new Error('logout unavailable'))
  await user.click(screen.getByRole('button', { name: /sign out/i }))
  await waitFor(() => expect(mockClearAccessToken).toHaveBeenCalled())

})

test('clears authentication when the user lookup returns unauthorized', async () => {
  mockApiGet.mockResolvedValueOnce({ username: 'user', email: 'user@example.com' })
    .mockRejectedValueOnce({ isAxiosError: true, response: { status: 401 } })
    .mockRejectedValueOnce({ isAxiosError: true, response: { status: 401 } })
  render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  await waitFor(() => expect(mockClearAccessToken).toHaveBeenCalled())
})

test('falls back to an empty username when the user profile omits it', async () => {
  // L43 `setUsername(user.username || '')` — username falsy
  mockApiGet.mockResolvedValue({ username: '', email: 'empty@test.com' })
  render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByRole('button', { name: /more pages/i })).toBeInTheDocument())
  // empty username is falsy, so no username span is rendered for it
  expect(screen.queryByText('testuser')).not.toBeInTheDocument()
})

test('renders all secondary nav links inline on a desktop viewport', async () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
  window.dispatchEvent(new Event('resize'))
  renderWithAuth()

  await waitFor(() => {
    const desktopNav = screen.getByRole('navigation', { name: /desktop navigation/i })
    expect(within(desktopNav).getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  })
  const desktopNav = screen.getByRole('navigation', { name: /desktop navigation/i })
  expect(within(desktopNav).getByRole('link', { name: /queue page/i })).toBeInTheDocument()
  expect(within(desktopNav).getByRole('link', { name: /history page/i })).toBeInTheDocument()
  expect(within(desktopNav).getByRole('link', { name: /crossovers page/i })).toBeInTheDocument()
  expect(within(desktopNav).getByRole('link', { name: /continuity planner page/i })).toBeInTheDocument()
  expect(within(desktopNav).getByRole('link', { name: /what's new page/i })).toBeInTheDocument()
  expect(within(desktopNav).getByRole('link', { name: /help page/i })).toBeInTheDocument()
  expect(within(desktopNav).getByRole('link', { name: /glossary page/i })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /more pages/i })).not.toBeInTheDocument()
})
