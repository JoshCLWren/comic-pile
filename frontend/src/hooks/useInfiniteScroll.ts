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
  const [sentinelElement, setSentinelElement] = useState<HTMLDivElement | null>(null)
  const sentinelRef = useCallback((el: HTMLDivElement | null) => {
    setSentinelElement(el)
  }, [])

  // Tracks the previous intersection state so a load only fires on a real
  // outside->inside transition. IntersectionObserver enqueues an entry with the
  // element's current state synchronously when `observe()` is called, so without
  // edge-triggering every page load would immediately re-request (and greedily
  // prefetch) the following page on mount and after each successful fetch.
  // Reset when the sentinel element changes so remounts (e.g. plain→virtualized
  // threshold crossing) don't inherit stale intersection state.
  const wasIntersecting = useRef(false)

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
