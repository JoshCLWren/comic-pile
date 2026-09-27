import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  dependencyGroupsApi,
  type DependencyGroupMemberTarget,
} from '../services/api-dependency-groups'
import { threadsApi } from '../services/api-threads'
import { issuesApi, type IssueListParams } from '../services/api-issues'
import type { Issue, ThreadListItem, ThreadListResponse } from '../types'
import { queryKeys } from '../query/queryKeys'
import { invalidateAfterCrossoverMutation } from '../query/cacheEffects'

type PositionedIssue = Issue & { position: number }

/** Crossover group service surface the Crossovers page depends on. */
export type CrossoverGroupsApi = Pick<
  typeof dependencyGroupsApi,
  'list' | 'get' | 'create' | 'rename' | 'delete' | 'addMember' | 'addIssueRange' | 'removeMember'
>

/** Thread service surface the Crossovers page depends on. */
export type CrossoverThreadsApi = Pick<typeof threadsApi, 'list'>

/** Issue service surface the Crossovers page depends on. */
export type CrossoverIssuesApi = Pick<typeof issuesApi, 'list'>

/**
 * Injectable service seams for the Crossovers page.
 *
 * Tests pass faithful in-memory implementations through the page's `api` prop
 * instead of replacing the service modules themselves, so the page exercises
 * the real query and mutation wiring against a controllable transport.
 */
export interface CrossoverApiDeps {
  groups?: CrossoverGroupsApi
  threads?: CrossoverThreadsApi
  issues?: CrossoverIssuesApi
}

async function fetchAllIssues(threadId: number, issueApi: CrossoverIssuesApi = issuesApi): Promise<PositionedIssue[]> {
  const issues: PositionedIssue[] = []
  const seenPageTokens = new Set<string>()
  let nextPageToken: string | null = null

  while (true) {
    const params: IssueListParams = { page_size: 100 }
    if (nextPageToken) {
      params.page_token = nextPageToken
    }
    const data = await issueApi.list(threadId, params)
    // SAFETY: the issues endpoint returns position-ordered issues; the integer-position check below enforces the contract.
    const pageIssues = data.issues as PositionedIssue[]
    if (pageIssues.some((issue) => !Number.isInteger(issue.position) || issue.position < 1)) {
      throw new Error('Comic issue order is unavailable for this series.')
    }
    issues.push(...pageIssues)
    if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) return issues
    seenPageTokens.add(data.next_page_token)
    nextPageToken = data.next_page_token
  }
}

async function fetchAllThreads(threadApi: CrossoverThreadsApi = threadsApi): Promise<ThreadListItem[]> {
  const threads: ThreadListItem[] = []
  const seenPageTokens = new Set<string>()
  let nextPageToken: string | null = null

  while (true) {
    const data: ThreadListResponse = await threadApi.list({ page_size: 100 }, nextPageToken)
    threads.push(...data.threads)
    if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) return threads
    seenPageTokens.add(data.next_page_token)
    nextPageToken = data.next_page_token
  }
}

export function useCrossoverGroupsList(deps: CrossoverApiDeps = {}) {
  const groups = deps.groups ?? dependencyGroupsApi
  return useQuery({
    queryKey: queryKeys.crossover.list(),
    queryFn: async () => {
      try {
        return await groups.list()
      } catch (err) {
        throw err instanceof Error ? err : new Error('Unable to load crossovers.')
      }
    },
    retry: false,
  })
}

export function useAllThreads(deps: CrossoverApiDeps = {}) {
  return useQuery({
    queryKey: queryKeys.thread.all,
    queryFn: async () => {
      try {
        return await fetchAllThreads(deps.threads ?? threadsApi)
      } catch (err) {
        throw err instanceof Error ? err : new Error('Unable to load comics for selection.')
      }
    },
    retry: false,
  })
}

export function useCrossoverIssuesForRange(threadId: number | null, deps: CrossoverApiDeps = {}) {
  const issueApi = deps.issues ?? issuesApi
  return useQuery({
    queryKey: threadId != null ? queryKeys.crossover.issues(threadId) : queryKeys.crossover.issues(-1),
    queryFn: async () => {
      try {
        return await fetchAllIssues(threadId!, issueApi)
      } catch (err) {
        throw err instanceof Error ? err : new Error('Unable to load issues for this series.')
      }
    },
    enabled: threadId != null,
    retry: false,
  })
}

export function useCreateCrossoverGroup(deps: CrossoverApiDeps = {}) {
  const client = useQueryClient()
  const groups = deps.groups ?? dependencyGroupsApi

  return useMutation({
    mutationFn: (name: string) => groups.create(name),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useRenameCrossoverGroup(deps: CrossoverApiDeps = {}) {
  const client = useQueryClient()
  const groups = deps.groups ?? dependencyGroupsApi

  return useMutation({
    mutationFn: ({ groupId, name }: { groupId: number; name: string }) =>
      groups.rename(groupId, name),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useDeleteCrossoverGroup(deps: CrossoverApiDeps = {}) {
  const client = useQueryClient()
  const groups = deps.groups ?? dependencyGroupsApi

  return useMutation({
    mutationFn: (groupId: number) => groups.delete(groupId),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useAddCrossoverMember(deps: CrossoverApiDeps = {}) {
  const client = useQueryClient()
  const groups = deps.groups ?? dependencyGroupsApi

  return useMutation({
    mutationFn: ({
      groupId,
      target,
    }: {
      groupId: number
      target: DependencyGroupMemberTarget
    }) => groups.addMember(groupId, target),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useAddCrossoverIssueRange(deps: CrossoverApiDeps = {}) {
  const client = useQueryClient()
  const groups = deps.groups ?? dependencyGroupsApi

  return useMutation({
    mutationFn: ({
      groupId,
      threadId,
      startPosition,
      endPosition,
    }: {
      groupId: number
      threadId: number
      startPosition: number
      endPosition: number
    }) => groups.addIssueRange(groupId, threadId, startPosition, endPosition),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useRemoveCrossoverMember(deps: CrossoverApiDeps = {}) {
  const client = useQueryClient()
  const groups = deps.groups ?? dependencyGroupsApi

  return useMutation({
    mutationFn: ({ groupId, memberId }: { groupId: number; memberId: number }) =>
      groups.removeMember(groupId, memberId),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}
