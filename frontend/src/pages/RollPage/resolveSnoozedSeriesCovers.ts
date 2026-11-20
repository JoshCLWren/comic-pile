import type { InfiniteData, QueryClient } from '@tanstack/react-query'
import { queryKeys } from '../../query/queryKeys'
import { threadsApi } from '../../services/api-threads'
import type { ThreadListItem, ThreadListResponse } from '../../types'

/**
 * Resolve art for the compact Roll snooze shelf without N+1 requests or a
 * whole-queue waterfall. Only accept non-invalidated, recent snapshots and
 * choose the newest projection when multiple views have cached a series.
 */
export async function resolveSnoozedSeriesCovers(
  snoozedThreads: readonly { id: number }[],
  queryClient: QueryClient,
  listThreads: Pick<typeof threadsApi, 'list'> = threadsApi,
): Promise<Record<number, string | null>> {
  const wantedIds = new Set(snoozedThreads.map((thread) => thread.id))
  if (wantedIds.size === 0) return {}
  const latestById = new Map<number, { url: string | null; updatedAt: number }>()
  const now = Date.now()
  const applyThreads = (threads: ThreadListItem[], updatedAt: number) => {
    // Invalidated, expired and older projections must not override a
    // corrected mapping; one timestamp applies to each source batch.
    if (!updatedAt || now - updatedAt > 60_000) return
    for (const thread of threads) {
      if (!wantedIds.has(thread.id)) continue
      const previous = latestById.get(thread.id)
      if (previous && previous.updatedAt > updatedAt) continue
      latestById.set(thread.id, {
        url: thread.series_cover_image_url ?? null,
        updatedAt,
      })
    }
  }

  const plannerState = queryClient.getQueryState<ThreadListItem[]>(queryKeys.thread.list())
  if (plannerState?.data && !plannerState.isInvalidated) {
    applyThreads(plannerState.data, plannerState.dataUpdatedAt)
  }
  const queuePages = queryClient.getQueriesData<InfiniteData<ThreadListResponse>>({
    queryKey: queryKeys.queue.pages(),
  })
  for (const [key, pageData] of queuePages) {
    const state = queryClient.getQueryState<InfiniteData<ThreadListResponse>>(key)
    if (!state || state.isInvalidated) continue
    for (const page of pageData?.pages ?? []) {
      applyThreads(page.threads, state.dataUpdatedAt)
    }
  }
  if ([...wantedIds].some((id) => !latestById.has(id))) {
    // Fetch exactly one page to resolve remaining covers, never all pages.
    const page = await listThreads.list({ page_size: 200 })
    applyThreads(page.threads, Date.now())
  }
  return Object.fromEntries([...latestById].map(([id, value]) => [id, value.url]))
}
