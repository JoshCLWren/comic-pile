import { useContext } from 'react'
import { BugReportRestoreContext } from './BugReportRestoreContextValue'

export function useBugReportRestore() {
  const context = useContext(BugReportRestoreContext)
  if (!context) {
    throw new Error('useBugReportRestore must be used within a BugReportRestoreProvider')
  }
  return context
}