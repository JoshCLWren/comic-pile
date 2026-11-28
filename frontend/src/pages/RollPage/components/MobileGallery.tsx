import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'
import type { IssueCard } from '../../../services/issueCardsApi'
import type { RollBootstrapThread } from '../../../types/rollBootstrap'
import { isFunction, isWindowDefined } from '../../../utils/runtimeChecks'
import {
  GALLERY_SWIPE_THRESHOLD,
  carouselOffset,
  carouselTransform,
  galleryCoverWidth,
  wrapCarouselIndex,
} from '../coverBoardLayout'
import { RollCover } from './RollCover'

interface MobileGalleryProps {
  pool: RollBootstrapThread[]
  cardByIssueId: Map<number, IssueCard>
  isRolling: boolean
  winningThreadId: number | null
  /** The real die renderer, owned by the page so it stays a single instance. */
  dieSlot: ReactNode
  onThreadClick: (thread: RollBootstrapThread) => void
}

/**
 * Decorative rotation is skipped for reduced-motion readers; the outcome is not.
 * `matchMedia` is decoded with the runtimeChecks contract helper rather than a
 * bare `typeof` guard: a function at this DOM boundary is the browser's
 * `MediaQueryList` factory, so `.matches` is a boolean preference.
 */
function prefersReducedMotion(): boolean {
  return (
    isWindowDefined() &&
    isFunction(window.matchMedia) &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/**
 * Wraparound comic gallery for phone Roll (issue #5981). Browsing is pure
 * presentation state: swiping or using the arrows only moves the highlighted
 * face. The die above the carousel is the single roll trigger, and the winning
 * face is centered before the existing Rate view opens.
 */
export function MobileGallery({
  pool,
  cardByIssueId,
  isRolling,
  winningThreadId,
  dieSlot,
  onThreadClick,
}: MobileGalleryProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const pointerStart = useRef<number | null>(null)
  const suppressClick = useRef(false)
  const [width, setWidth] = useState(390)
  const [active, setActive] = useState(0)

  useEffect(() => {
    const node = wrapRef.current
    /* v8 ignore start */
    if (node == null) return
    /* v8 ignore stop */
    const measure = () => setWidth(node.clientWidth || 390)
    measure()
    /* v8 ignore next 2 */
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  // Decorative rotation while a roll is in flight. No mutation is issued here;
  // the authoritative winner is supplied by the committed roll response. Reduced
  // motion skips the decorative rotation; the winning face still centers.
  useEffect(() => {
    if (prefersReducedMotion() || !isRolling || pool.length < 2) return
    const interval = window.setInterval(() => {
      setActive((current) => wrapCarouselIndex(current + 1, pool.length))
    }, 110)
    return () => window.clearInterval(interval)
  }, [isRolling, pool.length])

  useEffect(() => {
    if (winningThreadId == null) return
    const winnerIndex = pool.findIndex((thread) => thread.id === winningThreadId)
    if (winnerIndex >= 0) setActive(winnerIndex)
  }, [winningThreadId, pool])

  const move = (delta: number) => {
    if (isRolling || pool.length < 2) return
    setActive((current) => wrapCarouselIndex(current + delta, pool.length))
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    pointerStart.current = event.clientX
  }
  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const start = pointerStart.current
    pointerStart.current = null
    if (start == null) return
    const distance = event.clientX - start
    if (Math.abs(distance) <= GALLERY_SWIPE_THRESHOLD) return
    suppressClick.current = true
    move(distance < 0 ? 1 : -1)
    window.setTimeout(() => {
      suppressClick.current = false
    }, 0)
  }
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    move(event.key === 'ArrowRight' ? 1 : -1)
  }

  const coverWidth = galleryCoverWidth(width)
  // SAFETY: `--gallery-cover-w` is a custom CSS property accepted by the
  // CSSProperties index signature; height is a px string.
  const trackStyle = {
    height: `${Math.ceil(coverWidth * 1.5 + 19)}px`,
    '--gallery-cover-w': `${coverWidth}px`,
  } as CSSProperties

  return (
    <div ref={wrapRef} className="roll-mobile-gallery-wrap" data-testid="roll-mobile-gallery">
      {dieSlot}
      <div
        className="roll-gallery"
        tabIndex={0}
        role="group"
        aria-label="Comic gallery, use arrow keys to browse"
        onKeyDown={handleKeyDown}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerCancel={() => {
          pointerStart.current = null
        }}
      >
        <div className="roll-gallery-track" style={trackStyle}>
          {pool.map((thread, index) => {
            const offset = carouselOffset(index, active, pool.length)
            // SAFETY: transform/opacity/visibility/zIndex are standard
            // CSSProperties members built from the computed carousel offset.
            const style = {
              transform: carouselTransform(offset, coverWidth),
              opacity: Math.abs(offset) > 1 ? 0 : offset === 0 ? 1 : 0.55,
              visibility: Math.abs(offset) > 1 ? 'hidden' : 'visible',
              zIndex: offset === 0 ? 2 : 1,
            } as CSSProperties
            return (
              <RollCover
                key={thread.id}
                thread={thread}
                face={index + 1}
                card={thread.issue_id != null ? cardByIssueId.get(thread.issue_id) ?? null : null}
                winner={winningThreadId != null && thread.id === winningThreadId}
                center={offset === 0}
                far={Math.abs(offset) > 1}
                style={style}
                className="roll-gallery-cover"
                onOpen={() => {
                  if (suppressClick.current || isRolling) return
                  if (index !== active) {
                    setActive(index)
                    return
                  }
                  onThreadClick(thread)
                }}
              />
            )
          })}
        </div>
      </div>
      <div className="roll-gallery-nav">
        <button
          type="button"
          className="roll-gallery-arrow"
          aria-label="Previous comic"
          onClick={() => move(-1)}
          disabled={pool.length < 2}
        >
          ‹
        </button>
        <span className="roll-gallery-count" aria-live="polite">
          {active + 1} / {pool.length}
        </span>
        <button
          type="button"
          className="roll-gallery-arrow"
          aria-label="Next comic"
          onClick={() => move(1)}
          disabled={pool.length < 2}
        >
          ›
        </button>
      </div>
      <p className="roll-gallery-caption">
        {isRolling ? 'Gallery rotating…' : 'Swipe to browse · Tap cover for actions'}
      </p>
    </div>
  )
}
