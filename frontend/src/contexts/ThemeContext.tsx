import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import { ThemeId, DEFAULT_THEME, isValidThemeId, SUPPORTED_THEMES } from '../types/theme'
import type { UserPreferences } from '../types'
import api from '../services/api'

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

    try {
      await api.patch<UserPreferences>('/users/me/preferences', { theme: newTheme })
      setThemeState(newTheme)
      applyTheme(newTheme)
      writeCachedTheme(newTheme)
    } catch (error) {
      console.error('Failed to persist theme preference:', error)
      throw error
    }
  }, [applyTheme])

  // Fetch user's persisted theme from server and sync
  useEffect(() => {
    let isMounted = true

    api.get<UserPreferences>('/users/me/preferences', { skipAuthRedirect: true })
      .then((response) => {
        if (isMounted && isValidThemeId(response.theme)) {
          const serverTheme = response.theme
          if (serverTheme !== theme) {
            setThemeState(serverTheme)
            applyTheme(serverTheme)
            writeCachedTheme(serverTheme)
          }
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
  }, [applyTheme, theme])

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
