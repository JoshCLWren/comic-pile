import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, beforeEach, vi } from 'vitest'
import { ThemeProvider, useTheme, THEME_IDS } from '../contexts/ThemeProvider'
import { AuthProvider } from '../App'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'

const mockApiGet = vi.fn()
const mockApiPost = vi.fn()
const mockApiPatch = vi.fn()
const mockSetAccessToken = vi.fn()
const mockClearAccessToken = vi.fn()
const mockGetAccessToken = vi.fn(() => 'test-token')

vi.mock('../services/api', () => ({
  default: {
    get: (...args: Parameters<typeof mockApiGet>) => mockApiGet(...args),
    post: (...args: Parameters<typeof mockApiPost>) => mockApiPost(...args),
    patch: (...args: Parameters<typeof mockApiPatch>) => mockApiPatch(...args),
  },
  setAccessToken: (...args: Parameters<typeof mockSetAccessToken>) => mockSetAccessToken(...args),
  clearAccessToken: (...args: Parameters<typeof mockClearAccessToken>) => mockClearAccessToken(...args),
  getAccessToken: () => mockGetAccessToken(),
}))

beforeEach(() => {
  mockApiGet.mockReset()
  mockApiPost.mockReset()
  mockApiPatch.mockReset()
  mockSetAccessToken.mockReset()
  mockClearAccessToken.mockReset()
  document.documentElement.removeAttribute('data-theme')
})

function ThemeConsumer() {
  const { theme, isLoaded, setTheme } = useTheme()
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="loaded">{String(isLoaded)}</span>
      <button type="button" onClick={() => { void setTheme('command-center') }}>
        Switch
      </button>
    </div>
  )
}

function renderWithTheme(entry = '/') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AuthProvider>
        <ThemeProvider>
          <BugReportRestoreProvider>
            <ThemeConsumer />
          </BugReportRestoreProvider>
        </ThemeProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

test('defaults to classic when no preferences exist', async () => {
  mockApiGet.mockResolvedValueOnce({ theme: 'classic' })
  mockApiGet.mockResolvedValueOnce({ username: 'testuser' })
  renderWithTheme()

  await waitFor(() => {
    expect(screen.getByTestId('loaded').textContent).toBe('true')
  })
  expect(screen.getByTestId('theme').textContent).toBe('classic')
})

test('applies server theme on load', async () => {
  mockApiGet.mockResolvedValueOnce({ theme: 'ink-gold' })
  mockApiGet.mockResolvedValueOnce({ username: 'testuser' })
  renderWithTheme()

  await waitFor(() => {
    expect(screen.getByTestId('loaded').textContent).toBe('true')
  })
  expect(screen.getByTestId('theme').textContent).toBe('ink-gold')
  expect(document.documentElement.getAttribute('data-theme')).toBe('ink-gold')
})

test('falls back to classic on preferences fetch failure', async () => {
  mockApiGet.mockRejectedValueOnce(new Error('network'))
  mockApiGet.mockResolvedValueOnce({ username: 'testuser' })
  renderWithTheme()

  await waitFor(() => {
    expect(screen.getByTestId('loaded').textContent).toBe('true')
  })
  expect(screen.getByTestId('theme').textContent).toBe('classic')
})

test('setTheme applies immediately and patches server', async () => {
  mockApiGet.mockResolvedValueOnce({ theme: 'classic' })
  mockApiGet.mockResolvedValueOnce({ username: 'testuser' })
  mockApiPatch.mockResolvedValueOnce({ theme: 'command-center' })

  renderWithTheme()
  await waitFor(() => {
    expect(screen.getByTestId('loaded').textContent).toBe('true')
  })

  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Switch' }))

  expect(screen.getByTestId('theme').textContent).toBe('command-center')
  expect(document.documentElement.getAttribute('data-theme')).toBe('command-center')
  expect(mockApiPatch).toHaveBeenCalledWith(
    '/v1/users/me/preferences',
    { theme: 'command-center' },
  )
})

test('reverts on server failure', async () => {
  mockApiGet.mockResolvedValueOnce({ theme: 'classic' })
  mockApiGet.mockResolvedValueOnce({ username: 'testuser' })
  mockApiPatch.mockRejectedValueOnce(new Error('fail'))
  // Fallback GET on failure
  mockApiGet.mockResolvedValueOnce({ theme: 'classic' })

  renderWithTheme()
  await waitFor(() => {
    expect(screen.getByTestId('loaded').textContent).toBe('true')
  })

  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Switch' }))

  await waitFor(() => {
    expect(screen.getByTestId('theme').textContent).toBe('classic')
  })
})

test('all three themes are valid theme IDs', () => {
  expect(THEME_IDS).toEqual(['classic', 'ink-gold', 'command-center'])
})

test('useTheme returns defaults when used outside provider', () => {
  function BareConsumer() {
    const { theme, isLoaded } = useTheme()
    return (
      <div>
        <span data-testid="bare-theme">{theme}</span>
        <span data-testid="bare-loaded">{String(isLoaded)}</span>
      </div>
    )
  }

  render(<BareConsumer />)
  expect(screen.getByTestId('bare-theme').textContent).toBe('classic')
  expect(screen.getByTestId('bare-loaded').textContent).toBe('true')
})
