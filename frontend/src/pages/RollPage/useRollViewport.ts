import { useCallback, useEffect, useRef } from 'react'
import { requestSemanticScroll } from '../../scroll/scrollCoordinator'
import { isFunction } from '../../utils/runtimeChecks'

/**
 * Resolve the scroll behavior for Roll-page viewport transitions. Smooth
 * scrolling is the playful default while the reader has not asked to reduce
 * motion; `prefers-reduced-motion` falls back to an instant anchor so the
 * transition still lands on the target without the animation.
 */
function scrollBehavior(): 'auto' | 'smooth' {
  return typeof window !== 'undefined'
    && isFunction(window.matchMedia)
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? 'auto'
    : 'smooth'
}

interface UseRollViewportParams {
  isRatingView: boolean
}

/**
 * Explicit semantic scrolling for the Roll dice/rating transition (#2582).
 *
 * This is the narrow feature-scroll exception to route scroll ownership: the
 * scroll only fires for an intentional in-page product transition and is
 * routed through `requestSemanticScroll` so it can never race an actively
 * settling route restore — a deferred transition applies once the restore
 * ends instead of fighting it.
 */
export function useRollViewport({ isRatingView }: UseRollViewportParams) {
  const mainDieRef = useRef<HTMLDivElement>(null)
  const ratingViewTopRef = useRef<HTMLDivElement>(null)
  const prevIsRatingViewRef = useRef(isRatingView)

  const scrollToDice = useCallback(() => {
    requestSemanticScroll(() => {
      mainDieRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
    })
  }, [])

  const scrollToRatingStart = useCallback((behavior: 'auto' | 'smooth' = scrollBehavior()) => {
    requestSemanticScroll(() => {
      ratingViewTopRef.current?.scrollIntoView({ behavior, block: 'start' })
    })
  }, [])

  useEffect(() => {
    const wasRatingView = prevIsRatingViewRef.current
    const entersRatingView = isRatingView && !wasRatingView
    prevIsRatingViewRef.current = isRatingView

    if (wasRatingView && !isRatingView) {
      scrollToDice()
      return
    }
    if (entersRatingView) {
      scrollToRatingStart()
    }
  }, [isRatingView, scrollToDice, scrollToRatingStart])

  return { mainDieRef, ratingViewTopRef, scrollToDice, scrollToRatingStart }
}