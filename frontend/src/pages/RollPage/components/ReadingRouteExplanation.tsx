import { useEffect, useRef } from 'react'
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
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const { readiness, isLoading, error, refetch } = useContinuityReadiness(isOpen ? issueId : null)

  useEffect(() => {
    if (!isOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButtonRef.current?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end bg-black/70 p-0 backdrop-blur-sm md:items-center md:justify-center md:p-6">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="route-explanation-heading"
        className="max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl border border-white/10 bg-[#1a1410] p-4 shadow-2xl md:max-w-2xl md:rounded-3xl md:p-6"
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 bg-[#1a1410] pb-3">
          <div>
            <p className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-500">Why this issue is next</p>
            <h2 id="route-explanation-heading" className="mt-1 text-xl font-black text-stone-100">{issueLabel}</h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="min-h-11 rounded-xl border border-white/10 bg-white/5 px-4 text-xs font-black text-stone-200 focus:ring-2 focus:ring-amber-500"
          >
            Back to rating
          </button>
        </div>

        <div className="space-y-4">
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

          {readingOrders.length > 0 ? (
            <section aria-labelledby="named-routes-heading">
              <h3 id="named-routes-heading" className="text-xs font-black text-stone-200">Named reading routes</h3>
              <p className="mt-1 text-[11px] text-stone-500">Membership is informational and does not imply a hard dependency.</p>
              <ul className="mt-2 grid gap-2 md:grid-cols-2">
                {[...readingOrders].sort((a, b) => a.name.localeCompare(b.name)).map((order) => {
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
        </div>
      </section>
    </div>
  )
}
