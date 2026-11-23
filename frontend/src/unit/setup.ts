import '@testing-library/jest-dom'
import { beforeEach, vi } from 'vitest'
import { queryClient } from '../query/queryClient'
import { resetQueryRetryBudget } from '../query/outageRetryBudget'
import { isFunction } from '../utils/runtimeChecks'

// Tests run against the same process-wide `queryClient` singleton the app uses
// (see App.tsx) so cache writes (`setQueryData`/`invalidateQueries`, e.g. roll
// bootstrap reconciliation) reach the cache the rendered component reads. Retries
// are disabled for deterministic, fast failure paths, and the cache is cleared
// once per test so tests stay isolated while multiple renders within a test can
// share the cache coherently; any test-supplied wrapper is composed inside.
// Preserve the app's other query defaults (notably `staleTime`) so assertions that
// depend on them continue to hold. The app's real retry policy is asserted against
// the exported `queryRetryPolicy` in queryClient.test.ts because test setup
// intentionally overrides the singleton's `retry` default to `false`.
const defaultOptions = queryClient.getDefaultOptions()
queryClient.setDefaultOptions({
  queries: { ...(defaultOptions.queries ?? {}), retry: false },
  mutations: { ...(defaultOptions.mutations ?? {}), retry: false },
})

beforeEach(() => {
  queryClient.clear()
  // The outage retry budget is module-level state; reset it so one test's
  // recognized outage or auth-degraded window cannot leak into the next.
  resetQueryRetryBudget()
})

// Ensure globals exist before user-event and other libraries access them
if (typeof global.window === 'undefined') {
  // SAFETY: test setup runs in Node; we assign a minimal window for jsdom compatibility
  (global as { window?: unknown }).window = {}
}
if (typeof global.document === 'undefined') {
  // SAFETY: test setup runs in Node; we assign a minimal document for jsdom compatibility
  (global as { document?: unknown }).document = {
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
  // SAFETY: test setup runs in Node; it installs the minimal localStorage user-event needs
  (window as { localStorage?: unknown }).localStorage = {
    clear: vi.fn(),
    getItem: vi.fn(),
    setItem: vi.fn(),
  }
}

// Make window.scrollTo a no-op in environments where it throws
if (typeof window !== 'undefined') {
  // SAFETY: jsdom throws on scrollTo, so the test replaces it with a no-op
  window.scrollTo = (() => undefined) as typeof window.scrollTo
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
