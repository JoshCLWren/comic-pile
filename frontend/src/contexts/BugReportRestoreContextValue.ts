import { createContext } from 'react'

export type RestoreAction = (() => void) | null

export interface BugReportRestoreContextValue {
  setRestoreAction: (action: RestoreAction) => void
  clearRestoreAction: () => void
  restoreLastView: () => void
}

export const BugReportRestoreContext = createContext<BugReportRestoreContextValue | undefined>(undefined)