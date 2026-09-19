import { useInfiniteCollection } from '../pagination'
import type { InfiniteCollectionState } from '../pagination'
import { issuesApi, type IssueListParams } from '../services/api-issues'
import { queryKeys } from '../query/queryKeys'
import type { Issue, IssueListResponse } from '../types'

/** Bounded page size for thread issue listings (matches the Queue page size). */
export const THREAD_ISSUES_PAGE_SIZE = 100

export interface ThreadIssuePagesState
  extends Omit<InfiniteCollectionState<Issue, IssueListResponse>, 'items'> {
  /** All loaded issues across every page, in server order. */
  issues: Issue[]
  /** Server-reported total issue count for the thread, or `0` before load. */
  totalCount: number
}

/**
 * Canonical paginated thread-issue loader for the thread detail view.
 *
 * Uses the stable `queryKeys.thread.issuePages(threadId)` key (cursor excluded)
 * so retries, edits, and read-status toggles stay consistent with the rest of
 * the app. Disabled until the caller requests data (e.g. when the Issues
 * section expands) and never retries, matching the previous hand-rolled fetch.
 */
export function useThreadIssuePages(
  threadId: number | null,
  enabled = true,
): ThreadIssuePagesState {
  const query = useInfiniteCollection<Issue, IssueListResponse>({
    queryKey: threadId != null ? queryKeys.thread.issuePages(threadId) : [],
    queryFn: ({ pageParam }) => {
      const params: IssueListParams = { page_size: THREAD_ISSUES_PAGE_SIZE }
      if (pageParam) {
        params.page_token = pageParam
      }
      return issuesApi.list(threadId!, params)
    },
    // SAFETY: null is the intentional first-page cursor for the issues paginator.
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_page_token,
    selectPage: (page) => page.issues,
    enabled: threadId != null && enabled,
    retry: false,
  })

  const totalCount = query.pages[0]?.total_count ?? 0

  return {
    issues: query.items,
    pages: query.pages,
    totalCount,
    isInitialLoading: query.isInitialLoading,
    isNextPageLoading: query.isNextPageLoading,
    isLoading: query.isLoading,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error,
    hasNextPage: query.hasNextPage,
    nextPageToken: query.nextPageToken,
    fetchNextPage: query.fetchNextPage,
    refetch: query.refetch,
  }
}
