import { vi, type Mock } from 'vitest'
import type { ToastContextType } from '../contexts/ToastContext'

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
