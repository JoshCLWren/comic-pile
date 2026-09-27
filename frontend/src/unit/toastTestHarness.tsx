import type { ReactNode } from 'react'
import { ToastContext, type ToastContextType } from '../contexts/ToastContext'

/**
 * Inject a toast context through the real React context.
 *
 * Components and hooks under test read the same `ToastContext` the app
 * provides, so no module replacement is needed.
 *
 * @param props.value - Toast context handed to the tree.
 * @param props.children - Tree to render.
 * @returns A provider element carrying the supplied context value.
 */
export function ToastContextSpy({
  value,
  children,
}: {
  value: ToastContextType
  children: ReactNode
}) {
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>
}
