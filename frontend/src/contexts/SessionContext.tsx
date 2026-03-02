import { createContext, useState } from 'react'

const SessionContext = createContext(null)

export const SessionProvider = ({ children }) => {
  const [currentSession, setCurrentSession] = useState(null)
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
