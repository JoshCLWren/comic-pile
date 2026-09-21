import { AxiosError } from 'axios'

export type AuthStatus =
  | 'checking'
  | 'authenticated'
  | 'unauthenticated'
  | 'service_unavailable'
  | 'network_error'

export interface AuthState {
  status: AuthStatus
  isLoading: boolean
  user: AuthUser | null
  error: AuthError | null
  retryCount: number
  lastRetryAt: number | null
}

export interface AuthError {
  type: 'network' | 'service_unavailable' | 'definitive_auth_failure'
  message: string
  status?: number
  retryAfter?: number
}

export function isDefinitiveAuthenticationFailure(error: unknown): boolean {
  if (!axios.isAxiosError(error)) {
    return false
  }

  return error.response?.status === 401
}

export function isServiceUnavailable(error: unknown): boolean {
  if (!axios.isAxiosError(error)) {
    return false
  }

  return error.response?.status === 503 || error.code === 'ECONNABORTED'
}

export function isNetworkError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) {
    return false
  }

  return !error.response || error.code === 'NETWORK_ERROR' || error.code === 'ERR_NETWORK'
}

export function createAuthError(error: unknown): AuthError | null {
  if (isDefinitiveAuthenticationFailure(error)) {
    return {
      type: 'definitive_auth_failure',
      message: 'Authentication failed. Please login again.',
      status: 401,
    }
  }

  if (isServiceUnavailable(error)) {
    return {
      type: 'service_unavailable',
      message: 'ComicPile is temporarily unavailable',
      status: 503,
    }
  }

  if (isNetworkError(error)) {
    return {
      type: 'network',
      message: "Can't reach ComicPile",
    }
  }

  return null
}

export function calculateRetryDelay(attempt: number, baseDelay: number = 1000): number {
  // Exponential backoff with jitter: baseDelay * 2^(attempt-1) + random jitter
  const exponentialDelay = baseDelay * Math.pow(2, attempt - 1)
  const jitter = Math.random() * exponentialDelay * 0.1 // 10% jitter
  return Math.min(exponentialDelay + jitter, 30000) // Cap at 30 seconds
}