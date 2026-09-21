/**
 * Custom SVG flowchart for visualizing thread dependency relationships.
 *
 * Features: zoom/pan, node dragging, hover tooltips, blocked node styling,
 * blocking edge pulse animation, pagination for large graphs.
 */

import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { layoutGraph, NODE_WIDTH, NODE_HEIGHT, ISSUE_NODE_WIDTH, ISSUE_NODE_HEIGHT } from '../utils/graphLayout'
import type { Thread, FlowchartDependency, FlowchartNode } from '../types'

const PAGE_SIZE = 50
const LARGE_GRAPH_THRESHOLD = 100
const MIN_SCALE = 0.25
const MAX_SCALE = 3
const ZOOM_STEP = 1.2

interface DependencyFlowchartProps {
  threads: Thread[]
  dependencies: FlowchartDependency[]
  blockedIds: Set<number>
  issueNodes?: FlowchartNode[]
}

interface Transform {
  x: number
  y: number
  scale: number
}

interface TooltipState {
  node: FlowchartNode
  clientX: number
  clientY: number
}

/**
 * Truncate text to fit within a given pixel width at ~7px per character.
 *
 * @param text - Text to truncate
 * @param maxChars - Maximum character count
 * @returns Truncated text with ellipsis if needed
 */
function truncateTitle(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text
  return text.slice(0, maxChars - 1) + '…'
}

/**
 * Dependency flowchart component that renders an interactive SVG graph.
 *
 * @param props - Component props containing threads, dependencies, and blocked IDs
 * @returns React element rendering the flowchart
 */
export default function DependencyFlowchart({
  threads,
  dependencies,
  blockedIds,
  issueNodes = [],
}: DependencyFlowchartProps) {
   const [transform, setTransform] = useState<Transform>({ x: 0, y: 0, scale: 1 })
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const [draggedNodeId, setDraggedNodeId] = useState<number | null>(null)
  const [nodeOffsets, setNodeOffsets] = useState<Map<number, { dx: number; dy: number }>>(
    new Map(),
  )
  const [isPanning, setIsPanning] = useState(false)
  const [panStart, setPanStart] = useState<{ x: number; y: number } | null>(null)
  const [page, setPage] = useState(0)

  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragAnchorRef = useRef<{ x: number; y: number } | null>(null)

  // Pagination: slice threads for display
  const totalPages = Math.ceil(threads.length / PAGE_SIZE)

  // Memoize layout computation so pan/drag don't trigger expensive recalculation
  const layout = useMemo(() => {
    const paginatedThreads = threads.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
    const visibleThreadIds = new Set(paginatedThreads.map((t) => t.id))
    
    // Filter dependencies to only those involving visible nodes
    const visibleDependencies = dependencies.filter((d) => {
      // Issue-level dependency: check parent thread IDs from issue nodes
      if (d.is_issue_level) {
        const sourceParent = issueNodes?.find((n) => n.id === d.source_id)
        const targetParent = issueNodes?.find((n) => n.id === d.target_id)
        if (sourceParent?.parentThreadId && targetParent?.parentThreadId) {
          return visibleThreadIds.has(sourceParent.parentThreadId) && visibleThreadIds.has(targetParent.parentThreadId)
        }
        return false
      }
      // Thread-level dependency: check thread IDs
      return (
        visibleThreadIds.has(d.source_id) &&
        visibleThreadIds.has(d.target_id)
      )
    })
    
    // Filter issue nodes to only those whose parent threads are visible
    const visibleIssueNodes = (issueNodes ?? []).filter(
      (n) => n.parentThreadId !== undefined && visibleThreadIds.has(n.parentThreadId)
    )
    
    return layoutGraph(paginatedThreads, visibleDependencies, blockedIds, visibleIssueNodes)
  }, [threads, page, dependencies, blockedIds, issueNodes])

  // Apply node drag offsets
  const adjustedNodes = useMemo(
    () =>
      layout.nodes.map((node) => {
        const offset = nodeOffsets.get(node.id)
        if (offset) {
          return { ...node, x: node.x + offset.dx, y: node.y + offset.dy }
        }
        return node
      }),
    [layout.nodes, nodeOffsets],
  )

  // Recompute edge paths with adjusted positions
  const adjustedEdges = useMemo(() => {
    const nodePositions = new Map(adjustedNodes.map((n) => [n.id, n]))
    return layout.edges.map((edge) => {
      const source = nodePositions.get(edge.sourceId)
      const target = nodePositions.get(edge.targetId)
      if (!source || !target) return edge

      const srcW = source.isIssueNode ? ISSUE_NODE_WIDTH : NODE_WIDTH
      const srcH = source.isIssueNode ? ISSUE_NODE_HEIGHT : NODE_HEIGHT
      const tgtW = target.isIssueNode ? ISSUE_NODE_WIDTH : NODE_WIDTH

      const sx = source.x + srcW / 2
      const sy = source.y + srcH
      const tx = target.x + tgtW / 2
      const ty = target.y
      const midY = (sy + ty) / 2
      const path = `M ${sx} ${sy} C ${sx} ${midY}, ${tx} ${midY}, ${tx} ${ty}`
      return { ...edge, path }
    })
  }, [layout.edges, adjustedNodes])

  // Reset state when the set of threads changes
  const threadKey = useMemo(() => threads.map((t) => t.id).join(','), [threads])
  useEffect(() => {
    setPage(0)
    setNodeOffsets(new Map())
    setTransform({ x: 0, y: 0, scale: 1 })
  }, [threadKey])

  const handleWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP
    const rect = e.currentTarget.getBoundingClientRect()
    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
    setTransform((prev) => {
      const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, prev.scale * delta))
      // Zoom toward cursor position
      const scaleFactor = newScale / prev.scale
      return {
        x: cx - (cx - prev.x) * scaleFactor,
        y: cy - (cy - prev.y) * scaleFactor,
        scale: newScale,
      }
    })
  }, [])

  const handleZoomIn = useCallback(() => {
    setTransform((prev) => ({
      ...prev,
      scale: Math.min(MAX_SCALE, prev.scale * ZOOM_STEP),
    }))
  }, [])

  const handleZoomOut = useCallback(() => {
    setTransform((prev) => ({
      ...prev,
      scale: Math.max(MIN_SCALE, prev.scale / ZOOM_STEP),
    }))
  }, [])

  const handleReset = useCallback(() => {
    setTransform({ x: 0, y: 0, scale: 1 })
    setNodeOffsets(new Map())
  }, [])

  // Pan handling
  const handleSvgMouseDown = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      // Only pan if clicking on the SVG background (not a node)
      // SAFETY: SVG event targets are always DOM Elements in the browser.
      if ((e.target as Element).closest('.flowchart-node')) return
      setIsPanning(true)
      setPanStart({ x: e.clientX - transform.x, y: e.clientY - transform.y })
    },
    [transform.x, transform.y],
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (isPanning && panStart) {
        setTransform((prev) => ({
          ...prev,
          x: e.clientX - panStart.x,
          y: e.clientY - panStart.y,
        }))
        return
      }

      if (draggedNodeId !== null) {
        const svgRect = svgRef.current?.getBoundingClientRect()
        if (!svgRect) return

        const svgX = (e.clientX - svgRect.left - transform.x) / transform.scale
        const svgY = (e.clientY - svgRect.top - transform.y) / transform.scale

        const originalNode = layout.nodes.find((n) => n.id === draggedNodeId)
        if (!originalNode) return

        const nodeW = originalNode.isIssueNode ? ISSUE_NODE_WIDTH : NODE_WIDTH
        const nodeH = originalNode.isIssueNode ? ISSUE_NODE_HEIGHT : NODE_HEIGHT
        const anchor = dragAnchorRef.current ?? { x: 0, y: 0 }

        setNodeOffsets((prev) => {
          const next = new Map(prev)
          next.set(draggedNodeId, {
            dx: svgX - originalNode.x - nodeW / 2 - anchor.x,
            dy: svgY - originalNode.y - nodeH / 2 - anchor.y,
          })
          return next
        })
      }
    },
    [isPanning, panStart, draggedNodeId, transform, layout.nodes],
  )

  const handleMouseUp = useCallback(() => {
    setIsPanning(false)
    setPanStart(null)
    setDraggedNodeId(null)
    dragAnchorRef.current = null
  }, [])

  const handleNodeMouseDown = useCallback(
    (e: React.MouseEvent, nodeId: number) => {
      e.stopPropagation()
      setDraggedNodeId(nodeId)

      const svgRect = svgRef.current?.getBoundingClientRect()
      if (!svgRect) return

      const svgX = (e.clientX - svgRect.left - transform.x) / transform.scale
      const svgY = (e.clientY - svgRect.top - transform.y) / transform.scale

      const originalNode = layout.nodes.find((n) => n.id === nodeId)
      if (!originalNode) return

      const nodeW = originalNode.isIssueNode ? ISSUE_NODE_WIDTH : NODE_WIDTH
      const nodeH = originalNode.isIssueNode ? ISSUE_NODE_HEIGHT : NODE_HEIGHT
      const currentOffset = nodeOffsets.get(nodeId) ?? { dx: 0, dy: 0 }
      const currentCenterX = originalNode.x + currentOffset.dx + nodeW / 2
      const currentCenterY = originalNode.y + currentOffset.dy + nodeH / 2
      dragAnchorRef.current = {
        x: svgX - currentCenterX,
        y: svgY - currentCenterY,
      }
    },
    [layout.nodes, nodeOffsets, transform.x, transform.y, transform.scale],
  )

  const handleNodeMouseEnter = useCallback(
    (e: React.MouseEvent, node: FlowchartNode) => {
      if (draggedNodeId !== null) return
      setTooltip({ node, clientX: e.clientX, clientY: e.clientY })
    },
    [draggedNodeId],
  )

  const handleNodeMouseLeave = useCallback(() => {
    setTooltip(null)
  }, [])

  const isLargeGraph = threads.length > LARGE_GRAPH_THRESHOLD

  if (adjustedNodes.length === 0) {
    return (
      <div className="p-8 text-center text-[var(--theme-text-muted)] text-sm font-semibold uppercase tracking-wide" data-testid="flowchart-empty">
        No dependency relationships to visualize
      </div>
    )
  }

  const svgWidth = Math.max(layout.width, 300)
  const svgHeight = Math.max(layout.height, 200)

  return (
    <div 
      className="relative w-full border border-[var(--theme-border)] rounded-lg overflow-hidden bg-[var(--theme-bg-panel)]" 
      ref={containerRef} 
      data-testid="flowchart-container"
    >
      <style>{`
        @keyframes pulse-edge {
          0%, 100% { stroke-opacity: 0.7; }
          50% { stroke-opacity: 0.3; }
        }
        @media (prefers-reduced-motion: reduce) {
          .flowchart-edge-blocking {
            animation: none !important;
            stroke-opacity: 0.7;
          }
        }
      `}</style>
      
      {isLargeGraph && (
        <div className="p-4 border border-[color-mix(in_srgb,var(--theme-warning)_30%,transparent)] rounded-lg bg-[color-mix(in_srgb,var(--theme-warning)_8%,transparent)] text-center" data-testid="flowchart-warning">
          <h3 className="m-0 mb-2 text-[var(--theme-warning)] text-sm font-extrabold uppercase tracking-wide">⚠️ Large Dependency Graph</h3>
          <p className="m-0 text-[var(--theme-text-muted)] text-xs">
            This view has {threads.length} related threads. Showing {PAGE_SIZE} threads per page for performance.
          </p>
        </div>
      )}
      
      <div className="relative w-full h-full">
        <svg
          ref={svgRef}
          className="dependency-flowchart w-full cursor-grab active:cursor-grabbing touch-none"
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          style={{ height: Math.min(svgHeight + 40, 500) }}
          onWheel={handleWheel}
          onMouseDown={handleSvgMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          data-testid="flowchart-svg"
        >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="10"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" style={{ fill: 'color-mix(in srgb, var(--theme-text-muted) 60%, transparent)' }} />
          </marker>
          <marker
            id="arrowhead-blocking"
            markerWidth="10"
            markerHeight="7"
            refX="10"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" style={{ fill: 'var(--theme-danger)' }} />
          </marker>
        </defs>

        <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.scale})`}>
          {/* Render edges */}
          {adjustedEdges.map((edge) => {
            const marker = edge.isBlocking && !edge.isIssueLevel
              ? 'url(#arrowhead-blocking)'
              : 'url(#arrowhead)'
            
            return (
              <path
                key={edge.id}
                d={edge.path}
                stroke="none"
                fill="none"
                className={edge.isBlocking ? 'flowchart-edge-blocking' : undefined}
                style={edge.isIssueLevel ? { 
                  stroke: 'var(--theme-continuity-accent)', 
                  strokeWidth: 2, 
                  strokeDasharray: '6 4', 
                  strokeOpacity: 0.6 
                } : edge.isBlocking ? { 
                  stroke: 'var(--theme-danger)', 
                  strokeWidth: 2.5,
                  animation: 'pulse-edge 2s ease-in-out infinite'
                } : { 
                  stroke: 'color-mix(in srgb, var(--theme-text-muted) 40%, transparent)', 
                  strokeWidth: 2 
                }}
                markerEnd={marker}
                data-testid={`flowchart-edge-${edge.sourceId}-${edge.targetId}`}
              />
            )
          })}

          {/* Render nodes */}
          {adjustedNodes.map((node) => {
            const nodeW = node.isIssueNode ? ISSUE_NODE_WIDTH : NODE_WIDTH
            const nodeH = node.isIssueNode ? ISSUE_NODE_HEIGHT : NODE_HEIGHT
            const maxChars = node.isIssueNode ? 14 : 18
            
            const rectStyle = node.isBlocked 
              ? { fill: 'color-mix(in srgb, var(--theme-danger) 30%, transparent)', stroke: 'var(--theme-danger)' }
              : node.isIssueNode 
                ? { fill: 'color-mix(in srgb, var(--theme-continuity-accent) 15%, transparent)', stroke: 'var(--theme-continuity-accent)' }
                : { fill: 'var(--theme-bg-page)', stroke: 'var(--theme-text-dim)' }
            
            return (
              <g
                key={node.id}
                transform={`translate(${node.x}, ${node.y})`}
                className={`cursor-grab active:cursor-grabbing`}
                onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
                onMouseEnter={(e) => handleNodeMouseEnter(e, node)}
                onMouseLeave={handleNodeMouseLeave}
                data-testid={`flowchart-node-${node.id}`}
              >
                <rect
                  width={nodeW}
                  height={nodeH}
                  rx={node.isIssueNode ? 12 : 0}
                  strokeWidth="1.5"
                  style={rectStyle}
                  className="transition-all duration-150"
                />
                <text
                  x={nodeW / 2}
                  y={nodeH / 2 + (node.isIssueNode ? 3 : 4)}
                  textAnchor="middle"
                  fill="var(--theme-text-primary)"
                  fontSize={node.isIssueNode ? 11 : 12}
                  fontWeight="700"
                  pointerEvents="none"
                >
                  {truncateTitle(node.title, maxChars)}
                </text>

                {node.isBlocked && !node.isIssueNode && (
                  <text
                    x={nodeW - 8}
                    y={16}
                    textAnchor="end"
                    fontSize="14px"
                    pointerEvents="none"
                  >
                    🔒
                  </text>
                )}
              </g>
            )
          })}
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && containerRef.current && (
        <div
          className="absolute z-60 px-3 py-2 rounded-lg bg-[var(--theme-bg-page)] border border-[var(--theme-border)] text-[var(--theme-text-primary)] text-xs font-semibold pointer-events-none whitespace-nowrap max-w-[250px] overflow-hidden text-ellipsis"
          style={{
            left: tooltip.clientX - containerRef.current.getBoundingClientRect().left + 12,
            top: tooltip.clientY - containerRef.current.getBoundingClientRect().top - 30,
          }}
          data-testid="flowchart-tooltip"
        >
          {tooltip.node.title}
          {tooltip.node.isBlocked && ' (blocked)'}
        </div>
      )}

      {/* Zoom controls */}
      <div className="absolute bottom-3 right-3 flex gap-1" data-testid="flowchart-controls">
        <button 
          type="button" 
          onClick={handleZoomIn} 
          aria-label="Zoom in"
          className="w-8 h-8 flex items-center justify-center rounded-lg bg-[var(--theme-bg-page)] border border-[var(--theme-border)] text-[var(--theme-text-primary)] text-sm font-bold cursor-pointer transition-all duration-150 hover:bg-[var(--theme-bg-panel)] hover:border-[color-mix(in_srgb,white_25%,transparent)]"
        >
          +
        </button>
        <button 
          type="button" 
          onClick={handleZoomOut} 
          aria-label="Zoom out"
          className="w-8 h-8 flex items-center justify-center rounded-lg bg-[var(--theme-bg-page)] border border-[var(--theme-border)] text-[var(--theme-text-primary)] text-sm font-bold cursor-pointer transition-all duration-150 hover:bg-[var(--theme-bg-panel)] hover:border-[color-mix(in_srgb,white_25%,transparent)]"
        >
          −
        </button>
        <button 
          type="button" 
          onClick={handleReset} 
          aria-label="Reset view"
          className="w-8 h-8 flex items-center justify-center rounded-lg bg-[var(--theme-bg-page)] border border-[var(--theme-border)] text-[var(--theme-text-primary)] text-sm font-bold cursor-pointer transition-all duration-150 hover:bg-[var(--theme-bg-panel)] hover:border-[color-mix(in_srgb,white_25%,transparent)]"
        >
          ⟳
        </button>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          className="absolute bottom-3 left-3 flex items-center gap-1"
        >
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="w-8 h-8 flex items-center justify-center rounded-lg bg-[var(--theme-bg-page)] border border-[var(--theme-border)] text-[var(--theme-text-primary)] text-sm font-bold cursor-pointer transition-all duration-150 disabled:opacity-40"
            aria-label="Previous page"
          >
            ←
          </button>
          <span
            className="text-[rgba(203,213,225,0.7)] text-xs font-bold"
          >
            {page + 1}/{totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page === totalPages - 1}
            className="w-8 h-8 flex items-center justify-center rounded-lg bg-[var(--theme-bg-page)] border border-[var(--theme-border)] text-[var(--theme-text-primary)] text-sm font-bold cursor-pointer transition-all duration-150 disabled:opacity-40"
            aria-label="Next page"
          >
            →
          </button>
        </div>
      )}
      </div>
    </div>
  )
}
