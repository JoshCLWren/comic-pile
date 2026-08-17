import { PillarHeader } from './PillarHeader'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'

const ACCENT = 'var(--reading-context-accent, #0891b2)'

interface ReadingContextPillarProps {
  threadId: number | null | undefined
  connectedThreads: ConnectedThreadInfo[]
  readingOrders: ReadingOrder[]
  threadTitle: string
  issueNumber: string | number | null
  onExplainRoute: () => void
  onCorrectContinuity: () => void
}

export function ReadingContextPillar({
  threadId,
  connectedThreads,
  readingOrders,
  threadTitle,
  issueNumber,
  onExplainRoute,
  onCorrectContinuity,
}: ReadingContextPillarProps) {
  return (
    <div className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.04] p-3 md:p-4">
      <PillarHeader number="02" title="Reading Context" accentColor={ACCENT} />

      {connectedThreads.length > 0 ? (
        <section aria-labelledby="connected-heading" className="rounded-xl border border-blue-800/30 bg-blue-950/15 p-3">
          <div className="flex items-center justify-between gap-2">
            <h3 id="connected-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-blue-400">
              Verified dependency connections
            </h3>
            <button
              type="button"
              onClick={onCorrectContinuity}
              className="text-[10px] font-bold text-blue-400 hover:text-blue-300 transition-colors"
            >
              Correct continuity
            </button>
          </div>
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Connected threads">
            {connectedThreads.map((connectedThread) => (
              <li
                key={`${connectedThread.thread_id}-${connectedThread.dependency_id}`}
                className="rounded-full border border-blue-800/40 bg-blue-900/20 px-2.5 py-1 text-[10px] font-bold text-blue-200"
              >
                {connectedThread.title}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <ReadingOrderGroups threadId={threadId} />

      {readingOrders.length > 0 ? (
        <section aria-labelledby="routes-heading" className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 id="routes-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Reading routes
            </h3>
            <span className="text-[10px] font-bold text-stone-600">
              {readingOrders.length} active
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-1">
            {readingOrders.map((order) => {
              const routeProgress = order.total_items > 0
                ? Math.round((order.completed_items / order.total_items) * 100)
                : 0
              return (
                <article key={order.id} className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="truncate text-xs font-black text-stone-200">{order.name}</h4>
                    <span className="shrink-0 text-[10px] font-bold text-stone-500">
                      {order.completed_items}/{order.total_items}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10" aria-hidden="true">
                    <div className="h-full rounded-full bg-amber-600" style={{ width: `${routeProgress}%` }} />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <p className="text-[10px] font-bold text-stone-500">{routeProgress}% complete</p>
                    <button
                      type="button"
                      onClick={onExplainRoute}
                      className="min-h-11 rounded-lg border border-amber-700/40 bg-amber-900/15 px-3 text-[10px] font-black text-amber-200 focus:ring-2 focus:ring-amber-500"
                      aria-label={`Explain why ${threadTitle} ${issueNumber != null ? `#${issueNumber}` : ''} is next in ${order.name}`}
                    >
                      Explain route
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      ) : null}
    </div>
  )
}
