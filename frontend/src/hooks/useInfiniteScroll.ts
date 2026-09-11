import { useCallback, useEffect, useRef, useState } from 'react'

interface UseInfiniteScrollOptions {
  onLoadMore: () => void
  hasMore: boolean
  isLoading: boolean
  threshold?: number
  rootRef?: React.RefObject<Element | null>
}

export function useInfiniteScroll({
  onLoadMore,
  hasMore,
  isLoading,
  threshold = 200,
  rootRef,
}: UseInfiniteScrollOptions) {
  // Tracks the previous intersection state so a load only fires on a real
  // outside->inside transition. IntersectionObserver enqueues an entry with the
  // element's current state synchronously when `observe()` is called, so without
  // edge-triggering every page load would immediately re-request (and greedily
  // prefetch) the following page on mount and after each successful fetch.
  const wasIntersecting = useRef(false)

  // The sentinel is tracked as state through a callback ref so the observer
  // effect is keyed to the actual element and re-arms whenever the DOM node is
  // swapped. A remount - e.g. the plain -> virtualized switch when the queue
  // crosses VIRTUALIZATION_THRESHOLD - attaches a brand-new sentinel. Reset the
  // previous intersection edge there so the fresh observer can fire loadMore on
  // its first intersecting report instead of treating the new sentinel as
  // already-intersecting; without the reset the scroll silently stalls after
  // the threshold crossing and the user must scroll away and back to resume.
  const [sentinelElement, setSentinelElement] = useState<HTMLDivElement | null>(null)
  const sentinelRef = useCallback((el: HTMLDivElement | null) => {
    wasIntersecting.current = false
    setSentinelElement(el)
  }, [])

  const handleIntersect = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const [entry] = entries
      const isIntersecting = !!entry?.isIntersecting
      if (isIntersecting && !wasIntersecting.current && hasMore && !isLoading) {
        onLoadMore()
      }
      wasIntersecting.current = isIntersecting
    },
    [hasMore, isLoading, onLoadMore],
  )

  useEffect(() => {
    const sentinel = sentinelElement
    if (!sentinel) return

    const observer = new IntersectionObserver(handleIntersect, {
      root: rootRef ? rootRef.current : null,
      rootMargin: `${threshold}px`,
    })

    observer.observe(sentinel)

    return () => {
      observer.disconnect()
    }
  }, [handleIntersect, threshold, rootRef, sentinelElement])

  return { sentinelRef }
}
