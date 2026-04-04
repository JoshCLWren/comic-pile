import { createContext, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import type { SessionCurrent } from '../types'

interface SessionContextValue {
  currentSession: SessionCurrent | null
  setCurrentSession: Dispatch<SetStateAction<SessionCurrent | null>>
  hasRestorePoint: boolean
  setHasRestorePoint: Dispatch<SetStateAction<boolean>>
}

export const SessionContext = createContext<SessionContextValue | null>(null)

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
