import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'

class MockIntersectionObserver {
  static instances: MockIntersectionObserver[] = []
  callback: IntersectionObserverCallback

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    MockIntersectionObserver.instances.push(this)
  }

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

const intersectingEntry = (isIntersecting: boolean) =>
  ({ isIntersecting } as unknown as IntersectionObserverEntry)

function getObserver(): MockIntersectionObserver {
  const observer = MockIntersectionObserver.instances.at(-1)
  if (!observer) throw new Error('IntersectionObserver was not constructed')
  return observer
}

async function flushObserver(): Promise<void> {
  await waitFor(() => {
    expect(MockIntersectionObserver.instances.length).toBeGreaterThan(0)
  })
}

describe('useInfiniteScroll edge-triggering', () => {
  let originalObserver: unknown

  beforeEach(() => {
    MockIntersectionObserver.instances = []
    originalObserver = globalThis.IntersectionObserver
    Object.defineProperty(globalThis, 'IntersectionObserver', {
      configurable: true,
      writable: true,
      value: MockIntersectionObserver,
    })
  })

  afterEach(() => {
    Object.defineProperty(globalThis, 'IntersectionObserver', {
      configurable: true,
      writable: true,
      value: originalObserver,
    })
  })

  it('fires onLoadMore once on the initial intersecting observe', async () => {
    const onLoadMore = vi.fn()
    renderHook(() => useInfiniteScroll({ onLoadMore, hasMore: true, isLoading: false }))
    await flushObserver()

    const observer = getObserver()
    act(() => observer.callback([intersectingEntry(true)], observer))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('does not re-fire when the sentinel stays intersecting without leaving', async () => {
    const onLoadMore = vi.fn()
    renderHook(() => useInfiniteScroll({ onLoadMore, hasMore: true, isLoading: false }))
    await flushObserver()

    const observer = getObserver()
    act(() => observer.callback([intersectingEntry(true)], observer))
    act(() => observer.callback([intersectingEntry(true)], observer))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('fires again only after the sentinel leaves and re-enters the viewport', async () => {
    const onLoadMore = vi.fn()
    renderHook(() => useInfiniteScroll({ onLoadMore, hasMore: true, isLoading: false }))
    await flushObserver()

    const observer = getObserver()
    act(() => observer.callback([intersectingEntry(true)], observer))
    act(() => observer.callback([intersectingEntry(false)], observer))
    act(() => observer.callback([intersectingEntry(true)], observer))

    expect(onLoadMore).toHaveBeenCalledTimes(2)
  })

  it('does not re-fire after the observer is recreated by a dependency change', async () => {
    const onLoadMore = vi.fn()
    const { rerender } = renderHook(
      ({ isLoading }: { isLoading: boolean }) =>
        useInfiniteScroll({ onLoadMore, hasMore: true, isLoading }),
      { initialProps: { isLoading: false } },
    )
    await flushObserver()

    const first = getObserver()
    act(() => first.callback([intersectingEntry(true)], first))
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    // Simulate a page load completing: isLoading flips true then false,
    // which recreates the observer (the situation that caused duplicate prefetch).
    rerender({ isLoading: true })
    rerender({ isLoading: false })
    await flushObserver()

    const second = getObserver()
    act(() => second.callback([intersectingEntry(true)], second))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })
})
