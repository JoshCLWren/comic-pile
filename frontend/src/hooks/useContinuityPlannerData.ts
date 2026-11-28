import { useQuery } from '@tanstack/react-query'
import { threadsApi } from '../services/api-threads'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { issuesApi, type IssueListParams } from '../services/api-issues'
import { queryKeys } from '../query/queryKeys'
import {
  COLLECT_ALL_DEFAULT_MAX_PAGES,
  MAX_ISSUE_COLLECTION_PAGES,
  collectAllPages,
} from '../pagination/collectAllPages'
import type { Issue, ThreadListItem } from '../types'

/**
 * Fetch all threads across all pages.
 * Uses React Query for caching and automatic refetching.
 *
 * The paginated thread endpoints return the queue-optimized list item, which is
 * deliberately narrower than the thread detail response (no `last_rating`,
 * `is_test`, or `reading_progress`). The result is typed accordingly.
 */
export function useAllThreads() {
  return useQuery({
    queryKey: queryKeys.thread.list(),
    queryFn: async (): Promise<ThreadListItem[]> => {
      const firstPage = await threadsApi.list({ page_size: 100 }, null)
      const total = firstPage.filtered_count ?? firstPage.active_count
      const maxPages = Math.max(
        COLLECT_ALL_DEFAULT_MAX_PAGES,
        Math.ceil((total ?? 0) / 100),
      )
      const collected = await collectAllPages({
        fetchPage: (token) => token === null
          ? firstPage
          : threadsApi.list({ page_size: 100 }, token),
        selectItems: (page) => page.threads,
        selectNextToken: (page) => page.next_page_token || null,
        maxPages,
      })
      if (collected.stopReason === 'max-pages') {
        throw new Error('Unable to load the complete comics list for selection.')
      }
      return collected.items
    },
  })
}

/**
 * Fetch all dependency groups.
 * Uses React Query for caching and automatic refetching.
 */
export function useAllDependencyGroups() {
  return useQuery({
    queryKey: queryKeys.dependencies.list(),
    queryFn: dependencyGroupsApi.list,
  })
}

/**
 * Fetch a single continuity plan by ID.
 * Uses React Query for caching and automatic refetching.
 */
export function useContinuityPlan(planId: number | null) {
  return useQuery({
    queryKey: planId ? queryKeys.readingPlans.detail(planId) : [],
    queryFn: () => continuityPlansApi.get(planId!),
    enabled: planId != null,
  })
}

/**
 * Fetch every issue of the selected thread across all pages.
 * Uses React Query keyed by thread so switching threads re-fetches cleanly.
 */
export function useThreadIssues(selectedThreadId: number | null) {
  return useQuery({
    queryKey:
      selectedThreadId != null
        ? queryKeys.thread.issuePage(selectedThreadId, { pageSize: 100, status: undefined })
        : [],
    queryFn: async (): Promise<Issue[]> => {
      if (selectedThreadId === null) return []
      const collected = await collectAllPages({
        fetchPage: (token) => {
          const params: IssueListParams = { page_size: 100 }
          if (token) {
            params.page_token = token
          }
          return issuesApi.list(selectedThreadId, params)
        },
        selectItems: (page) => page.issues,
        selectNextToken: (page) => page.next_page_token || null,
        maxPages: MAX_ISSUE_COLLECTION_PAGES,
      })
      if (collected.stopReason === 'max-pages') {
        throw new Error('Unable to load the complete issue list for this series.')
      }
      return collected.items
    },
    enabled: selectedThreadId != null,
  })
}
