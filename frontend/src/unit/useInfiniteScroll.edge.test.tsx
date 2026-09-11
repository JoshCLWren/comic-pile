import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'
import { cast } from '../utils/cast'

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

function RemountingSentinel({
  onLoadMore,
  hasMore,
  isLoading,
  virtualized,
}: {
  onLoadMore: () => void
  hasMore: boolean
  isLoading: boolean
  virtualized: boolean
}) {
  const { sentinelRef } = useInfiniteScroll({ onLoadMore, hasMore, isLoading })
  if (virtualized) {
    return (
      <section>
        <div ref={sentinelRef} data-testid="virtualized-sentinel" />
      </section>
    )
  }
  return <div ref={sentinelRef} data-testid="sentinel" />
}
const intersectingEntry = (isIntersecting: boolean) =>
  cast<IntersectionObserverEntry>({ isIntersecting })

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
act(() => observer.callback([intersectingEntry(true)], cast<IntersectionObserver>(observer)))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('does not re-fire when the sentinel stays intersecting without leaving', async () => {
    const onLoadMore = vi.fn()
    render(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />)
    await flushObserver()

    const observer = getObserver()
act(() => observer.callback([intersectingEntry(true)], cast<IntersectionObserver>(observer)))
    act(() => observer.callback([intersectingEntry(true)], cast<IntersectionObserver>(observer)))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('fires again only after the sentinel leaves and re-enters the viewport', async () => {
    const onLoadMore = vi.fn()
    render(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />)
    await flushObserver()

    const observer = getObserver()
act(() => observer.callback([intersectingEntry(true)], cast<IntersectionObserver>(observer)))
    act(() => observer.callback([intersectingEntry(false)], cast<IntersectionObserver>(observer)))
    act(() => observer.callback([intersectingEntry(true)], cast<IntersectionObserver>(observer)))

    expect(onLoadMore).toHaveBeenCalledTimes(2)
  })

  it('does not re-fire after the observer is recreated by a dependency change', async () => {
    const onLoadMore = vi.fn()
    const { rerender } = render(
      <ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />,
    )
    await flushObserver()

    const first = getObserver()
act(() => first.callback([intersectingEntry(true)], cast<IntersectionObserver>(first)))
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    rerender(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={true} />)
    rerender(<ScrollSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} />)
    await flushObserver()

    const second = getObserver()
act(() => second.callback([intersectingEntry(true)], cast<IntersectionObserver>(second)))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('re-fires loadMore after the sentinel remounts into a new DOM node (plain→virtualized threshold crossing)', async () => {
    const onLoadMore = vi.fn()
    const { rerender } = render(
      <RemountingSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} virtualized={false} />,
    )
    await flushObserver()

    // Sentinel is intersecting in the plain list, so loadMore fires once and the
    // previous-intersection edge is now primed true.
    const first = getObserver()
    act(() => first.callback([intersectingEntry(true)], cast<IntersectionObserver>(first)))
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    // The queue crosses VIRTUALIZATION_THRESHOLD: QueueList swaps from the plain
    // list to VirtualizedThreadList. The hook stays mounted but React attaches a
    // brand-new sentinel DOM node, tearing down the old observer.
    rerender(
      <RemountingSentinel onLoadMore={onLoadMore} hasMore={true} isLoading={false} virtualized={true} />,
    )
    await flushObserver()

    const remounted = getObserver()
    expect(remounted).not.toBe(first)

    // The remounted sentinel is in the viewport. Without resetting the previous
    // intersection edge this entry would be swallowed and infinite scroll would
    // stall until the user scrolled away and back.
    act(() => remounted.callback([intersectingEntry(true)], cast<IntersectionObserver>(remounted)))

    expect(onLoadMore).toHaveBeenCalledTimes(2)
  })
})
