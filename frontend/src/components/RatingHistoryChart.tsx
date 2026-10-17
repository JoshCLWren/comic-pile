import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { CreatorIssueRow } from '../services/api-creators'

/**
 * Deterministic trend contract for issue #3090.
 *
 * The rolling average uses a fixed, documented rule rather than a tuned or
 * model-produced direction:
 *
 *   window = min(TREND_MAX_WINDOW, max(TREND_MIN_WINDOW, floor(n * 0.3)))
 *
 * A trend is drawn only once the sample reaches `TREND_MIN_SAMPLE`
 * observations. Below that the sample is labelled as too small instead of being
 * forced into a warming/cooling direction.
 */
const TREND_MAX_WINDOW = 5
const TREND_MIN_WINDOW = 3
const TREND_MIN_SAMPLE = 3
const TREND_WINDOW_RATIO = 0.3

/** Backend rating scale (`app/schemas/rate.py`), used so the axis cannot exaggerate a small spread. */
const RATING_DOMAIN_MIN = 0.5
const RATING_DOMAIN_MAX = 5

/** X-axis spans shorter than this many days get day-level labels instead of month-level ones. */
const DAY_LEVEL_TICK_SPAN_MS = 45 * 24 * 60 * 60 * 1000

/**
 * Grace period before a hovered observation is dismissed, so the pointer can
 * travel from the plotted point onto the tooltip and reach its drill-down link.
 */
const DISMISS_GRACE_MS = 150

const PLOT_MARGIN = { top: 20, right: 20, bottom: 40, left: 48 }
const PLOT_WIDTH = 720
const PLOT_HEIGHT = 240

/** Coordinate width used until the chart measures its own box. */
const DEFAULT_VIEW_WIDTH = PLOT_WIDTH + PLOT_MARGIN.left + PLOT_MARGIN.right

/** Narrowest plot this chart will draw, so dates stay legible on a phone. */
const MIN_PLOT_WIDTH = 240

/** Approximate pixels an x-axis date label needs before another tick would collide. */
const X_TICK_LABEL_BUDGET_PX = 92

interface RatingHistoryChartProps {
  ratedIssues: CreatorIssueRow[]
  /**
   * Headline rated count for the creator. When it exceeds the plotted
   * observations the history is a lower bound, and the chart says so instead of
   * presenting the loaded page as the whole history.
   */
  totalRatings?: number
  className?: string
}

interface RatingDataPoint {
  issueId: number
  rating: number
  timestamp: Date
  threadId: number
  threadTitle: string
  issueNumber: string
}

interface RollingAveragePoint {
  timestamp: Date
  rating: number
  count: number
}

function trendWindowSize(sampleSize: number): number {
  return Math.min(
    TREND_MAX_WINDOW,
    Math.max(TREND_MIN_WINDOW, Math.floor(sampleSize * TREND_WINDOW_RATIO)),
  )
}

/** Half-star ratings keep one decimal; whole ratings do not claim false precision. */
function formatRating(value: number): string {
  return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)
}

function formatCount(value: number, singular: string): string {
  return `${value} ${singular}${value === 1 ? '' : 's'}`
}

export function RatingHistoryChart({ ratedIssues, totalRatings, className = '' }: RatingHistoryChartProps) {
  const [hoveredPoint, setHoveredPoint] = useState<RatingDataPoint | null>(null)
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cancelDismiss = () => {
    if (dismissTimer.current === null) return
    clearTimeout(dismissTimer.current)
    dismissTimer.current = null
  }

  const revealPoint = (point: RatingDataPoint) => {
    cancelDismiss()
    setHoveredPoint(point)
  }

  const dismissSoon = () => {
    cancelDismiss()
    dismissTimer.current = setTimeout(() => {
      dismissTimer.current = null
      setHoveredPoint(null)
    }, DISMISS_GRACE_MS)
  }

  useEffect(() => cancelDismiss, [])

  // Measure the chart box so the SVG coordinate system matches real pixels. A
  // fixed coordinate width would shrink every label below ~12px on a phone;
  // matching the box keeps axis text at its true rendered size at any width.
  const plotBoxRef = useRef<HTMLDivElement | null>(null)
  const [measuredWidth, setMeasuredWidth] = useState<number | null>(null)

  useEffect(() => {
    const node = plotBoxRef.current
    if (node === null || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width ?? 0
      if (width > 0) setMeasuredWidth(width)
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const viewWidth = measuredWidth ?? DEFAULT_VIEW_WIDTH
  const viewPlotWidth = Math.max(
    MIN_PLOT_WIDTH,
    viewWidth - PLOT_MARGIN.left - PLOT_MARGIN.right,
  )

  // Deduplicate edited ratings — the backend already returns the latest
  // effective rating per issue, so the latest timestamp per issue wins again here
  // to keep repeated rows from becoming duplicate observations.
  const ratingData = useMemo(() => {
    const byIssue = new Map<number, RatingDataPoint>()
    ratedIssues.forEach(issue => {
      const rating = issue.effective_rating
      const ratedAt = issue.rating_timestamp
      if (rating == null || ratedAt == null) return
      const point: RatingDataPoint = {
        issueId: issue.issue_id,
        rating,
        timestamp: new Date(ratedAt),
        threadId: issue.thread_id,
        threadTitle: issue.thread_title,
        issueNumber: issue.issue_number,
      }
      const existing = byIssue.get(point.issueId)
      if (!existing || point.timestamp.getTime() > existing.timestamp.getTime()) {
        byIssue.set(point.issueId, point)
      }
    })
    return Array.from(byIssue.values()).sort(
      (a, b) => a.timestamp.getTime() - b.timestamp.getTime(),
    )
  }, [ratedIssues])

  // Deterministic, minimum-sample-guarded rolling average (see contract above).
  const rollingAverage = useMemo(() => {
    const windowSize = trendWindowSize(ratingData.length)
    const sufficient = ratingData.length >= TREND_MIN_SAMPLE
    const points: RollingAveragePoint[] = []
    if (sufficient) {
      for (let i = windowSize - 1; i < ratingData.length; i++) {
        const window = ratingData.slice(i - windowSize + 1, i + 1)
        const sum = window.reduce((acc, point) => acc + point.rating, 0)
        points.push({
          timestamp: ratingData[i].timestamp,
          rating: sum / window.length,
          count: window.length,
        })
      }
    }
    return { points, windowSize, sufficient }
  }, [ratingData])

  const plot = useMemo(() => {
    const minTime = ratingData[0]?.timestamp.getTime() ?? 0
    const maxTime = ratingData[ratingData.length - 1]?.timestamp.getTime() ?? 0
    const timeRange = maxTime - minTime || 1
    const ratingRange = RATING_DOMAIN_MAX - RATING_DOMAIN_MIN

    return {
      minTime,
      maxTime,
      x: (timestamp: number) =>
        PLOT_MARGIN.left + ((timestamp - minTime) / timeRange) * viewPlotWidth,
      // Clamp so an out-of-range value can never escape the plot bounds.
      y: (rating: number) => {
        const bounded = Math.min(RATING_DOMAIN_MAX, Math.max(RATING_DOMAIN_MIN, rating))
        return PLOT_MARGIN.top + PLOT_HEIGHT - ((bounded - RATING_DOMAIN_MIN) / ratingRange) * PLOT_HEIGHT
      },
    }
  }, [ratingData, viewPlotWidth])

  const xTicks = useMemo(() => {
    if (ratingData.length === 0) return []
    const { minTime, maxTime } = plot
    const affordableTicks = Math.max(2, Math.floor(viewPlotWidth / X_TICK_LABEL_BUDGET_PX))
    const tickCount = Math.min(affordableTicks, ratingData.length)
    const dayLevel = maxTime - minTime <= DAY_LEVEL_TICK_SPAN_MS
    const step = tickCount > 1 ? (maxTime - minTime) / (tickCount - 1) : 0
    const dateFormat: Intl.DateTimeFormatOptions = dayLevel
      ? { month: 'short', day: 'numeric' }
      : { month: 'short', year: 'numeric' }

    return Array.from({ length: tickCount }, (_, i) => {
      const value = tickCount > 1 ? minTime + i * step : minTime
      return {
        value,
        label: new Date(value).toLocaleDateString(undefined, dateFormat),
      }
    })
  }, [ratingData, plot, viewPlotWidth])

  // Whole-star ticks across the fixed rating domain keep the vertical scale
  // honest instead of stretching a narrow spread across the whole plot.
  const yTicks = useMemo(() => {
    const ticks: { value: number; label: string }[] = []
    for (let rating = 1; rating <= RATING_DOMAIN_MAX; rating += 1) {
      ticks.push({ value: rating, label: formatRating(rating) })
    }
    return ticks
  }, [])

  const plottedCount = ratingData.length
  const unloadedRatings = totalRatings != null && plottedCount < totalRatings ? totalRatings : null

  // Tooltip placement helpers keep the overlay inside the card when a point sits
  // near the right or top edge of the plot.
  function tooltipXShift(timestamp: number): string {
    return plot.x(timestamp) - PLOT_MARGIN.left > viewPlotWidth / 2
      ? 'translateX(calc(-100% - 12px))'
      : 'translateX(12px)'
  }

  function tooltipYShift(rating: number): string {
    return PLOT_MARGIN.top + PLOT_HEIGHT - plot.y(rating) > 60
      ? 'translateY(12px)'
      : 'translateY(calc(-100% - 12px))'
  }

  if (plottedCount === 0) {
    return (
      <div
        className={`rounded-2xl border p-4 md:p-6 ${className}`}
        style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}
      >
        <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          No rating history available for this creator yet.
        </p>
      </div>
    )
  }

  const tooltipPoint = hoveredPoint
  // Keep the overlay inside the card at narrow widths instead of letting it
  // escape the chart on the plot edges.
  const tooltipOffset = tooltipPoint
    ? {
        left: `${((plot.x(tooltipPoint.timestamp.getTime()) - PLOT_MARGIN.left) / viewPlotWidth) * 100}%`,
        top: `${((plot.y(tooltipPoint.rating) - PLOT_MARGIN.top) / PLOT_HEIGHT) * 100}%`,
        transform: `${tooltipXShift(tooltipPoint.timestamp.getTime())}, ${tooltipYShift(tooltipPoint.rating)}`,
      }
    : null

  return (
    <div
      className={`rounded-2xl border p-4 md:p-6 ${className}`}
      style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}
    >
      <div
        ref={plotBoxRef}
        className="relative"
        onMouseLeave={dismissSoon}
        onBlur={event => {
          const next = event.relatedTarget
          if (next instanceof Node && event.currentTarget.contains(next)) return
          dismissSoon()
        }}
      >
        <svg
          className="h-auto w-full"
          role="group"
          aria-label="Rating history chart"
          viewBox={`0 0 ${viewPlotWidth + PLOT_MARGIN.left + PLOT_MARGIN.right} ${PLOT_HEIGHT + PLOT_MARGIN.top + PLOT_MARGIN.bottom}`}
        >
          {/* Grid lines */}
          {yTicks.map((tick) => (
            <line
              key={`y-grid-${tick.value}`}
              x1={PLOT_MARGIN.left}
              y1={plot.y(tick.value)}
              x2={viewPlotWidth + PLOT_MARGIN.left}
              y2={plot.y(tick.value)}
              strokeDasharray="2,2"
              style={{ stroke: 'var(--theme-border)' }}
            />
          ))}

          {/* X-axis */}
          <line
            x1={PLOT_MARGIN.left}
            y1={PLOT_HEIGHT + PLOT_MARGIN.top}
            x2={viewPlotWidth + PLOT_MARGIN.left}
            y2={PLOT_HEIGHT + PLOT_MARGIN.top}
            style={{ stroke: 'var(--theme-border)' }}
          />

          {/* Y-axis */}
          <line
            x1={PLOT_MARGIN.left}
            y1={PLOT_MARGIN.top}
            x2={PLOT_MARGIN.left}
            y2={PLOT_HEIGHT + PLOT_MARGIN.top}
            style={{ stroke: 'var(--theme-border)' }}
          />

          {/* X-axis labels */}
          {xTicks.map((tick) => (
            <text
              key={`x-tick-${tick.value}`}
              x={plot.x(tick.value)}
              y={PLOT_HEIGHT + PLOT_MARGIN.top + 20}
              textAnchor="middle"
              className="text-xs"
              style={{ fill: 'var(--theme-text-muted)' }}
            >
              {tick.label}
            </text>
          ))}

          {/* Y-axis labels */}
          {yTicks.map((tick) => (
            <text
              key={`y-tick-${tick.value}`}
              x={PLOT_MARGIN.left - 8}
              y={plot.y(tick.value) + 4}
              textAnchor="end"
              className="text-xs"
              style={{ fill: 'var(--theme-text-muted)' }}
            >
              {tick.label}
            </text>
          ))}

          {/* Rolling average line */}
          {rollingAverage.points.length > 0 && (
            <path
              d={`M ${rollingAverage.points
                .map((point) => `${plot.x(point.timestamp.getTime())},${plot.y(point.rating)}`)
                .join(' L ')}`}
              fill="none"
              strokeDasharray="4,2"
              style={{ stroke: 'var(--theme-comic-accent)', strokeWidth: 2, opacity: 0.8 }}
            />
          )}

          {/* Individual rating points */}
          {ratingData.map((point) => (
            <g
              key={point.issueId}
              onMouseEnter={() => revealPoint(point)}
              onFocus={() => revealPoint(point)}
              onBlur={dismissSoon}
              tabIndex={0}
              role="button"
              aria-label={`${formatRating(point.rating)} stars for ${point.threadTitle} #${point.issueNumber} rated ${point.timestamp.toLocaleDateString()}`}
              className="cursor-pointer focus:outline-none focus-visible:[&>circle]:stroke-[var(--theme-focus-ring)]"
            >
              <circle
                cx={plot.x(point.timestamp.getTime())}
                cy={plot.y(point.rating)}
                r={hoveredPoint?.issueId === point.issueId ? 6 : 4}
                fill="var(--theme-personal-accent)"
              />
            </g>
          ))}
        </svg>

        {/* Real HTML tooltip so the drill-down link stays clickable and reachable by keyboard. */}
        {tooltipPoint && tooltipOffset && (
          <div
            role="tooltip"
            onMouseEnter={cancelDismiss}
            onFocus={cancelDismiss}
            className="pointer-events-auto absolute z-10 w-48 rounded-lg border px-3 py-2 text-xs font-semibold"
            style={{
              backgroundColor: 'var(--theme-bg-page)',
              borderColor: 'var(--theme-border)',
              color: 'var(--theme-text-primary)',
              left: tooltipOffset.left,
              top: tooltipOffset.top,
              transform: tooltipOffset.transform,
            }}
          >
            <div style={{ color: 'var(--theme-personal-accent)' }}>
              {formatRating(tooltipPoint.rating)}★
            </div>
            <div className="mt-1" style={{ color: 'var(--theme-text-muted)' }}>
              {tooltipPoint.timestamp.toLocaleDateString()}
            </div>
            <div className="mt-1">
              <Link
                to={`/thread/${tooltipPoint.threadId}`}
                className="underline hover:no-underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                style={{ color: 'var(--theme-comic-accent)' }}
              >
                {tooltipPoint.threadTitle} #{tooltipPoint.issueNumber}
              </Link>
            </div>
          </div>
        )}
      </div>

      {/* Accessible alternative for screen reader / keyboard users */}
      <table className="sr-only" aria-label="Rating history data">
        <caption className="sr-only">Every plotted rating in chronological order</caption>
        <thead>
          <tr>
            <th scope="col">Issue</th>
            <th scope="col">Rating</th>
            <th scope="col">Date</th>
            <th scope="col">Thread</th>
          </tr>
        </thead>
        <tbody>
          {ratingData.map((point) => (
            <tr key={point.issueId}>
              <td>{point.issueNumber}</td>
              <td>{formatRating(point.rating)}</td>
              <td>{point.timestamp.toLocaleDateString()}</td>
              <td>{point.threadTitle}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {unloadedRatings != null && (
        <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
          Showing {formatCount(plottedCount, 'rating')} of {formatCount(unloadedRatings, 'rating')}.
          More of this creator&apos;s history is still loading.
        </p>
      )}

      {!rollingAverage.sufficient && (
        <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
          Trend needs at least {TREND_MIN_SAMPLE} ratings; this sample ({plottedCount}) is too small.
        </p>
      )}

      {/* Legend */}
      <div
        className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs"
        style={{ color: 'var(--theme-text-muted)' }}
      >
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: 'var(--theme-personal-accent)' }} />
            <span>Individual rating</span>
          </div>
          {rollingAverage.points.length > 0 && (
            <div className="flex items-center gap-1">
              <span className="h-0.5 w-3" style={{ backgroundColor: 'var(--theme-comic-accent)' }} />
              <span>{`Rolling average (${rollingAverage.windowSize} issues)`}</span>
            </div>
          )}
        </div>
        <div>{formatCount(plottedCount, 'rating')}</div>
      </div>
    </div>
  )
}