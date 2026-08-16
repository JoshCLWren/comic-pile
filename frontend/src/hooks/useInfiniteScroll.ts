import { useCallback, useEffect, useRef } from 'react'

interface UseInfiniteScrollOptions {
  onLoadMore: () => void
  hasMore: boolean
  isLoading: boolean
  threshold?: number
}

export function useInfiniteScroll({
  onLoadMore,
  hasMore,
  isLoading,
  threshold = 200,
}: UseInfiniteScrollOptions) {
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  // Tracks the previous intersection state so a load only fires on a real
  // outside->inside transition. IntersectionObserver enqueues an entry with the
  // element's current state synchronously when `observe()` is called, so without
  // edge-triggering every page load would immediately re-request (and greedily
  // prefetch) the following page on mount and after each successful fetch.
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
    const sentinel = sentinelRef.current
    if (!sentinel) return

    const observer = new IntersectionObserver(handleIntersect, {
      rootMargin: `${threshold}px`,
    })

    observer.observe(sentinel)

    return () => {
      observer.disconnect()
    }
  }, [handleIntersect, threshold])

  return { sentinelRef }
}
