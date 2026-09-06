import { useCallback, useEffect, useRef } from 'react'

/**
 * Resolve the scroll behavior for Roll-page viewport transitions. Smooth
 * scrolling is the playful default while the reader has not asked to reduce
 * motion; `prefers-reduced-motion` falls back to an instant anchor so the
 * transition still lands on the target without the animation.
 */
function scrollBehavior(): 'auto' | 'smooth' {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? 'auto'
    : 'smooth'
}

interface UseRollViewportParams {
  isRatingView: boolean
  navType: 'POP' | 'PUSH' | 'REPLACE'
}

/**
 * Owns the in-place Roll-page viewport transitions. Entering the rating view
 * (for example after a fresh roll) anchors the viewport to the start of the
 * rating surface so the reader immediately sees the rolled comic instead of
 * the pre-roll scroll offset; leaving rating mode returns the viewport to the
 * die. The hook owns the "enter rating" side of the transition that the page
 * previously handled only for the "leave rating" direction.
 *
 * Back/forward and reload restoration stays with the route-level
 * `useScrollRestoration` hook, so POP navigations never re-anchor here:
 * position restoration on those navigations remains untouched.
 */
export function useRollViewport({ isRatingView, navType }: UseRollViewportParams) {
  const mainDieRef = useRef<HTMLDivElement>(null)
  const ratingViewTopRef = useRef<HTMLDivElement>(null)
  const prevIsRatingViewRef = useRef(isRatingView)

  const scrollToDice = useCallback(() => {
    mainDieRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
  }, [])

  const scrollToRatingStart = useCallback(() => {
    ratingViewTopRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
  }, [])

  useEffect(() => {
    const wasRatingView = prevIsRatingViewRef.current
    const entersRatingView = isRatingView && !wasRatingView
    prevIsRatingViewRef.current = isRatingView

    if (wasRatingView && !isRatingView) {
      scrollToDice()
      return
    }
    if (entersRatingView && navType !== 'POP') {
      scrollToRatingStart()
    }
  }, [isRatingView, navType, scrollToDice, scrollToRatingStart])

  return { mainDieRef, ratingViewTopRef, scrollToDice, scrollToRatingStart }
}