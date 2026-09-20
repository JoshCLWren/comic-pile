import { useQuery, useMutation, useInfiniteQuery } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import { issuesApi } from '../services/api-issues'
import { issueDependenciesApi } from '../services/api-dependencies'
import type { IssueListParams, IssueListResponse } from '../services/api-issues'
import type { Issue, IssueDependenciesResponse } from '../types'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { invalidateAfterIssueEdit, optimisticallyUpdateIssueStatus, optimisticallyDeleteIssue, optimisticallyReorderIssues } from '../query/cacheEffects'

export const THREAD_ISSUES_PAGE_SIZE = 100

export interface ThreadIssuePagesOptions {
  /** Optional read-status filter; filtered reads own a distinct cache. */
  status?: 'read' | 'unread'
  /** When false the query stays disabled (used by collapsed sections). */
  enabled?: boolean
}

/**
 * Infinite query for paginated thread issue reads (used by IssueList).
 * Filter changes reset the query to the first page. Caller uses fetchNextPage.
 *
 * The options are decoded at the hook boundary: a status filter selects a
 * filtered cache (`['paged', { status }]`) so filtered and unfiltered reads
 * never share a page cursor, while `enabled` gates the query for collapsed
 * sections. The return value spreads the raw infinite-query result and adds
 * flattened conveniences (`issues`, `totalCount`, `pages`, `nextPageToken`)
 * matching the previous loader shape.
 */
export function useThreadIssuePages(
  threadId: number | null,
  options: ThreadIssuePagesOptions = {},
) {
  const { status, enabled = true } = options
  const pageKey =
    threadId != null && status != null
      ? [...queryKeys.thread.issuePagesPaged(threadId), { status }]
      : threadId != null
        ? queryKeys.thread.issuePages(threadId)
        : []
  const query = useInfiniteQuery<IssueListResponse>({
    queryKey: pageKey,
    queryFn: ({ pageParam }) => {
      const params: IssueListParams = { page_size: THREAD_ISSUES_PAGE_SIZE }
      if (status != null) {
        params.status = status
      }
      const pageToken = pageParam == null ? null : String(pageParam)
      if (pageToken != null) {
        params.page_token = pageToken
      }
      return issuesApi.list(threadId!, params)
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_page_token,
    enabled: threadId != null && enabled,
    retry: false,
  })

  const pages = query.data?.pages ?? []
  const lastPage = pages[pages.length - 1] ?? null
  const nextPageToken: string | null =
    query.hasNextPage && lastPage ? (lastPage.next_page_token ?? null) : null

  return {
    ...query,
    issues: flattenIssuePages(query.data),
    totalCount: getIssueTotalCount(query.data),
    pages,
    nextPageToken,
  }
}

/**
 * Flattens all loaded pages from useThreadIssuePages into a single Issue[] array.
 */
export function flattenIssuePages(
  data: InfiniteData<IssueListResponse> | undefined,
): Issue[] {
  if (!data?.pages) return []
  return data.pages.flatMap((page) => page.issues)
}

/**
 * Returns the total_count from the first page of an infinite query.
 */
export function getIssueTotalCount(
  data: InfiniteData<IssueListResponse> | undefined,
): number {
  return data?.pages?.[0]?.total_count ?? 0
}

/**
 * Query for all issues in a thread (all-pages drain, used by IssueToggleList).
 * Fetches all pages at once and returns the flattened list.
 */
export function useThreadAllIssues(threadId: number) {
  return useQuery<Issue[]>({
    queryKey: queryKeys.thread.issuePagesAll(threadId),
    queryFn: async () => {
      const allIssues: Issue[] = []
      const seenPageTokens = new Set<string>()
      let nextPageToken: string | null = null

      while (true) {
        const params: IssueListParams = { page_size: 100 }
        if (nextPageToken) {
          params.page_token = nextPageToken
        }
        const data = await issuesApi.list(threadId, params)
        allIssues.push(...data.issues)

        if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
          return allIssues
        }

        seenPageTokens.add(data.next_page_token)
        nextPageToken = data.next_page_token
      }
    },
  })
}

/**
 * Query for thread issue dependencies.
 */
export function useThreadDependencies(threadId: number) {
  return useQuery<Record<number, IssueDependenciesResponse>>({
    queryKey: queryKeys.dependencies.forThread(threadId),
    queryFn: async () => {
      const response = await issueDependenciesApi.listForThread(threadId)
      const depsMap: Record<number, IssueDependenciesResponse> = {}

      for (const issueDependencies of response.issues) {
        if (
          issueDependencies.incoming.length > 0
          || issueDependencies.outgoing.length > 0
        ) {
          depsMap[issueDependencies.issue_id] = issueDependencies
        }
      }

      return depsMap
    },
  })
}

/**
 * Mutation to toggle an issue's read/unread status.
 * Uses optimistic updates on the all-issues cache and invalidates related caches.
 */
export function useToggleIssueStatus(threadId: number) {
  return useMutation({
    mutationFn: async ({ issue, nextStatus }: { issue: Issue; nextStatus: 'read' | 'unread' }) => {
      if (nextStatus === 'read') {
        await issuesApi.markRead(issue.id)
      } else {
        await issuesApi.markUnread(issue.id)
      }
      return { issue, nextStatus }
    },
    onMutate: async ({ issue, nextStatus }) => {
      const rollback = optimisticallyUpdateIssueStatus(queryClient, threadId, issue, nextStatus)
      return { rollback }
    },
    onError: (_err, _vars, context) => {
      context?.rollback?.()
    },
    onSuccess: async () => {
      await invalidateAfterIssueEdit(queryClient, threadId)
    },
  })
}

/**
 * Mutation to create issues from a range string.
 */
export function useCreateIssues(threadId: number) {
  return useMutation({
    mutationFn: async ({
      issueRange,
      insertAfterIssueId,
    }: { issueRange: string; insertAfterIssueId?: number | null }) => {
      return issuesApi.create(threadId, issueRange, { insert_after_issue_id: insertAfterIssueId })
    },
    onSuccess: async () => {
      await invalidateAfterIssueEdit(queryClient, threadId)
    },
  })
}

/**
 * Mutation to delete an issue.
 */
export function useDeleteIssue(threadId: number) {
  return useMutation({
    mutationFn: async (issueId: number) => {
      await issuesApi.delete(issueId)
      return issueId
    },
    onMutate: async (issueId) => {
      const rollback = optimisticallyDeleteIssue(queryClient, threadId, issueId)
      return { rollback }
    },
    onError: (_err, _vars, context) => {
      context?.rollback?.()
    },
    onSuccess: async () => {
      await invalidateAfterIssueEdit(queryClient, threadId)
    },
  })
}

/**
 * Mutation to reorder issues in a thread.
 */
export function useReorderIssues(threadId: number) {
  return useMutation({
    mutationFn: async (issueIds: number[]) => {
      await issuesApi.reorder(threadId, issueIds)
      return issueIds
    },
    onMutate: async (issueIds) => {
      const rollback = optimisticallyReorderIssues(queryClient, threadId, issueIds)
      return { rollback }
    },
    onError: (_err, _vars, context) => {
      context?.rollback?.()
    },
    onSuccess: async () => {
      await invalidateAfterIssueEdit(queryClient, threadId)
    },
  })
}
