import { useMemo } from 'react'
import Modal from '../../../components/Modal'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'

interface ReadingRouteExplanationProps {
  isOpen: boolean
  issueId: number | null | undefined
  issueLabel: string
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  onClose: () => void
}

export function ReadingRouteExplanation({
  isOpen,
  issueId: _issueId,
  issueLabel,
  readingOrders,
  connectedThreads,
  onClose,
}: ReadingRouteExplanationProps) {
  const sortedReadingOrders = useMemo(
    () => [...readingOrders].sort((a, b) => a.name.localeCompare(b.name)),
    [readingOrders],
  )
  const upstreamThreads = useMemo(
    () => connectedThreads.filter(
      (thread) => thread.connection_type === 'blocked_by' || thread.connection_type === 'blocks & blocked_by',
    ),
    [connectedThreads],
  )
  const downstreamThreads = useMemo(
    () => connectedThreads.filter(
      (thread) => thread.connection_type === 'blocks' || thread.connection_type === 'blocks & blocked_by',
    ),
    [connectedThreads],
  )

  return (
    <Modal
      isOpen={isOpen}
      title={issueLabel}
      onClose={onClose}
      autoFocus={false}
      data-testid="reading-route-explanation"
      overlayClassName="bg-black/70 backdrop-blur-sm"
    >
      <p className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-500">
        Why this issue is next
      </p>
      <p className="mt-2 text-[11px] leading-relaxed text-stone-400">
        Roll already selected this issue. The context below describes recorded reading-order and dependency relationships without running a second verification request.
      </p>

      {upstreamThreads.length > 0 ? (
        <section className="mt-4 rounded-2xl border border-blue-900/30 bg-blue-950/15 p-3" aria-labelledby="upstream-heading">
          <h3 id="upstream-heading" className="text-xs font-black text-blue-300">Recorded prerequisites</h3>
          <ul className="mt-2 flex flex-wrap gap-2" aria-label="Recorded prerequisite threads">
            {upstreamThreads.map((thread) => (
              <li key={`${thread.thread_id}-${thread.dependency_id}`} className="rounded-full border border-blue-700/40 px-3 py-1 text-[11px] font-bold text-blue-200">
                {thread.title}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {downstreamThreads.length > 0 ? (
        <section className="mt-4 rounded-2xl border border-emerald-800/30 bg-emerald-950/15 p-3" aria-labelledby="downstream-heading">
          <h3 id="downstream-heading" className="text-xs font-black text-emerald-300">Related later threads</h3>
          <ul className="mt-2 flex flex-wrap gap-2" aria-label="Related later threads">
            {downstreamThreads.map((thread) => (
              <li key={`${thread.thread_id}-${thread.dependency_id}`} className="rounded-full border border-emerald-700/40 px-3 py-1 text-[11px] font-bold text-emerald-200">
                {thread.title}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {sortedReadingOrders.length > 0 ? (
        <section className="mt-4 rounded-2xl border border-white/10 bg-white/[0.04] p-3" aria-labelledby="routes-heading">
          <h3 id="routes-heading" className="text-xs font-black text-stone-200">Reading-order context</h3>
          <p className="mt-1 text-[11px] text-stone-400">
            Membership is informational here. Roll remains the source of truth for what is next.
          </p>
          <ul className="mt-2 grid gap-2" aria-label="Reading orders">
            {sortedReadingOrders.map((order) => (
              <li key={order.id} className="rounded-xl border border-white/10 bg-black/20 p-2 text-[11px] text-stone-300">
                <span className="font-bold text-stone-100">{order.name}</span>
                <span className="ml-2 text-stone-500">{order.completed_items}/{order.total_items}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Modal>
  )
}
