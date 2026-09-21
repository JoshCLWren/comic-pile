import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  dependencyGroupsApi,
  type DependencyGroupMemberTarget,
} from '../services/api-dependency-groups'
import { threadsApi } from '../services/api-threads'
import { issuesApi, type IssueListParams } from '../services/api-issues'
import type { Issue, Thread, ThreadListResponse } from '../types'
import { queryKeys } from '../query/queryKeys'
import { invalidateAfterCrossoverMutation } from '../query/cacheEffects'

type PositionedIssue = Issue & { position: number }

async function fetchAllIssues(threadId: number): Promise<PositionedIssue[]> {
  const issues: PositionedIssue[] = []
  const seenPageTokens = new Set<string>()
  let nextPageToken: string | null = null

  while (true) {
    const params: IssueListParams = { page_size: 100 }
    if (nextPageToken) {
      params.page_token = nextPageToken
    }
    const data = await issuesApi.list(threadId, params)
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

async function fetchAllThreads(): Promise<Thread[]> {
  const threads: Thread[] = []
  const seenPageTokens = new Set<string>()
  let nextPageToken: string | null = null

  while (true) {
    const data: ThreadListResponse = await threadsApi.list({ page_size: 100 }, nextPageToken)
    threads.push(...data.threads)
    if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) return threads
    seenPageTokens.add(data.next_page_token)
    nextPageToken = data.next_page_token
  }
}

export function useCrossoverGroupsList() {
  return useQuery({
    queryKey: queryKeys.crossover.list(),
    queryFn: async () => {
      try {
        return await dependencyGroupsApi.list()
      } catch (err) {
        throw err instanceof Error ? err : new Error('Unable to load crossovers.')
      }
    },
    retry: false,
  })
}

export function useAllThreads() {
  return useQuery({
    queryKey: queryKeys.thread.all,
    queryFn: async () => {
      try {
        return await fetchAllThreads()
      } catch (err) {
        throw err instanceof Error ? err : new Error('Unable to load comics for selection.')
      }
    },
    retry: false,
  })
}

export function useCrossoverIssuesForRange(threadId: number | null) {
  return useQuery({
    queryKey: threadId != null ? queryKeys.crossover.issues(threadId) : queryKeys.crossover.issues(-1),
    queryFn: async () => {
      try {
        return await fetchAllIssues(threadId!)
      } catch (err) {
        throw err instanceof Error ? err : new Error('Unable to load issues for this series.')
      }
    },
    enabled: threadId != null,
    retry: false,
  })
}

export function useCreateCrossoverGroup() {
  const client = useQueryClient()

  return useMutation({
    mutationFn: (name: string) => dependencyGroupsApi.create(name),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useRenameCrossoverGroup() {
  const client = useQueryClient()

  return useMutation({
    mutationFn: ({ groupId, name }: { groupId: number; name: string }) =>
      dependencyGroupsApi.rename(groupId, name),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useDeleteCrossoverGroup() {
  const client = useQueryClient()

  return useMutation({
    mutationFn: (groupId: number) => dependencyGroupsApi.delete(groupId),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useAddCrossoverMember() {
  const client = useQueryClient()

  return useMutation({
    mutationFn: ({
      groupId,
      target,
    }: {
      groupId: number
      target: DependencyGroupMemberTarget
    }) => dependencyGroupsApi.addMember(groupId, target),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useAddCrossoverIssueRange() {
  const client = useQueryClient()

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
    }) => dependencyGroupsApi.addIssueRange(groupId, threadId, startPosition, endPosition),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}

export function useRemoveCrossoverMember() {
  const client = useQueryClient()

  return useMutation({
    mutationFn: ({ groupId, memberId }: { groupId: number; memberId: number }) =>
      dependencyGroupsApi.removeMember(groupId, memberId),
    onSuccess: async () => {
      await invalidateAfterCrossoverMutation(client)
    },
  })
}
