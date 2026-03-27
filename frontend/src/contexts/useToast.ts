import { useContext } from 'react'
import { ToastContext } from './ToastContextTypes'

/**
 * Hook to access the toast notification context.
 * Must be used within a ToastProvider.
 */
export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}
