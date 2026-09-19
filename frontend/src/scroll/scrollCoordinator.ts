/**
 * Single-owner scroll coordination for ComicPile (issue #2582).
 *
 * Ownership contract:
 * - Route/resume restoration is owned exclusively by the route restoration
 *   layer (`useScrollRestoration`). This module is the only production code
 *   allowed to call `window.scrollTo` for restoring a prior route position;
 *   see `restoreRouteScrollPosition`.
 * - Feature surfaces may perform explicit semantic scrolling only for an
 *   intentional in-page product transition (Roll dice/rating moves, glossary
 *   anchors, Roll-pool return-to-top). Those paths must go through
 *   `requestSemanticScroll` / `scrollToTopSemantic` so they can never race an
 *   actively settling route restore.
 * - Virtualizers own measurement/rendering, not navigation. Queue
 *   virtualization must never call the helpers in this module to reposition
 *   the window; its drag edge auto-scroll is an explicit user-gesture scroll
 *   through the virtualizer, not a restore.
 * - ResumeRecovery owns data/auth recovery, not viewport position. It refreshes
 *   queries through scoped `cacheEffects` helpers and never touches the
 *   viewport.
 *
 * Correctness never depends on a guessed delay: restoration settles against an
 * explicit layout-readiness contract (`waitForLayoutSettled`), not a fixed
 * timeout.
 */

type SemanticScrollAction = () => void

let activeRestores = 0
const pendingSemantic: SemanticScrollAction[] = []

/** Stable document height probe used by the settling contract. */
function readDocumentHeight(): number {
  if (typeof document === 'undefined') {
    return 0
  }
  return document.documentElement?.scrollHeight ?? document.body?.scrollHeight ?? 0
}

/**
 * Whether a route/resume restore is actively settling. Feature semantic
 * scrolling must defer while this is true.
 */
export function isRouteRestoreSettling(): boolean {
  return activeRestores > 0
}

/**
 * Mark the start of a route/resume restoration window. Returns an `end`
 * callback that must run when the restore settles or is cancelled. Calls nest
 * (navigation restore overlapping a resume restore); deferred semantic scrolls
 * flush in order when the outermost restore ends.
 */
export function beginRouteRestore(): () => void {
  activeRestores += 1
  let ended = false
  return () => {
    if (ended) {
      return
    }
    ended = true
    activeRestores = Math.max(0, activeRestores - 1)
    if (activeRestores === 0) {
      const queued = pendingSemantic.splice(0, pendingSemantic.length)
      for (const action of queued) {
        action()
      }
    }
  }
}

/**
 * The sole route/resume restoration viewport write. Every other production
 * path that needs the window at a restored offset must flow through here so a
 * second navigation-scroll owner cannot be introduced unnoticed (guarded by
 * `scrollOwnership.test.ts`).
 */
export function restoreRouteScrollPosition(y: number): void {
  if (typeof window === 'undefined') {
    return
  }
  window.scrollTo(0, y)
}

/**
 * Request an explicit feature semantic scroll (for example a Roll
 * dice/rating transition or a glossary anchor). Runs immediately when no
 * route restore is settling; otherwise queues until the outermost restore
 * ends so the two can never race.
 */
export function requestSemanticScroll(action: SemanticScrollAction): void {
  if (isRouteRestoreSettling()) {
    pendingSemantic.push(action)
    return
  }
  action()
}

/**
 * Explicit semantic scroll to the top of the window (for example returning
 * from the Roll rating view to the dice pool). Gated exactly like
 * `requestSemanticScroll`: deferred while a route restore is settling.
 */
export function scrollToTopSemantic(): void {
  requestSemanticScroll(() => {
    if (typeof window === 'undefined') {
      return
    }
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  })
}

const SETTLE_STABLE_FRAMES = 3
const SETTLE_MAX_FRAMES = 60

export interface LayoutSettleOptions {
  /** Height probe; defaults to the document scroll height. */
  readHeight?: () => number
  /** Consecutive stable frames that declare the layout settled. */
  stableFrames?: number
  /** Hard frame bound so a continuously shifting page still resolves. */
  maxFrames?: number
  /** Cancellation predicate checked before every frame. */
  isCancelled?: () => boolean
  /**
   * Called after each settled frame with the current target. Return true when
   * the position still needs re-applying (for example deferred content
   * unclamped a clamped restore). Never called after cancellation or after
   * the caller reports user-driven movement.
   */
  needsReapply?: () => boolean
  /** Re-applies the target position when `needsReapply` reports true. */
  reapply?: () => void
}

/**
 * Resolve when layout stops shifting: the height probe must read unchanged
 * for `stableFrames` consecutive animation frames, bounded by `maxFrames`.
 * Uses only animation-frame readiness — never a fixed timeout — so deferred
 * renders re-arm the settle window instead of racing a guessed delay.
 */
export function waitForLayoutSettled(options: LayoutSettleOptions = {}): Promise<void> {
  const {
    readHeight = readDocumentHeight,
    stableFrames = SETTLE_STABLE_FRAMES,
    maxFrames = SETTLE_MAX_FRAMES,
    isCancelled = () => false,
    needsReapply,
    reapply,
  } = options
  return new Promise((resolve) => {
    if (typeof window === 'undefined' || !('requestAnimationFrame' in window)) {
      resolve()
      return
    }
    let lastHeight = readHeight()
    let stable = 0
    let frames = 0
    const step = () => {
      if (isCancelled()) {
        resolve()
        return
      }
      frames += 1
      const height = readHeight()
      if (height === lastHeight) {
        stable += 1
      } else {
        stable = 0
        lastHeight = height
      }
      if (needsReapply?.() === true) {
        reapply?.()
      }
      if (stable >= stableFrames || frames >= maxFrames) {
        resolve()
        return
      }
      window.requestAnimationFrame(step)
    }
    window.requestAnimationFrame(step)
  })
}
