import '@testing-library/jest-dom'
import { vi } from 'vitest'
import { createElement, type ReactElement, type ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '../query/queryClient'

// Tests run against the same process-wide `queryClient` singleton the app uses
// (see App.tsx) so cache writes (`setQueryData`/`invalidateQueries`, e.g. roll
// bootstrap reconciliation) reach the cache the rendered component reads. Retries
// are disabled for deterministic, fast failure paths, and the cache is cleared
// per render so tests stay isolated; any test-supplied wrapper is composed inside.
queryClient.setDefaultOptions({
  queries: { retry: false },
  mutations: { retry: false },
})

vi.mock('@testing-library/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@testing-library/react')>()
  const makeWrapper = (innerWrapper?: (props: { children: ReactNode }) => ReactElement) => {
    queryClient.clear()
    return ({ children }: { children: ReactNode }) =>
      createElement(
        QueryClientProvider,
        { client: queryClient },
        innerWrapper ? createElement(innerWrapper, null, children) : children,
      )
  }

  return {
    ...actual,
    render: (
      ui: Parameters<typeof actual.render>[0],
      options?: Record<string, unknown>,
    ) => {
      const wrapper = options?.wrapper as
        | ((props: { children: ReactNode }) => ReactElement)
        | undefined
      return actual.render(ui, { ...options, wrapper: makeWrapper(wrapper) })
    },
    renderHook: (
      callback: Parameters<typeof actual.renderHook>[0],
      options?: Record<string, unknown>,
    ) => {
      const wrapper = options?.wrapper as
        | ((props: { children: ReactNode }) => ReactElement)
        | undefined
      return actual.renderHook(callback, { ...options, wrapper: makeWrapper(wrapper) })
    },
  }
})

// Ensure globals exist before user-event and other libraries access them
if (typeof global.window === 'undefined') {
  ;(global as any).window = {}
}
if (typeof global.document === 'undefined') {
  ;(global as any).document = {
    addEventListener: () => {},
    removeEventListener: () => {},
    // Minimal DOM methods used by tests
    createElement: () => ({
      setAttribute: () => {},
      appendChild: () => {},
      removeChild: () => {},
      // Add any other attributes as needed
    }),
    getElementsByTagName: () => [],
    getElementById: () => undefined,
    querySelector: () => undefined,
    querySelectorAll: () => [],
  }
}

// Provide a minimal localStorage implementation if missing
if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
  ;(window as any).localStorage = {
    clear: vi.fn(),
    getItem: vi.fn(),
    setItem: vi.fn(),
  }
}

// Make window.scrollTo a no-op in environments where it throws
if (typeof window !== 'undefined') {
  window.scrollTo = (() => undefined) as unknown as typeof window.scrollTo
}

// Handle IntersectionObserver fallback if needed
if (typeof IntersectionObserver === 'undefined' || typeof globalThis.IntersectionObserver === 'undefined') {
  class MockIntersectionObserver {
    static instances: MockIntersectionObserver[] = []
    readonly callback: IntersectionObserverCallback
    readonly root: Element | Document | null = null
    readonly rootMargin = ''
    readonly thresholds: readonly number[] = []
    private readonly targets = new Set<Element>()

    constructor(callback: IntersectionObserverCallback) {
      this.callback = callback
      MockIntersectionObserver.instances.push(this)
    }

    observe(target: Element): void {
      this.targets.add(target)
    }

    unobserve(target: Element): void {
      this.targets.delete(target)
    }

    disconnect(): void {
      this.targets.clear()
    }

    takeRecords(): IntersectionObserverEntry[] {
      return []
    }
  }
  Object.defineProperty(globalThis, 'IntersectionObserver', {
    configurable: true,
    writable: true,
    value: MockIntersectionObserver,
  })
}

if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = vi.fn()
}

// jsdom's window.scrollTo throws "Not implemented"; replace it with a no-op so
// scroll-restoration logic can run without noisy console errors.
window.scrollTo = (() => undefined) as unknown as typeof window.scrollTo

if (typeof globalThis.IntersectionObserver === 'undefined') {
  class MockIntersectionObserver {
    static instances: MockIntersectionObserver[] = []
    readonly callback: IntersectionObserverCallback
    readonly root: Element | Document | null = null
    readonly rootMargin = ''
    readonly thresholds: readonly number[] = []
    private readonly targets = new Set<Element>()

    constructor(callback: IntersectionObserverCallback) {
      this.callback = callback
      MockIntersectionObserver.instances.push(this)
    }

    observe(target: Element): void {
      this.targets.add(target)
    }

    unobserve(target: Element): void {
      this.targets.delete(target)
    }

    disconnect(): void {
      this.targets.clear()
    }

    takeRecords(): IntersectionObserverEntry[] {
      return []
    }
  }
  Object.defineProperty(globalThis, 'IntersectionObserver', {
    configurable: true,
    writable: true,
    value: MockIntersectionObserver,
  })
}