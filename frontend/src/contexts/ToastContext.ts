import { createContext } from 'react'
export { ToastProvider } from './ToastProvider'
export { useToast } from './ToastProvider'

type ToastType = 'info' | 'success' | 'warning' | 'error'

type Toast = {
  id: string
  message: string
  type: ToastType
}

export type ToastContextType = {
  toasts: Toast[]
  showToast: (message: string, type?: ToastType) => void
  removeToast: (id: string) => void
}

export const ToastContext = createContext<ToastContextType | undefined>(undefined)