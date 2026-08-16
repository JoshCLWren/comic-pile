import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'

class MockIntersectionObserver {
  static instances: MockIntersectionObserver[] = []
  callback: IntersectionObserverCallback
  root: Element | Document | null = null
  rootMargin = ''
  thresholds: readonly number[] = []

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

function ScrollSentinel({
  onLoadMore,
  hasMore,
  isLoading,
}: {
  onLoadMore: () => void
  hasMore: boolean
  isLoading: boolean
}) {
  const { sentinelRef } = useInfiniteScroll({ onLoadMore, hasMore, isLoading })
  return <div ref={sentinelRef} data-testid="sentinel" />
}

const intersectingEntry = (isIntersecting: boolean) => ({
  isIntersecting,
} as IntersectionObserverEntry)

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
    render(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />)
    await flushObserver()

    const observer = getObserver()
    act(() => observer.callback([intersectingEntry(true)], observer as unknown as IntersectionObserver))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('does not re-fire when the sentinel stays intersecting without leaving', async () => {
    const onLoadMore = vi.fn()
    render(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />)
    await flushObserver()

    const observer = getObserver()
    act(() => observer.callback([intersectingEntry(true)], observer as unknown as IntersectionObserver))
    act(() => observer.callback([intersectingEntry(true)], observer as unknown as IntersectionObserver))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('fires again only after the sentinel leaves and re-enters the viewport', async () => {
    const onLoadMore = vi.fn()
    render(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />)
    await flushObserver()

    const observer = getObserver()
    act(() => observer.callback([intersectingEntry(true)], observer as unknown as IntersectionObserver))
    act(() => observer.callback([intersectingEntry(false)], observer as unknown as IntersectionObserver))
    act(() => observer.callback([intersectingEntry(true)], observer as unknown as IntersectionObserver))

    expect(onLoadMore).toHaveBeenCalledTimes(2)
  })

  it('does not re-fire after the observer is recreated by a dependency change', async () => {
    const onLoadMore = vi.fn()
    const { rerender } = render(
      <ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />,
    )
    await flushObserver()

    const first = getObserver()
    act(() => first.callback([intersectingEntry(true)], first as unknown as IntersectionObserver))
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    rerender(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={true} />)
    rerender(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />)
    await flushObserver()

    const second = getObserver()
    act(() => second.callback([intersectingEntry(true)], second as unknown as IntersectionObserver))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })
})
