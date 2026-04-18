import { createContext, useCallback, useContext, useState } from 'react'
import type { ReactNode } from 'react'

type RestoreAction = (() => void) | null

interface BugReportRestoreContextValue {
  setRestoreAction: (action: RestoreAction) => void
  clearRestoreAction: () => void
  restoreLastView: () => void
}

const BugReportRestoreContext = createContext<BugReportRestoreContextValue | undefined>(undefined)

export function BugReportRestoreProvider({ children }: { children: ReactNode }) {
  const [restoreAction, setRestoreActionState] = useState<RestoreAction>(null)

  const setRestoreAction = useCallback((action: RestoreAction) => {
    setRestoreActionState(() => action)
  }, [])

  const clearRestoreAction = useCallback(() => {
    setRestoreActionState(null)
  }, [])

  const restoreLastView = useCallback(() => {
    restoreAction?.()
  }, [restoreAction])

  return (
    <BugReportRestoreContext.Provider
      value={{
        setRestoreAction,
        clearRestoreAction,
        restoreLastView,
      }}
    >
      {children}
    </BugReportRestoreContext.Provider>
  )
}

export function useBugReportRestore() {
  const context = useContext(BugReportRestoreContext)
  if (!context) {
    throw new Error('useBugReportRestore must be used within a BugReportRestoreProvider')
  }
  return context
}
