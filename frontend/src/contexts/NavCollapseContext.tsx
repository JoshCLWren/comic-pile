import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

const STORAGE_KEY = 'comic-pile-nav-collapsed'

interface NavCollapseContextValue {
  collapsed: boolean
  toggleCollapsed: () => void
}

const NavCollapseContext = createContext<NavCollapseContextValue | null>(null)

function getDefaultCollapsed(): boolean {
  if (typeof window === 'undefined') return false
  const w = window.innerWidth
  if (w < 768) return false
  if (w >= 1024) return false
  return true
}

function readStoredCollapse(): boolean | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'true') return true
    if (stored === 'false') return false
  } catch {
    // localStorage unavailable
  }
  return null
}

export function NavCollapseProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    const stored = readStoredCollapse()
    if (stored !== null) return stored
    return getDefaultCollapsed()
  })

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed))
    } catch {
      // localStorage unavailable
    }
  }, [collapsed])

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => !prev)
  }, [])

  return (
    <NavCollapseContext.Provider value={{ collapsed, toggleCollapsed }}>
      {children}
    </NavCollapseContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useNavCollapse(): NavCollapseContextValue {
  const context = useContext(NavCollapseContext)
  if (!context) throw new Error('useNavCollapse must be used within a NavCollapseProvider')
  return context
}
