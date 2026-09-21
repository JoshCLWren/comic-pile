import { useQuery } from '@tanstack/react-query'
import { threadsApi } from '../services/api'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { issuesApi, type IssueListParams } from '../services/api-issues'
import { queryKeys } from '../query/queryKeys'
import type { Issue, Thread } from '../types'

/**
 * Fetch all threads across all pages.
 * Uses React Query for caching and automatic refetching.
 */
export function useAllThreads() {
  return useQuery({
    queryKey: queryKeys.thread.list(),
    queryFn: async (): Promise<Thread[]> => {
      const result: Thread[] = []
      const seen = new Set<string>()
      let token: string | null = null
      do {
        const page = await threadsApi.list({ page_size: 100 }, token)
        result.push(...page.threads)
        token = page.next_page_token
        if (token && seen.has(token)) break
        if (token) seen.add(token)
      } while (token)
      return result
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
      const result: Issue[] = []
      const seen = new Set<string>()
      let token: string | null = null
      do {
        const params: IssueListParams = { page_size: 100 }
        if (token) {
          params.page_token = token
        }
        const page = await issuesApi.list(selectedThreadId, params)
        result.push(...page.issues)
        token = page.next_page_token ?? null
        if (token && seen.has(token)) break
        if (token) seen.add(token)
      } while (token)
      return result
    },
    enabled: selectedThreadId != null,
  })
}
