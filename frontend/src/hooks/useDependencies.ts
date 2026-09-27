import { useQuery, useMutation } from '@tanstack/react-query';
import { threadsApi } from '../services/api-threads';
import { dependenciesApi, migrationApi } from '../services/api';
import { issuesApi, type IssueListParams } from '../services/api-issues';
import type { Dependency, Issue, Thread, ThreadDependenciesResponse, ThreadListResponse } from '../types';
import { queryClient } from '../query/queryClient';
import { queryKeys } from '../query/queryKeys';
import { invalidateAfterDependencyChange, applyMigratedThreadCache } from '../query/cacheEffects';

/** Dependency service surface the DependencyBuilder depends on. */
export type DependencyListApi = Pick<
  typeof dependenciesApi,
  'listThreadDependencies' | 'listBlockedThreadIds' | 'createDependency' | 'deleteDependency' | 'updateDependency'
>;

/** Thread service surface the DependencyBuilder depends on. */
export type DependencyThreadsApi = Pick<typeof threadsApi, 'list'>;

/** Issue service surface the DependencyBuilder depends on. */
export type DependencyIssuesApi = Pick<typeof issuesApi, 'list'>;

/** Migration service surface the DependencyBuilder depends on. */
export type DependencyMigrationApi = Pick<typeof migrationApi, 'migrateThread'>;

/**
 * Injectable service seams for the DependencyBuilder.
 *
 * Tests pass faithful in-memory implementations through the component's `api`
 * prop instead of replacing the service modules themselves, so the component
 * exercises its real query and mutation wiring against a controllable transport.
 */
export interface DependencyBuilderApiDeps {
  dependencies?: DependencyListApi;
  threads?: DependencyThreadsApi;
  issues?: DependencyIssuesApi;
  migration?: DependencyMigrationApi;
}

async function fetchAllUnreadIssues(threadId: number, issues: DependencyIssuesApi = issuesApi): Promise<Issue[]> {
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
    const data = await issues.list(threadId, params);
    allIssues.push(...data.issues);

    if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
      return allIssues;
    }

    seenPageTokens.add(data.next_page_token);
    nextPageToken = data.next_page_token;
  }
}

export function useThreadDependencies(
  threadId: number | null | undefined,
  enabled = true,
  api: DependencyListApi = dependenciesApi
) {
  return useQuery<ThreadDependenciesResponse>({
    queryKey: threadId != null ? queryKeys.dependencies.forThread(threadId) : [],
    queryFn: () => api.listThreadDependencies(threadId!),
    enabled: enabled && threadId != null,
    retry: false,
  });
}

export function useBlockedThreadIds(enabled = true, api: DependencyListApi = dependenciesApi) {
  return useQuery<number[]>({
    queryKey: queryKeys.dependencies.list(),
    queryFn: () => api.listBlockedThreadIds(),
    enabled,
    retry: false,
  });
}

export function useSearchThreads(
  query: string,
  enabled = true,
  api: DependencyThreadsApi = threadsApi
) {
  const normalizedQuery = query.trim();
  return useQuery<ThreadListResponse>({
    queryKey: normalizedQuery.length >= 2
      ? queryKeys.dependencies.search(normalizedQuery)
      : [],
    queryFn: () => api.list({ search: normalizedQuery }),
    enabled: enabled && normalizedQuery.length >= 2,
    retry: false,
  });
}

export function useThreadIssuesForDependency(
  threadId: number | null | undefined,
  enabled = true,
  api: DependencyIssuesApi = issuesApi
) {
  return useQuery<Issue[]>({
    queryKey: threadId != null ? queryKeys.dependencies.issues(threadId) : [],
    queryFn: () => fetchAllUnreadIssues(threadId!, api),
    enabled: enabled && threadId != null,
    retry: false,
  });
}

export function useCreateDependency(
  threadId: number | undefined,
  api: DependencyListApi = dependenciesApi
) {
  return useMutation({
    mutationFn: (payload: {
      sourceType: 'thread' | 'issue';
      sourceId: number;
      targetType: 'thread' | 'issue';
      targetId: number;
    }) => api.createDependency(payload),
    onSuccess: async () => {
      if (threadId != null) {
        await invalidateAfterDependencyChange(queryClient, threadId);
      }
    },
  });
}

export function useDeleteDependency(
  threadId: number | undefined,
  api: DependencyListApi = dependenciesApi
) {
  return useMutation({
    mutationFn: (dependencyId: number) => api.deleteDependency(dependencyId),
    onSuccess: async () => {
      if (threadId != null) {
        await invalidateAfterDependencyChange(queryClient, threadId);
      }
    },
  });
}

export function useUpdateDependency(
  threadId: number | undefined,
  api: DependencyListApi = dependenciesApi
) {
  return useMutation({
    mutationFn: ({ dependencyId, note }: { dependencyId: number; note: string | null }) =>
      api.updateDependency(dependencyId, note),
    onSuccess: async () => {
      if (threadId != null) {
        await invalidateAfterDependencyChange(queryClient, threadId);
      }
    },
  });
}

export function useMigrateThread(api?: DependencyMigrationApi) {
  return useMutation({
    mutationFn: ({ threadId, lastIssueRead, totalIssues }: { threadId: number; lastIssueRead: number; totalIssues: number }) =>
      (api ?? migrationApi).migrateThread(threadId, { last_issue_read: lastIssueRead, total_issues: totalIssues }),
    onSuccess: async (updatedThread) => {
      await applyMigratedThreadCache(queryClient, updatedThread);
    },
  });
}
