import { createContext, useContext, useState, useEffect } from 'react'
import type { ReactNode } from 'react'

interface Theme {
  id: string
  name: string
  variables: Record<string, string>
}

interface ThemeContextValue {
  currentTheme: Theme
  themes: Theme[]
  setTheme: (themeId: string) => void
}

const themes: Theme[] = [
  {
    id: 'dark',
    name: 'Dark',
    variables: {
      '--bg-main': '#1a1410',
      '--bg-darker': '#110e0a',
      '--accent-primary': '#d4890e',
      '--accent-red': '#c0392b',
      '--accent-amber': '#d4890e',
      '--glass-bg': 'rgba(255, 255, 255, 0.04)',
      '--glass-border': 'rgba(255, 255, 255, 0.08)',
      '--glass-blur': 'blur(12px)',
      '--text-primary': '#e8d5b0',
      '--text-muted': '#a0937e',
      '--text-dim': '#6b5f50',
    },
  },
  {
    id: 'light',
    name: 'Light',
    variables: {
      '--bg-main': '#ffffff',
      '--bg-darker': '#f5f5f5',
      '--accent-primary': '#d4890e',
      '--accent-red': '#c0392b',
      '--accent-amber': '#d4890e',
      '--glass-bg': 'rgba(0, 0, 0, 0.04)',
      '--glass-border': 'rgba(0, 0, 0, 0.08)',
      '--glass-blur': 'blur(12px)',
      '--text-primary': '#1a1410',
      '--text-muted': '#6b5f50',
      '--text-dim': '#a0937e',
    },
  },
]

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [currentThemeId, setCurrentThemeId] = useState('dark')

  // Load saved theme from localStorage
  useEffect(() => {
    const savedTheme = localStorage.getItem('theme') || 'dark'
    setCurrentThemeId(savedTheme)
  }, [])

  // Save theme to localStorage when it changes
  useEffect(() => {
    localStorage.setItem('theme', currentThemeId)
  }, [currentThemeId])

  const currentTheme = themes.find(theme => theme.id === currentThemeId) || themes[0]

  // Apply theme variables to document root
  useEffect(() => {
    const root = document.documentElement
    Object.entries(currentTheme.variables).forEach(([key, value]) => {
      root.style.setProperty(key, value)
    })
  }, [currentTheme])

  const setTheme = (themeId: string) => {
    setCurrentThemeId(themeId)
  }

  return (
    <ThemeContext.Provider value={{ currentTheme, themes, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}