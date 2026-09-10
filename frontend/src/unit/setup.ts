import '@testing-library/jest-dom'
import { beforeEach, vi } from 'vitest'
import { createElement, type ReactElement, type ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '../query/queryClient'
import { isFunction } from '../utils/runtimeChecks'
import * as testingLibrary from '@testing-library/react'

const defaultOptions = queryClient.getDefaultOptions()
queryClient.setDefaultOptions({
  queries: { ...(defaultOptions.queries ?? {}), retry: false },
  mutations: { ...(defaultOptions.mutations ?? {}), retry: false },
})

beforeEach(() => {
  queryClient.clear()
})

const makeWrapper = (innerWrapper?: (props: { children: ReactNode }) => ReactElement) => {
  return ({ children }: { children: ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: queryClient },
      innerWrapper ? createElement(innerWrapper, null, children) : children,
    )
}

const wrappedRender = (
  ui: Parameters<typeof testingLibrary.render>[0],
  options?: Record<string, unknown>,
) => {
  const wrapper = options?.wrapper as
    | ((props: { children: ReactNode }) => ReactElement)
    | undefined
  return testingLibrary.render(ui, { ...options, wrapper: makeWrapper(wrapper) })
}

const wrappedRenderHook = (
  callback: Parameters<typeof testingLibrary.renderHook>[0],
  options?: Record<string, unknown>,
) => {
  const wrapper = options?.wrapper as
    | ((props: { children: ReactNode }) => ReactElement)
    | undefined
  return testingLibrary.renderHook(callback, { ...options, wrapper: makeWrapper(wrapper) })
}

Object.defineProperty(testingLibrary, 'render', { value: wrappedRender, writable: true })
Object.defineProperty(testingLibrary, 'renderHook', { value: wrappedRenderHook, writable: true })

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

if (!isFunction(Element.prototype.scrollIntoView)) {
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