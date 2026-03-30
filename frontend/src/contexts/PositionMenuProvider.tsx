import { useState, useCallback, ReactNode } from 'react'
import { PositionMenuContext } from './PositionMenuContext'

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
