import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import type { AuthUser } from '../types'
import type { AuthState } from '../services/authState'

export interface AuthContextValue {
  authState: AuthState
  isAuthenticated: boolean
  isLoading: boolean
  user: AuthUser | null
  login: (accessToken: string) => Promise<void>
  logout: () => void
  revalidateSession: (timeout?: number) => Promise<void>
  recoverSession: (timeout?: number) => Promise<void>
  retryAuth: () => Promise<void>
  clearAuthError: () => void
}

export interface AuthContextLegacyValue {
  isAuthenticated: boolean
  isLoading: boolean
  user: AuthUser | null
}

export const AuthContext = createContext<AuthContextValue | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
