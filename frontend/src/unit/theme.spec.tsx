import { fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import { expect, test, beforeEach, vi } from 'vitest'
import { ThemeProvider, useTheme } from '../contexts/ThemeContext'
import type { ReactNode } from 'react'
import { ThemeId, DEFAULT_THEME, SUPPORTED_THEMES, isValidThemeId } from '../types/theme'

const mockApiGet = vi.fn()
const mockApiPatch = vi.fn()
const mockGetAccessToken = vi.fn(() => 'test-token')

vi.mock('../services/api', () => ({
  default: {
    get: (...args: Parameters<typeof mockApiGet>) => mockApiGet(...args),
    patch: (...args: Parameters<typeof mockApiPatch>) => mockApiPatch(...args),
  },
  getAccessToken: () => mockGetAccessToken(),
  setAccessToken: vi.fn(),
  clearAccessToken: vi.fn(),
}))

const THEME_STORAGE_KEY = 'comic-pile-theme'

function TestComponent({ children }: { children?: ReactNode }) {
  const { theme, isLoading, setTheme, supportedThemes } = useTheme()
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="is-loading">{String(isLoading)}</span>
      <span data-testid="supported-themes">{supportedThemes.join(',')}</span>
      <button data-testid="set-theme-classic" onClick={() => setTheme('classic')}>Set Classic</button>
      <button data-testid="set-theme-ink-gold" onClick={() => setTheme('ink-gold')}>Set Ink Gold</button>
      <button data-testid="set-theme-command-center" onClick={() => setTheme('command-center')}>Set Command Center</button>
      <button data-testid="set-theme-invalid" onClick={() => setTheme('invalid' as ThemeId)}>Set Invalid</button>
      {children}
    </div>
  )
}

function renderWithTheme(
  ui: ReactNode,
  options: { initialTheme?: ThemeId; localStorageTheme?: ThemeId | null } = {}
) {
  const { initialTheme = DEFAULT_THEME, localStorageTheme } = options

  if (localStorageTheme !== undefined) {
    if (localStorageTheme) {
      localStorage.setItem(THEME_STORAGE_KEY, localStorageTheme)
    } else {
      localStorage.removeItem(THEME_STORAGE_KEY)
    }
  }

  return render(
    <ThemeProvider initialTheme={initialTheme}>
      {ui}
    </ThemeProvider>
  )
}

beforeEach(() => {
  localStorage.clear()
  mockApiGet.mockReset()
  mockApiPatch.mockReset()
  mockGetAccessToken.mockReset()
  mockGetAccessToken.mockReturnValue('test-token')
  mockApiGet.mockResolvedValue({ theme: 'classic', user_id: 1 })
  mockApiPatch.mockResolvedValue({ theme: 'ink-gold', user_id: 1 })
  document.documentElement.removeAttribute('data-theme')
})

afterEach(() => {
  localStorage.clear()
  vi.resetAllMocks()
})

describe('isValidThemeId', () => {
  test('returns true for supported themes', () => {
    expect(isValidThemeId('classic')).toBe(true)
    expect(isValidThemeId('ink-gold')).toBe(true)
    expect(isValidThemeId('command-center')).toBe(true)
  })

  test('returns false for unsupported themes', () => {
    expect(isValidThemeId('dark')).toBe(false)
    expect(isValidThemeId('light')).toBe(false)
    expect(isValidThemeId('')).toBe(false)
    expect(isValidThemeId(null)).toBe(false)
    expect(isValidThemeId(undefined)).toBe(false)
    expect(isValidThemeId(123)).toBe(false)
  })
})

describe('DEFAULT_THEME and SUPPORTED_THEMES', () => {
  test('has classic as default', () => {
    expect(DEFAULT_THEME).toBe('classic')
  })

  test('includes all three themes', () => {
    expect(SUPPORTED_THEMES).toEqual(['classic', 'ink-gold', 'command-center'])
  })
})

describe('ThemeProvider', () => {
  test('provides default theme when no localStorage or initialTheme', () => {
    renderWithTheme(<TestComponent />)
    expect(screen.getByTestId('theme').textContent).toBe('classic')
    expect(screen.getByTestId('is-loading').textContent).toBe('true')
  })

  test('uses initialTheme when provided and no localStorage', () => {
    renderWithTheme(<TestComponent />, { initialTheme: 'ink-gold' })
    expect(screen.getByTestId('theme').textContent).toBe('ink-gold')
  })

  test('prefers localStorage theme over initialTheme', () => {
    renderWithTheme(<TestComponent />, { initialTheme: 'classic', localStorageTheme: 'command-center' })
    expect(screen.getByTestId('theme').textContent).toBe('command-center')
  })

  test('applies theme to document.documentElement immediately', () => {
    renderWithTheme(<TestComponent />, { initialTheme: 'ink-gold' })
    expect(document.documentElement.getAttribute('data-theme')).toBe('ink-gold')
  })

  test('provides supportedThemes list', () => {
    renderWithTheme(<TestComponent />)
    expect(screen.getByTestId('supported-themes').textContent).toBe('classic,ink-gold,command-center')
  })

  test('sets isLoading to true initially', () => {
    renderWithTheme(<TestComponent />)
    expect(screen.getByTestId('is-loading').textContent).toBe('true')
  })
})

describe('setTheme', () => {
  test('updates theme state immediately on success', async () => {
    function TestWithSetTheme() {
      const { theme, setTheme } = useTheme()
      return (
        <div>
          <span data-testid="theme">{theme}</span>
          <button data-testid="set-theme-ink-gold" onClick={() => setTheme('ink-gold')}>Set Ink Gold</button>
        </div>
      )
    }
    renderWithTheme(<TestWithSetTheme />)
    
    await act(async () => {
      fireEvent.click(screen.getByTestId('set-theme-ink-gold'))
    })
    await waitFor(() => {
      expect(mockApiPatch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'ink-gold' }, { skipAuthRedirect: true })
    })
    await waitFor(() => {
      expect(screen.getByTestId('theme').textContent).toBe('ink-gold')
    })
    expect(document.documentElement.getAttribute('data-theme')).toBe('ink-gold')
  })

  test('updates localStorage on successful theme change', async () => {
    function TestWithSetTheme() {
      const { setTheme } = useTheme()
      return (
        <div>
          <button data-testid="set-theme-command-center" onClick={() => setTheme('command-center')}>Set Command Center</button>
        </div>
      )
    }
    renderWithTheme(<TestWithSetTheme />)
    
    await act(async () => {
      fireEvent.click(screen.getByTestId('set-theme-command-center'))
    })
    await waitFor(() => {
      expect(mockApiPatch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'command-center' }, { skipAuthRedirect: true })
    })
    await waitFor(() => {
      expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('command-center')
    })
  })

  test('does not update theme for invalid theme id', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    
    renderWithTheme(<TestComponent />)
    
    await act(async () => {
      fireEvent.click(screen.getByTestId('set-theme-invalid'))
    })

    expect(screen.getByTestId('theme').textContent).toBe('classic')
    expect(consoleSpy).toHaveBeenCalledWith('Invalid theme id: invalid')
    consoleSpy.mockRestore()
  })

  test('applies theme to document.documentElement when changed', async () => {
    function TestWithSetTheme() {
      const { setTheme } = useTheme()
      return (
        <div>
          <button data-testid="set-theme-ink-gold" onClick={() => setTheme('ink-gold')}>Set Ink Gold</button>
        </div>
      )
    }
    renderWithTheme(<TestWithSetTheme />)
    
    await act(async () => {
      fireEvent.click(screen.getByTestId('set-theme-ink-gold'))
    })
    await waitFor(() => {
      expect(mockApiPatch).toHaveBeenCalledWith('/v1/users/me/preferences', { theme: 'ink-gold' }, { skipAuthRedirect: true })
    })
    await waitFor(() => {
      expect(document.documentElement.getAttribute('data-theme')).toBe('ink-gold')
    })
  })
})

describe('theme persistence failure handling', () => {
  test('does not throw when setTheme is called with valid theme', async () => {
    renderWithTheme(<TestComponent />)
    
    await expect(
      act(async () => {
        fireEvent.click(screen.getByTestId('set-theme-ink-gold'))
      })
    ).resolves.not.toThrow()
  })
})

describe('unknown/stale theme values', () => {
  test('ignores invalid localStorage value and falls back to initialTheme', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'unknown-theme')
    renderWithTheme(<TestComponent />, { initialTheme: 'classic' })
    expect(screen.getByTestId('theme').textContent).toBe('classic')
  })

  test('ignores malformed localStorage value', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'not-a-theme')
    renderWithTheme(<TestComponent />, { initialTheme: 'ink-gold' })
    expect(screen.getByTestId('theme').textContent).toBe('ink-gold')
  })
})

describe('ThemeContext integration with Navigation', () => {
  test('exposes theme and setTheme through useTheme hook', () => {
    function TestHookComponent() {
      const { theme, setTheme, supportedThemes, isLoading } = useTheme()
      return (
        <div>
          <span data-testid="theme">{theme}</span>
          <span data-testid="is-loading">{String(isLoading)}</span>
          <span data-testid="supported-count">{supportedThemes.length}</span>
          <button onClick={() => setTheme('ink-gold')}>Change</button>
        </div>
      )
    }

    renderWithTheme(<TestHookComponent />)
    expect(screen.getByTestId('theme').textContent).toBe('classic')
    expect(screen.getByTestId('supported-count').textContent).toBe('3')
  })
})