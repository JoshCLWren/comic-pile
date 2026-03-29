import { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from 'react'

type ToastType = 'info' | 'success' | 'warning' | 'error'

type Toast = {
  id: string
  message: string
  type: ToastType
  action?: { label: string; onClick: () => void }
}

type ToastContextType = {
  toasts: Toast[]
  showToast: (message: string, type?: ToastType, action?: { label: string; onClick: () => void }) => string
  removeToast: (id: string) => void
}

const ToastContext = createContext<ToastContextType | undefined>(undefined)

const TOAST_DURATION = 5000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timeoutIdsRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())

  const showToast = useCallback((message: string, type: ToastType = 'info', action?: { label: string; onClick: () => void }) => {
    const id = `${Date.now()}-${Math.random().toString(36).substring(7)}`
    const newToast: Toast = { id, message, type, action }

    setToasts((prev) => [...prev, newToast])

    const timeoutId = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
      timeoutIdsRef.current.delete(timeoutId)
    }, TOAST_DURATION)

    timeoutIdsRef.current.add(timeoutId)

    return id
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  useEffect(() => {
    const timeoutIds = timeoutIdsRef.current
    return () => {
      timeoutIds.forEach((timeoutId) => clearTimeout(timeoutId))
      timeoutIds.clear()
    }
  }, [])

  return (
    <ToastContext.Provider value={{ toasts, showToast, removeToast }}>
      {children}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            data-testid="toast-notification"
            className={`pointer-events-auto px-4 py-3 rounded-lg shadow-lg border backdrop-blur-sm max-w-md animate-slide-in ${
              toast.type === 'error'
                ? 'bg-red-900/90 border-red-700 text-red-100'
                : toast.type === 'success'
                  ? 'bg-green-900/90 border-green-700 text-green-100'
                  : toast.type === 'warning'
                    ? 'bg-amber-900/90 border-amber-700 text-amber-100'
                    : 'bg-stone-800/90 border-stone-600 text-stone-100'
            }`}
            role="alert"
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium flex-1">{toast.message}</span>
              {toast.action && (
                <button
                  onClick={() => {
                    toast.action!.onClick()
                    removeToast(toast.id)
                  }}
                  className="text-sm font-bold underline hover:no-underline"
                >
                  {toast.action.label}
                </button>
              )}
              <button
                onClick={() => removeToast(toast.id)}
                className="text-sm opacity-70 hover:opacity-100"
                aria-label="Close notification"
              >
                ✕
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}
