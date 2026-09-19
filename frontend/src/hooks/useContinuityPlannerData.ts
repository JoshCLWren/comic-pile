import { useQuery } from '@tanstack/react-query'
import { threadsApi } from '../services/api'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { queryKeys } from '../query/queryKeys'
import type { Thread } from '../types'
import type { DependencyGroup } from '../services/api-dependency-groups'

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
