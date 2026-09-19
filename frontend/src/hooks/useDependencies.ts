import { useQuery, useMutation } from '@tanstack/react-query';
import { dependenciesApi, threadsApi, migrationApi } from '../services/api';
import { issuesApi, type IssueListParams } from '../services/api-issues';
import type { Dependency, Issue, Thread, ThreadDependenciesResponse, ThreadListResponse } from '../types';
import { queryClient } from '../query/queryClient';
import { queryKeys } from '../query/queryKeys';
import { invalidateAfterDependencyChange, applyMigratedThreadCache } from '../query/cacheEffects';

async function fetchAllUnreadIssues(threadId: number): Promise<Issue[]> {
  const allIssues: Issue[] = [];
  const seenPageTokens = new Set<string>();
  let nextPageToken: string | null = null;

  while (true) {
    const params: IssueListParams = {
      status: 'unread',
      page_size: 100,
    };
    if (nextPageToken) {
      params.page_token = nextPageToken;
    }
    const data = await issuesApi.list(threadId, params);
    allIssues.push(...data.issues);

    if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
      return allIssues;
    }

    seenPageTokens.add(data.next_page_token);
    nextPageToken = data.next_page_token;
  }
}

export function useThreadDependencies(threadId: number | null | undefined) {
  return useQuery<ThreadDependenciesResponse>({
    queryKey: threadId != null ? queryKeys.dependencies.forThread(threadId) : [],
    queryFn: () => dependenciesApi.listThreadDependencies(threadId!),
    enabled: threadId != null,
    retry: false,
  });
}

export function useBlockedThreadIds() {
  return useQuery<number[]>({
    queryKey: queryKeys.dependencies.list(),
    queryFn: () => dependenciesApi.listBlockedThreadIds(),
    retry: false,
  });
}

export function useSearchThreads(query: string) {
  const normalizedQuery = query.trim();
  return useQuery<ThreadListResponse>({
    queryKey: normalizedQuery.length >= 2
      ? queryKeys.dependencies.search(normalizedQuery)
      : [],
    queryFn: () => threadsApi.list({ search: normalizedQuery }),
    enabled: normalizedQuery.length >= 2,
    retry: false,
  });
}

export function useThreadIssuesForDependency(threadId: number | null | undefined) {
  return useQuery<Issue[]>({
    queryKey: threadId != null ? queryKeys.dependencies.issues(threadId) : [],
    queryFn: () => fetchAllUnreadIssues(threadId!),
    enabled: threadId != null,
    retry: false,
  });
}

export function useCreateDependency(threadId: number | undefined) {
  return useMutation({
    mutationFn: (payload: {
      sourceType: 'thread' | 'issue';
      sourceId: number;
      targetType: 'thread' | 'issue';
      targetId: number;
    }) => dependenciesApi.createDependency(payload),
    onSuccess: async () => {
      if (threadId != null) {
        await invalidateAfterDependencyChange(queryClient, threadId);
      }
    },
  });
}

export function useDeleteDependency(threadId: number | undefined) {
  return useMutation({
    mutationFn: (dependencyId: number) => dependenciesApi.deleteDependency(dependencyId),
    onSuccess: async () => {
      if (threadId != null) {
        await invalidateAfterDependencyChange(queryClient, threadId);
      }
    },
  });
}

export function useUpdateDependency(threadId: number | undefined) {
  return useMutation({
    mutationFn: ({ dependencyId, note }: { dependencyId: number; note: string | null }) =>
      dependenciesApi.updateDependency(dependencyId, note),
    onSuccess: async () => {
      if (threadId != null) {
        await invalidateAfterDependencyChange(queryClient, threadId);
      }
    },
  });
}

export function useMigrateThread() {
  return useMutation({
    mutationFn: ({ threadId, lastIssueRead, totalIssues }: { threadId: number; lastIssueRead: number; totalIssues: number }) =>
      migrationApi.migrateThread(threadId, { last_issue_read: lastIssueRead, total_issues: totalIssues }),
    onSuccess: async (updatedThread) => {
      await applyMigratedThreadCache(queryClient, updatedThread);
    },
  });
}
