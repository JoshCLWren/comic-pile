import '@testing-library/jest-dom'

class NoopIntersectionObserver {
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
