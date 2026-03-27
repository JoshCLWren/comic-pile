import { createContext } from 'react'

type ToastType = 'info' | 'success' | 'warning' | 'error'

type Toast = {
  id: string
  message: string
  type: ToastType
}

type ToastContextType = {
  toasts: Toast[]
  showToast: (message: string, type?: ToastType) => void
  removeToast: (id: string) => void
}

export const ToastContext = createContext<ToastContextType | undefined>(undefined)

export type { ToastType, Toast, ToastContextType }