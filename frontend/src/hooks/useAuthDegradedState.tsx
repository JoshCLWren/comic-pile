import { useAuth } from '../contexts/AuthContext'
import { ServiceUnavailableShell } from '../components/DegradedServiceState'
import type { ReactNode } from 'react'

export function ServiceUnavailableWrapper({ children }: { children: ReactNode }) {
  const { authState, retryAuth } = useAuth()
  const showServiceUnavailable = authState.status === 'service_unavailable'
  const showNetworkError = authState.status === 'network_error'
  return (
    <ServiceUnavailableShell
      serviceUnavailable={showServiceUnavailable}
      networkError={showNetworkError}
      onRetry={retryAuth}
      isRetrying={authState.isLoading}
    >
      {children}
    </ServiceUnavailableShell>
  )
}

export function useAuthDegradedState() {
  const { authState, retryAuth, clearAuthError } = useAuth()

  return {
    authState,
    showServiceUnavailable: authState.status === 'service_unavailable',
    showNetworkError: authState.status === 'network_error',
    isRetrying: authState.isLoading,
    retryAuth,
    clearAuthError,
    ServiceUnavailableWrapper,
  }
}
