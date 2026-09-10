import { useCallback, useEffect, useRef } from 'react'
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
 * Owns the in-place Roll-page viewport transitions. Entering the rating view
 * (for example after a fresh roll) anchors the viewport to the start of the
 * rating surface so the reader immediately sees the rolled comic instead of
 * the pre-roll scroll offset; leaving rating mode returns the viewport to the
 * die. The hook owns the "enter rating" side of the transition that the page
 * previously handled only for the "leave rating" direction.
 *
 * The rating view is an in-place state flip on the same route, never a URL the
 * browser can land on, so every false->true transition is a real reader action
 * (a fresh roll, a pending-read hydration, a thread read). Each one anchors.
 * Route-level back/forward and reload restoration stays entirely with the
 * `useScrollRestoration` hook; it restores positions on POP navigations and the
 * hook only reacts to the later in-place transition. Gating the anchor on the
 * last navigation type would be both ineffective (a POP arrival can never
 * activate the rating view itself) and harmful: after a reload or back/forward
 * arrival the stale pre-roll offset would be retained again on the next roll.
 */
export function useRollViewport({ isRatingView }: UseRollViewportParams) {
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
    if (entersRatingView) {
      scrollToRatingStart()
    }
  }, [isRatingView, scrollToDice, scrollToRatingStart])

  return { mainDieRef, ratingViewTopRef, scrollToDice, scrollToRatingStart }
}