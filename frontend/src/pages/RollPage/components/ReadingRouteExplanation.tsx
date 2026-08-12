import { useMemo } from 'react'
import Modal from '../../../components/Modal'
import { useContinuityReadiness } from '../../../hooks/useContinuityReadiness'
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
  issueId,
  issueLabel,
  readingOrders,
  connectedThreads,
  onClose,
}: ReadingRouteExplanationProps) {
  const { readiness, isLoading, error, refetch } = useContinuityReadiness(isOpen ? issueId : null)
  const sortedReadingOrders = useMemo(
    () => [...readingOrders].sort((a, b) => a.name.localeCompare(b.name)),
    [readingOrders],
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
      <p className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-500">Why this issue is next</p>

      <section aria-labelledby="eligibility-heading" className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
        <h3 id="eligibility-heading" className="text-xs font-black text-stone-200">Continuity eligibility</h3>
        {issueId == null ? (
          <p className="mt-2 text-[11px] text-amber-200">The exact issue identity is unavailable, so eligibility cannot be verified.</p>
        ) : isLoading ? (
          <p className="mt-2 text-[11px] text-stone-400" role="status">Checking authoritative readiness…</p>
        ) : error || !readiness ? (
          <div className="mt-2">
            <p className="text-[11px] text-rose-200" role="alert">Readiness is unavailable. The pending roll has not been changed.</p>
            <button type="button" onClick={refetch} className="mt-3 min-h-11 rounded-xl border border-rose-700/40 px-4 text-xs font-black text-rose-200">Retry readiness</button>
          </div>
        ) : readiness.is_readable ? (
          <div className="mt-2">
            <p className="text-[11px] font-bold text-emerald-300">Currently readable</p>
            <p className="mt-1 text-[11px] leading-relaxed text-stone-400">All known direct prerequisites are satisfied. No unresolved hard prerequisite was returned for this issue.</p>
          </div>
        ) : (
          <div className="mt-2">
            <p className="text-[11px] font-bold text-rose-300">Blocked by continuity</p>
            {readiness.blockers.length > 0 ? (
              <ul className="mt-2 grid gap-2" aria-label="Unresolved direct blockers">
                {readiness.blockers.map((blocker) => (
                  <li key={blocker.rule_id} className="rounded-xl border border-rose-800/30 bg-rose-950/20 p-3">
                    <span className="text-[10px] font-black uppercase tracking-wider text-rose-400">Unresolved direct blocker</span>
                    <p className="mt-1 text-sm font-bold text-stone-200">{blocker.source_label}</p>
                    {blocker.note ? <p className="mt-1 text-[11px] text-stone-400">{blocker.note}</p> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-[11px] text-rose-200">The server marked this issue blocked without returning prerequisite details.</p>
            )}
          </div>
        )}
      </section>

      {sortedReadingOrders.length > 0 ? (
        <section aria-labelledby="named-routes-heading">
          <h3 id="named-routes-heading" className="text-xs font-black text-stone-200">Named reading routes</h3>
          <p className="mt-1 text-[11px] text-stone-500">Membership is informational and does not imply a hard dependency.</p>
          <ul className="mt-2 grid gap-2 md:grid-cols-2">
            {sortedReadingOrders.map((order) => {
              const progress = order.total_items > 0 ? Math.round((order.completed_items / order.total_items) * 100) : 0
              return (
                <li key={order.id} className="rounded-xl border border-blue-800/30 bg-blue-950/15 p-3">
                  <p className="text-sm font-black text-blue-100">{order.name}</p>
                  <p className="mt-1 text-[11px] text-stone-400">{order.completed_items} of {order.total_items} complete · {progress}%</p>
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}

      {connectedThreads.length > 0 ? (
        <section aria-labelledby="connections-heading">
          <h3 id="connections-heading" className="text-xs font-black text-stone-200">Verified connected threads</h3>
          <p className="mt-1 text-[11px] text-stone-500">These verified connections are shown for context, not as an inferred sequence.</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {connectedThreads.map((thread) => (
              <li key={`${thread.thread_id}-${thread.dependency_id}`} className="rounded-full border border-blue-800/40 px-3 py-1.5 text-[11px] font-bold text-blue-200">{thread.title}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </Modal>
  )
}
