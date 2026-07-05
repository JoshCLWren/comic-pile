import { useState, type ReactNode } from 'react'
import type { SessionCurrent } from '../types'
import { SessionContext } from './SessionContextValue'

interface SessionProviderProps {
  children: ReactNode
}

export const SessionProvider = ({ children }: SessionProviderProps) => {
  const [currentSession, setCurrentSession] = useState<SessionCurrent | null>(null)
  const [hasRestorePoint, setHasRestorePoint] = useState(false)

  return (
    <SessionContext.Provider
      value={{
        currentSession,
        setCurrentSession,
        hasRestorePoint,
        setHasRestorePoint,
      }}
    >
      {children}
    </SessionContext.Provider>
  )
}
