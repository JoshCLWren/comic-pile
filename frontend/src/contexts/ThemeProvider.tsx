import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import api from '../services/api'

export type ThemeId = 'classic' | 'ink-gold' | 'command-center'

export const THEME_IDS: ThemeId[] = ['classic', 'ink-gold', 'command-center']

export const THEME_LABELS: Record<ThemeId, string> = {
  classic: 'Classic',
  'ink-gold': 'Ink & Gold',
  'command-center': 'Command Center',
}

interface ThemeContextValue {
  theme: ThemeId
  isLoaded: boolean
  setTheme: (theme: ThemeId) => Promise<void>
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

const defaultThemeContext: ThemeContextValue = {
  theme: 'classic',
  isLoaded: true,
  setTheme: async () => {},
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme() {
  return useContext(ThemeContext) ?? defaultThemeContext
}

function applyThemeToDocument(theme: ThemeId) {
  document.documentElement.setAttribute('data-theme', theme)
}

interface PreferencesResponse {
  theme: ThemeId
}

interface PreferencesUpdate {
  theme: ThemeId
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>('classic')
  const [isLoaded, setIsLoaded] = useState(false)
  const pendingRef = useRef<ThemeId | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<PreferencesResponse>('/v1/users/me/preferences', { skipAuthRedirect: true })
      .then((data) => {
        if (cancelled) return
        const resolved = THEME_IDS.includes(data.theme) ? data.theme : 'classic'
        setThemeState(resolved)
        applyThemeToDocument(resolved)
      })
      .catch(() => {
        if (cancelled) return
        applyThemeToDocument('classic')
      })
      .finally(() => {
        if (!cancelled) setIsLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const setTheme = useCallback(
    async (next: ThemeId) => {
      applyThemeToDocument(next)
      setThemeState(next)
      pendingRef.current = next
      try {
        const response = await api.patch<PreferencesResponse, PreferencesUpdate>(
          '/v1/users/me/preferences',
          { theme: next },
        )
        if (pendingRef.current === next) {
          setThemeState(response.theme)
        }
      } catch {
        // Failed preference save: revert to previous server state.
        // Do not strand the app in an unusable state.
        try {
          const fallback = await api.get<PreferencesResponse>('/v1/users/me/preferences', {
            skipAuthRedirect: true,
          })
          const resolved = THEME_IDS.includes(fallback.theme) ? fallback.theme : 'classic'
          setThemeState(resolved)
          applyThemeToDocument(resolved)
        } catch {
          // If even the read fails, keep the optimistic local theme.
        }
      } finally {
        if (pendingRef.current === next) {
          pendingRef.current = null
        }
      }
    },
    [],
  )

  return (
    <ThemeContext.Provider value={{ theme, isLoaded, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}
