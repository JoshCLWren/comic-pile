import { useMemo, useRef, useState } from 'react'
import Link from 'react-router-dom'
import type { CreatorIssueRow } from '../services/api-creators'

interface RatingHistoryChartProps {
  ratedIssues: CreatorIssueRow[]
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

export function RatingHistoryChart({ ratedIssues, className = '' }: RatingHistoryChartProps) {
  const [hoveredPoint, setHoveredPoint] = useState<RatingDataPoint | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  // Process rating data for visualization
  const ratingData = useMemo(() => {
    return ratedIssues
      .filter(issue => issue.effective_rating !== null && issue.rating_timestamp !== null)
      .map(issue => ({
        issueId: issue.issue_id,
        rating: issue.effective_rating!,
        timestamp: new Date(issue.rating_timestamp!),
        threadId: issue.thread_id,
        threadTitle: issue.thread_title,
        issueNumber: issue.issue_number,
      }))
      .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())
  }, [ratedIssues])

  // Calculate rolling average (minimum 5 observations)
  const rollingAverageData = useMemo(() => {
    if (ratingData.length < 5) return []
    
    const windowSize = Math.min(5, Math.floor(ratingData.length * 0.3))
    const averages: RollingAveragePoint[] = []
    
    for (let i = windowSize - 1; i < ratingData.length; i++) {
      const window = ratingData.slice(i - windowSize + 1, i + 1)
      const sum = window.reduce((acc, point) => acc + point.rating, 0)
      const avg = sum / window.length
      
      averages.push({
        timestamp: ratingData[i].timestamp,
        rating: avg,
        count: window.length,
      })
    }
    
    return averages
  }, [ratingData])

  // Chart dimensions and margins
  const margin = { top: 20, right: 20, bottom: 40, left: 60 }
  const width = 800 - margin.left - margin.right
  const height = 300 - margin.top - margin.bottom

  // Data scales
  const xScale = useMemo(() => {
    if (ratingData.length === 0) return () => 0
    
    const timestamps = ratingData.map(d => d.timestamp.getTime())
    const minX = Math.min(...timestamps)
    const maxX = Math.max(...timestamps)
    const range = maxX - minX || 1
    
    return (timestamp: number) => margin.left + ((timestamp - minX) / range) * width
  }, [ratingData, width])

  const yScale = useMemo(() => {
    if (ratingData.length === 0) return () => 0
    
    const ratings = ratingData.map(d => d.rating)
    const minY = Math.min(...ratings)
    const maxY = Math.max(...ratings)
    const range = maxY - minY || 1
    
    return (rating: number) => margin.top + height - ((rating - minY) / range) * height
  }, [ratingData, height])

  // Generate axis labels
  const xTicks = useMemo(() => {
    if (ratingData.length === 0) return []
    
    const timestamps = ratingData.map(d => d.timestamp.getTime())
    const minX = Math.min(...timestamps)
    const maxX = Math.max(...timestamps)
    
    // Generate 5-6 ticks
    const tickCount = Math.min(6, ratingData.length)
    const step = (maxX - minX) / (tickCount - 1)
    
    return Array.from({ length: tickCount }, (_, i) => ({
      value: minX + i * step,
      label: new Date(minX + i * step).toLocaleDateString(undefined, {
        month: 'short',
        year: i === 0 || i === tickCount - 1 ? 'numeric' : undefined,
      }),
    }))
  }, [ratingData])

  const yTicks = useMemo(() => {
    if (ratingData.length === 0) return []
    
    const ratings = ratingData.map(d => d.rating)
    const minY = Math.min(...ratings)
    const maxY = Math.max(...ratings)
    
    // Generate ticks at 0.5 intervals
    const ticks = []
    for (let rating = Math.ceil(minY * 2) / 2; rating <= maxY; rating += 0.5) {
      ticks.push({
        value: rating,
        label: rating.toFixed(1),
      })
    }
    
    return ticks
  }, [ratingData])

  if (ratingData.length === 0) {
    return (
      <div className={`rounded-2xl border p-4 md:p-6 ${className}`} style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
        <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          No rating history available for this creator yet.
        </p>
      </div>
    )
  }

  return (
    <div className={`rounded-2xl border p-4 md:p-6 ${className}`} style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
      <svg
        ref={svgRef}
        className="w-full"
        viewBox={`0 0 ${width + margin.left + margin.right} ${height + margin.top + margin.bottom}`}
        style={{ height: height + margin.top + margin.bottom }}
      >
        {/* Grid lines */}
        {yTicks.map((tick) => (
          <line
            key={`y-grid-${tick.value}`}
            x1={margin.left}
            y1={yScale(tick.value)}
            x2={width + margin.left}
            y2={yScale(tick.value)}
            stroke="none"
            strokeDasharray="2,2"
            style={{ stroke: 'var(--theme-border)' }}
          />
        ))}

        {/* X-axis */}
        <line
          x1={margin.left}
          y1={height + margin.top}
          x2={width + margin.left}
          y2={height + margin.top}
          style={{ stroke: 'var(--theme-border)' }}
        />

        {/* Y-axis */}
        <line
          x1={margin.left}
          y1={margin.top}
          x2={margin.left}
          y2={height + margin.top}
          style={{ stroke: 'var(--theme-border)' }}
        />

        {/* X-axis labels */}
        {xTicks.map((tick) => (
          <g key={`x-tick-${tick.value}`}>
            <text
              x={xScale(tick.value)}
              y={height + margin.top + 20}
              textAnchor="middle"
              className="text-xs"
              style={{ fill: 'var(--theme-text-muted)' }}
            >
              {tick.label}
            </text>
          </g>
        ))}

        {/* Y-axis labels */}
        {yTicks.map((tick) => (
          <g key={`y-tick-${tick.value}`}>
            <text
              x={margin.left - 10}
              y={yScale(tick.value) + 4}
              textAnchor="end"
              className="text-xs"
              style={{ fill: 'var(--theme-text-muted)' }}
            >
              {tick.label}
            </text>
          </g>
        ))}

        {/* Rolling average line */}
        {rollingAverageData.length > 0 && (
          <path
            d={rollingAverageData
              .map((point, i) => `${xScale(point.timestamp.getTime())},${yScale(point.rating)}`)
              .join(' L ')}
            fill="none"
            style={{ 
              stroke: 'var(--theme-comic-accent)', 
              strokeWidth: 2,
              strokeDasharray: '4,2',
              opacity: 0.8,
            }}
          />
        )}

        {/* Individual rating points */}
        {ratingData.map((point) => (
          <g
            key={point.issueId}
            onMouseEnter={() => setHoveredPoint(point)}
            onMouseLeave={() => setHoveredPoint(null)}
            className="cursor-pointer"
          >
            <circle
              cx={xScale(point.timestamp.getTime())}
              cy={yScale(point.rating)}
              r={hoveredPoint?.issueId === point.issueId ? 6 : 4}
              fill="var(--theme-personal-accent)"
              style={{
                transition: 'r 0.2s ease',
              }}
            />
          </g>
        ))}

        {/* Hover tooltip */}
        {hoveredPoint && (
          <g>
            {/* Vertical line at hovered point */}
            <line
              x1={xScale(hoveredPoint.timestamp.getTime())}
              y1={margin.top}
              x2={xScale(hoveredPoint.timestamp.getTime())}
              y2={height + margin.top}
              stroke="var(--theme-text-dim)"
              strokeDasharray="2,2"
            />
            
            {/* Tooltip background */}
            <foreignObject
              x={xScale(hoveredPoint.timestamp.getTime()) + 10}
              y={yScale(hoveredPoint.rating) - 40}
              width={200}
              height={80}
            >
              <div className="px-3 py-2 rounded-lg border text-xs font-semibold pointer-events-none"
                   style={{ 
                     backgroundColor: 'var(--theme-bg-page)', 
                     borderColor: 'var(--theme-border)',
                     color: 'var(--theme-text-primary)',
                   }}>
                <div style={{ color: 'var(--theme-personal-accent)' }}>
                  {hoveredPoint.rating.toFixed(1)}★
                </div>
                <div className="mt-1" style={{ color: 'var(--theme-text-muted)' }}>
                  {hoveredPoint.timestamp.toLocaleDateString()}
                </div>
                <div className="mt-1">
                  <Link
                    to={`/thread/${hoveredPoint.threadId}`}
                    className="underline hover:no-underline"
                    style={{ color: 'var(--theme-comic-accent)' }}
                  >
                    {hoveredPoint.threadTitle} #{hoveredPoint.issueNumber}
                  </Link>
                </div>
              </div>
            </foreignObject>
          </g>
        )}
      </svg>

      {/* Legend */}
      <div className="mt-4 flex items-center justify-between text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-full" style={{ backgroundColor: 'var(--theme-personal-accent)' }} />
            <span>Individual rating</span>
          </div>
          {rollingAverageData.length > 0 && (
            <div className="flex items-center gap-1">
              <div className="w-3 h-0.5" style={{ backgroundColor: 'var(--theme-comic-accent)' }} />
              <span>Rolling average (5 issues)</span>
            </div>
          )}
        </div>
        <div>
          {ratingData.length} rating{ratingData.length === 1 ? '' : 's'}
        </div>
      </div>
    </div>
  )
}