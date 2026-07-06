import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'
import { BugReportRestoreContext, type RestoreAction } from './BugReportRestoreContextValue'

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

