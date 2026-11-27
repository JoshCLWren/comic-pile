import { useEffect, useRef } from 'react'
import ImageWithLoading from '../../../components/ImageWithLoading'

export interface CoverFlightState {
  /** Exact ComicVine CDN URL from the card projection; never proxied. */
  url: string
  /** Rectangle of the actual small cover that produced this flight. */
  rect: { left: number; top: number; width: number; height: number }
}

interface CoverFlightProps {
  flight: CoverFlightState
  onDone: () => void
}

/**
 * Expands the winning cover's artwork from its real rectangle into the Rate
 * workspace (issue #5981). The flight is decorative only: it never decides the
 * winning issue and never delays the committed roll. A resize, navigation or
 * unmount terminates it immediately so no stale overlay can trap the reader.
 */
export function CoverFlight({ flight, onDone }: CoverFlightProps) {
  const flightRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = flightRef.current
    if (node == null) {
      onDone()
      return
    }
    if (typeof node.animate !== 'function') {
      onDone()
      return
    }

    const target = node.parentElement?.getBoundingClientRect()
    if (target == null || target.width === 0) {
      onDone()
      return
    }

    const animation = node.animate(
      [
        {
          left: `${flight.rect.left}px`,
          top: `${flight.rect.top}px`,
          width: `${flight.rect.width}px`,
          height: `${flight.rect.height}px`,
          borderRadius: '5px',
          opacity: 1,
        },
        {
          left: `${target.left}px`,
          top: `${target.top}px`,
          width: `${target.width}px`,
          height: `${target.height}px`,
          borderRadius: '0px',
          opacity: 0.25,
        },
      ],
      { duration: 500, easing: 'cubic-bezier(.2,.75,.2,1)', fill: 'forwards' },
    )

    let finished = false
    const finish = () => {
      if (finished) return
      finished = true
      onDone()
    }
    void animation.finished.then(finish, finish)
    window.addEventListener('resize', finish)
    return () => {
      window.removeEventListener('resize', finish)
      animation.cancel()
    }
  }, [flight, onDone])

  return (
    <div
      ref={flightRef}
      className="roll-cover-flight"
      data-testid="roll-cover-flight"
      aria-hidden="true"
    >
      <ImageWithLoading src={flight.url} alt="" loading="eager" className="roll-cover-flight-art" />
    </div>
  )
}
