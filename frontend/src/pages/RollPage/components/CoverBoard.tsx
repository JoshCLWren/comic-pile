import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import type { IssueCard } from '../../../services/issueCardsApi'
import type { RollBootstrapThread } from '../../../types/rollBootstrap'
import {
  allocateCoverFaces,
  computeCoverBoardLayout,
} from '../coverBoardLayout'
import { RollCover } from './RollCover'

interface CoverBoardProps {
  pool: RollBootstrapThread[]
  cardByIssueId: Map<number, IssueCard>
  dieSize: number
  selectedThreadId: number | null
  /** The real die renderer, owned by the page so it stays a single instance. */
  dieSlot: ReactNode
  onThreadClick: (thread: RollBootstrapThread) => void
}

/**
 * Centered cover-first board for desktop/tablet Roll (issue #5981). The die is
 * the only roll control and always sits in the middle row; every eligible face
 * keeps its authoritative order and number. Geometry is measured, not inferred
 * from a Tailwind breakpoint, so an expanded or collapsed sidebar simply
 * changes the available width.
 */
export function CoverBoard({
  pool,
  cardByIssueId,
  dieSize,
  selectedThreadId,
  dieSlot,
  onThreadClick,
}: CoverBoardProps) {
  const boardRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(900)
  const [viewportHeight, setViewportHeight] = useState(() =>
    typeof window === 'undefined' ? 900 : window.innerHeight,
  )

  useEffect(() => {
    const node = boardRef.current
    if (node == null) return
    const measure = () => setWidth(node.clientWidth || 900)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const onResize = () => setViewportHeight(window.innerHeight)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const layout = computeCoverBoardLayout({ width, viewportHeight, dieSize })
  const faceCount = Math.min(pool.length, dieSize)
  const [topCount, middleCount, bottomCount] = allocateCoverFaces(faceCount, layout.arrangement)
  const faces = pool.slice(0, faceCount).map((thread, index) => ({
    thread,
    face: index + 1,
  }))
  const middleLeft = Math.ceil(middleCount / 2)

  // SAFETY: the custom properties are consumed by the board CSS, not by React's CSSProperties type.
  const boardStyle = {
    '--roll-cover-w': `${layout.coverWidth}px`,
    '--roll-gap': `${layout.gap}px`,
    '--roll-die-w': `${layout.dieWidth}px`,
  } as CSSProperties

  const cover = (entry: (typeof faces)[number]) => (
    <RollCover
      key={entry.thread.id}
      thread={entry.thread}
      face={entry.face}
      card={entry.thread.issue_id != null ? cardByIssueId.get(entry.thread.issue_id) ?? null : null}
      winner={selectedThreadId != null && Number(selectedThreadId) === entry.thread.id}
      onOpen={() => onThreadClick(entry.thread)}
    />
  )

  const die = dieSlot

  return (
    <div ref={boardRef} className="roll-cover-board" style={boardStyle} data-testid="roll-cover-board">
      {topCount > 0 ? (
        <div className="roll-cover-row">{faces.slice(0, topCount).map(cover)}</div>
      ) : null}
      <div className="roll-cover-row roll-cover-row-middle">
        {faces.slice(topCount, topCount + middleLeft).map(cover)}
        {die}
        {faces.slice(topCount + middleLeft, topCount + middleCount).map(cover)}
      </div>
      {bottomCount > 0 ? (
        <div className="roll-cover-row">
          {faces.slice(topCount + middleCount, topCount + middleCount + bottomCount).map(cover)}
        </div>
      ) : null}
    </div>
  )
}
