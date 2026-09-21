import { useAuth } from './App'
import { ServiceUnavailableShell } from '../components/DegradedServiceState'

export function useAuthDegradedState() {
  const { authState, retryAuth, clearAuthError } = useAuth()

  const showServiceUnavailable = authState.status === 'service_unavailable'
  const showNetworkError = authState.status === 'network_error'
  const isRetrying = authState.isLoading

  const ServiceUnavailableWrapper = ({ children }: { children: React.ReactNode }) => (
    <ServiceUnavailableShell
      serviceUnavailable={showServiceUnavailable}
      networkError={showNetworkError}
      onRetry={retryAuth}
      isRetrying={isRetrying}
    >
      {children}
    </ServiceUnavailableShell>
  )

  return {
    authState,
    showServiceUnavailable,
    showNetworkError,
    isRetrying,
    retryAuth,
    clearAuthError,
    ServiceUnavailableWrapper,
  }
}