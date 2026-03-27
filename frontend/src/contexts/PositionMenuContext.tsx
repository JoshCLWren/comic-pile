import { createContext, useContext, useState, useCallback, ReactNode } from 'react'

interface PositionMenuContextType {
  openThreadId: number | null
  openMenu: (threadId: number) => void
  closeMenu: () => void
  toggleMenu: (threadId: number) => void
}

const PositionMenuContext = createContext<PositionMenuContextType | undefined>(undefined)

export function PositionMenuProvider({ children }: { children: ReactNode }) {
  const [openThreadId, setOpenThreadId] = useState<number | null>(null)

  const openMenu = useCallback((threadId: number) => {
    setOpenThreadId(threadId)
  }, [])

  const closeMenu = useCallback(() => {
    setOpenThreadId(null)
  }, [])

  const toggleMenu = useCallback((threadId: number) => {
    setOpenThreadId(prev => prev === threadId ? null : threadId)
  }, [])

  return (
    <PositionMenuContext.Provider value={{ openThreadId, openMenu, closeMenu, toggleMenu }}>
      {children}
    </PositionMenuContext.Provider>
  )
}

export function usePositionMenu() {
  const context = useContext(PositionMenuContext)
  if (!context) {
    throw new Error('usePositionMenu must be used within a PositionMenuProvider')
  }
  return context
}
