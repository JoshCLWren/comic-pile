import '@testing-library/jest-dom'

class NoopIntersectionObserver {
  root: Element | Document | null = null
  rootMargin = ''
  thresholds: readonly number[] = []

  observe(): void {
    /* no-op */
  }

  unobserve(): void {
    /* no-op */
  }

  disconnect(): void {
    /* no-op */
  }

  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}

globalThis.IntersectionObserver = NoopIntersectionObserver
