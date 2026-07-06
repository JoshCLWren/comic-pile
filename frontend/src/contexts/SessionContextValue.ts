import { createContext } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { SessionCurrent } from '../types'

export interface SessionContextValue {
  currentSession: SessionCurrent | null
  setCurrentSession: Dispatch<SetStateAction<SessionCurrent | null>>
  hasRestorePoint: boolean
  setHasRestorePoint: Dispatch<SetStateAction<boolean>>
}

export const SessionContext = createContext<SessionContextValue | null>(null)