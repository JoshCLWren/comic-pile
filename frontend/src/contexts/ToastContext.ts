import { createContext } from 'react'
export { ToastProvider } from './ToastProvider'
export { useToast } from './useToast'

type ToastType = 'info' | 'success' | 'warning' | 'error'

type ToastAction = {
  label: string
  onClick: () => void
}

type Toast = {
  id: string
  message: string
  type: ToastType
}

export type ToastContextType = {
  toasts: Toast[]
  showToast: (message: string, type?: ToastType, action?: ToastAction) => string
  removeToast: (id: string) => void
}

export const ToastContext = createContext<ToastContextType | undefined>(undefined)