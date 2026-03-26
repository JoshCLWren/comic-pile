export type ToastType = 'info' | 'success' | 'warning' | 'error'

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