import { createContext } from 'react'

interface PositionMenuContextType {
  openThreadId: number | null
  openMenu: (threadId: number) => void
  closeMenu: () => void
  toggleMenu: (threadId: number) => void
}

export const PositionMenuContext = createContext<PositionMenuContextType | undefined>(undefined)
