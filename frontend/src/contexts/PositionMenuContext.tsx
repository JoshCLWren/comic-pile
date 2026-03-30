import { createContext } from 'react'

export interface PositionMenuContextType {
  openThreadId: number | null
  openMenu: (threadId: number) => void
  closeMenu: () => void
  toggleMenu: (threadId: number) => void
}

export const PositionMenuContext = createContext<PositionMenuContextType | undefined>(undefined)

// Re-export from PositionMenuProvider for convenience
export { PositionMenuProvider } from './PositionMenuProvider'
