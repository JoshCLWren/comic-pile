import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import { ThemeId, DEFAULT_THEME, isValidThemeId, SUPPORTED_THEMES } from '../types/theme'
import type { UserPreferences } from '../types'
import api, { getAccessToken, preferencesApi } from '../services/api'

const THEME_STORAGE_KEY = 'comic-pile-theme'

function readCachedTheme(): ThemeId | null {
  if (typeof window === 'undefined') return null
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    if (stored && isValidThemeId(stored)) {
      return stored
    }
  } catch {
    // localStorage unavailable
  }
  return null
}

function writeCachedTheme(theme: ThemeId): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // localStorage unavailable
  }
}

interface ThemeContextValue {
  theme: ThemeId
  isLoading: boolean
  setTheme: (theme: ThemeId) => Promise<void>
  supportedThemes: readonly ThemeId[]
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}

interface ThemeProviderProps {
  children: ReactNode
  initialTheme?: ThemeId
}

export function ThemeProvider({ children, initialTheme = DEFAULT_THEME }: ThemeProviderProps) {
  const cachedTheme = readCachedTheme()
  const effectiveInitialTheme = cachedTheme ?? initialTheme

  const [theme, setThemeState] = useState<ThemeId>(effectiveInitialTheme)
  const [isLoading, setIsLoading] = useState(true)
  const hasAppliedInitialTheme = useRef(false)
  const userChoseThemeRef = useRef(false)

  const applyTheme = useCallback((newTheme: ThemeId) => {
    document.documentElement.setAttribute('data-theme', newTheme)
  }, [])

  // Apply initial theme synchronously before first paint
  if (!hasAppliedInitialTheme.current) {
    applyTheme(effectiveInitialTheme)
    hasAppliedInitialTheme.current = true
  }

  const setTheme = useCallback(async (newTheme: ThemeId) => {
    if (!isValidThemeId(newTheme)) {
      console.error(`Invalid theme id: ${newTheme}`)
      return
    }

    userChoseThemeRef.current = true

    try {
      await preferencesApi.patch({ theme: newTheme })
      setThemeState(newTheme)
      applyTheme(newTheme)
      writeCachedTheme(newTheme)
    } catch (error) {
      console.error('Failed to persist theme preference:', error)
      throw error
    }
  }, [applyTheme])

  // Fetch the authenticated user's persisted theme from the server and sync.
  // The endpoint requires auth, so skip the probe when no access token exists.
  // This effect runs once on mount; a stale response must never override a
  // theme the user explicitly chose in this session.
  useEffect(() => {
    let isMounted = true

    if (!getAccessToken()) {
      setIsLoading(false)
      return
    }

    api.get<UserPreferences>('/v1/users/me/preferences', { skipAuthRedirect: true })
      .then((response) => {
      .then((response) => {
        if (isMounted && !userChoseThemeRef.current && isValidThemeId(response.theme)) {
          setThemeState(response.theme)
          applyTheme(response.theme)
          writeCachedTheme(response.theme)
        }
      })
      .catch(() => {
        // Server fetch failed; keep cached/default theme
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [applyTheme])

  // Apply theme when it changes (covers server sync updates)
  useEffect(() => {
    if (hasAppliedInitialTheme.current) {
      applyTheme(theme)
    }
  }, [theme, applyTheme])

  return (
    <ThemeContext.Provider value={{ theme, isLoading, setTheme, supportedThemes: SUPPORTED_THEMES }}>
      {children}
    </ThemeContext.Provider>
  )
}
