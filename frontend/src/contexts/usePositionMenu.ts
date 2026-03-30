import { useContext } from 'react'
import { PositionMenuContext } from './PositionMenuContext'

export function usePositionMenu() {
  const context = useContext(PositionMenuContext)
  if (!context) {
    throw new Error('usePositionMenu must be used within a PositionMenuProvider')
  }
  return context
}
