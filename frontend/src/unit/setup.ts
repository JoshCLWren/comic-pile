import '@testing-library/jest-dom'
import { vi } from 'vitest'

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
    clear: jest.fn(),
    getItem: jest.fn(),
    setItem: jest.fn(),
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