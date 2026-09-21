import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ExclamationTriangleIcon, ArrowPathIcon } from '@heroicons/react/24/outline'

interface DegradedServiceStateProps {
  type: 'service_unavailable' | 'network_error'
  message?: string
  onRetry: () => void
  isRetrying?: boolean
  className?: string
}

export function DegradedServiceState({
  type,
  message,
  onRetry,
  isRetrying = false,
  className = '',
}: DegradedServiceStateProps) {
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    // Fade in animation
    setIsVisible(true)
  }, [])

  const defaultMessages = {
    service_unavailable: 'ComicPile is temporarily unavailable',
    network_error: "Can't reach ComicPile",
  }

  const displayMessage = message || defaultMessages[type]

  return (
    <div
      className={`fixed inset-x-0 top-0 z-[100] flex items-center justify-center p-4 transition-opacity duration-300 ${
        isVisible ? 'opacity-100' : 'opacity-0'
      } ${className}`}
    >
      <div className="w-full max-w-md rounded-xl border border-stone-200 bg-white p-6 shadow-lg">
        <div className="flex items-center space-x-3">
          <ExclamationTriangleIcon className="h-8 w-8 text-amber-500" />
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-stone-900">
              {type === 'service_unavailable' ? 'Service Unavailable' : 'Connection Issue'}
            </h3>
            <p className="mt-1 text-sm text-stone-600">{displayMessage}</p>
            <p className="mt-2 text-xs text-stone-500">
              Your session is still active. You don't need to login again.
            </p>
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={onRetry}
            disabled={isRetrying}
            className="inline-flex items-center rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-stone-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ArrowPathIcon
              className={`mr-2 h-4 w-4 ${isRetrying ? 'animate-spin' : ''}`}
            />
            {isRetrying ? 'Retrying...' : 'Try again'}
          </button>
        </div>
      </div>
    </div>
  )
}

interface ServiceUnavailableShellProps {
  children: ReactNode
  serviceUnavailable: boolean
  networkError: boolean
  onRetry: () => void
  isRetrying?: boolean
}

export function ServiceUnavailableShell({
  children,
  serviceUnavailable,
  networkError,
  onRetry,
  isRetrying = false,
}: ServiceUnavailableShellProps) {
  if (serviceUnavailable || networkError) {
    return (
      <>
        {children}
        <DegradedServiceState
          type={serviceUnavailable ? 'service_unavailable' : 'network_error'}
          onRetry={onRetry}
          isRetrying={isRetrying}
        />
      </>
    )
  }

  return <>{children}</>
}