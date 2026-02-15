import { createContext, useContext, useState, ReactNode } from 'react'

interface SessionData {
  id: number
  current_die: number
  last_rolled_result: number | null
  manual_die: number | null
  snoozed_threads: Array<{ id: number; title: string }>
}

interface SessionContextValue {
  currentSession: SessionData | null
  setCurrentSession: (session: SessionData | null) => void
  hasRestorePoint: boolean
  setHasRestorePoint: (hasRestore: boolean) => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

interface SessionProviderProps {
  children: ReactNode
}

export const SessionProvider = ({ children }: SessionProviderProps) => {
  const [currentSession, setCurrentSession] = useState<SessionData | null>(null)
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

export const useSessionContext = () => {
  const context = useContext(SessionContext)
  if (!context) {
    throw new Error('useSessionContext must be used within a SessionProvider')
  }
  return context
}
