import type { ReactNode } from 'react'
import { vi, type Mock } from 'vitest'
import { ToastContext, type ToastContextType } from '../contexts/ToastContext'

/**
 * Recording {@link ToastContextType} for tests.
 *
 * `showToast` and `removeToast` are spies so tests can assert on real toast
 * requests, while `toasts` stays empty because no toast markup is rendered.
 */
export type ToastSpy = ToastContextType & {
  showToast: Mock
  removeToast: Mock
}

/**
 * Build a toast context double that records calls instead of showing toasts.
 *
 * @returns A {@link ToastContextType} whose mutators are spies.
 */
export function createToastSpy(): ToastSpy {
  return {
    toasts: [],
    showToast: vi.fn(() => 'toast-id'),
    removeToast: vi.fn(),
  }
}

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
