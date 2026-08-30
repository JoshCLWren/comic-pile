import type { ReadingOrder } from '../../services/api-reading-orders'
import type { ConnectedThreadInfo, ReaderContextResponse } from '../../types'

/**
 * True when the reader context payload itself carries issue-local continuity
 * information worth a Reading Context region: dependency/continuity edges,
 * a local chain that extends beyond the current issue, or a named series.
 */
export function hasReadingContextInformation(readerContext: ReaderContextResponse | null): boolean {
  if (!readerContext) return false
  if (readerContext.local_chain.edges.length > 0) return true
  if (readerContext.local_chain.issues.some((issue) => issue.relation !== 'current')) return true
  return readerContext.series.series_name !== null
}

/**
 * Content-driven presence test for the Reading Context region. The named
 * component is never a reason to render; only actual reading-order,
 * continuity, route, or correction content earns visual presence.
 */
export function hasReadingContextContent(
  readingOrders: ReadingOrder[],
  connectedThreads: ConnectedThreadInfo[],
  readerContext: ReaderContextResponse | null,
): boolean {
  return (
    readingOrders.length > 0 || connectedThreads.length > 0 || hasReadingContextInformation(readerContext)
  )
}