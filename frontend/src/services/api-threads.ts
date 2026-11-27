import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  BulkQueueExclusionRequest,
  BulkQueueExclusionResponse,
  BulkQueueRestoreResponse,
  CheckPotentialDuplicatesRequest,
  CheckPotentialDuplicatesResponse,
  ReactivateThreadPayload,
  SetCurrentIssueResponse,
  Thread,
  ThreadCreatePayload,
  ThreadListResponse,
  ThreadPatchPayload,
  ThreadQueryParams,
} from '../types'

/**
 * Build the thread service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every thread request.
 * @returns The thread API bound to `client`.
 */
export function createThreadsApi(client: HttpClient) {
  return {
    list: async (params?: ThreadQueryParams, pageToken?: string | null): Promise<ThreadListResponse> => {
      const queryParams = { ...(params ?? {}) } satisfies ThreadQueryParams;
      if (pageToken) {
        queryParams.page_token = pageToken;
      }
      const response = await client.get<ThreadListResponse>('/v2/threads', {
        params: Object.keys(queryParams).length ? queryParams : undefined,
      })
      return response
    },
    listCompleted: async (search?: string, sort?: string, pageToken?: string | null, pageSize?: number): Promise<ThreadListResponse> => {
      const queryParams: Record<string, string | number> = {};
      if (search) queryParams.search = search;
      if (sort) queryParams.sort = sort;
      if (pageSize) queryParams.page_size = pageSize;
      if (pageToken) queryParams.page_token = pageToken;

      const response = await client.get<ThreadListResponse>('/v1/threads/completed/threads', {
        params: Object.keys(queryParams).length ? queryParams : undefined,
      })
      return response
    },
    listExcluded: async (search?: string, sort?: string, pageToken?: string | null, pageSize?: number): Promise<ThreadListResponse> => {
      const queryParams: Record<string, string | number> = {};
      if (search) queryParams.search = search;
      if (sort) queryParams.sort = sort;
      if (pageSize) queryParams.page_size = pageSize;
      if (pageToken) queryParams.page_token = pageToken;

      const response = await client.get<ThreadListResponse>('/v1/threads/excluded/threads', {
        params: Object.keys(queryParams).length ? queryParams : undefined,
      })
      return response
    },
    get: (id: number) => client.get<Thread>(`/v1/threads/${id}`),
    create: (data: ThreadCreatePayload) => client.post<Thread, ThreadCreatePayload>('/v2/threads', data),
    /**
     * AIP-134 partial update on the canonical v2 Thread resource. The field mask
     * is derived from the keys the caller actually supplied, so an omitted field
     * can never be cleared by a stale client snapshot (issue #5703).
     */
    update: async (id: number, data: ThreadPatchPayload): Promise<Thread> => {
      const { expected, update_mask: suppliedMask, ...fields } = data
      const mask =
        suppliedMask ??
        Object.entries(fields)
          .filter(([, value]) => value !== undefined)
          .map(([key]) => key)
      const body: ThreadPatchPayload = { ...fields }
      if (mask.length) {
        body.update_mask = mask
      }
      if (expected) {
        body.expected = expected
      }
      return client.patch<Thread, ThreadPatchPayload>(`/v2/threads/${id}`, body)
    },
    delete: (id: number) => client.delete<void>(`/v2/threads/${id}`),
    exclude: (id: number) => client.post<Thread>(`/v1/threads/${id}/exclude`),
    restore: (id: number) => client.post<Thread>(`/v1/threads/${id}/restore`),
    bulkExclude: (data: BulkQueueExclusionRequest) =>
      client.post<BulkQueueExclusionResponse>('/v2/queue-exclusions', data),
    bulkRestore: (threadIds: number[]) =>
      client.post<BulkQueueRestoreResponse>('/v2/queue-exclusions/restore', { thread_ids: threadIds }),
    checkExcludedStatus: async (threadIds: number[]) => {
      const chunkSize = 1000
      const chunks: number[][] = []
      for (let index = 0; index < threadIds.length; index += chunkSize) {
        chunks.push(threadIds.slice(index, index + chunkSize))
      }
      const results = await Promise.all(
        chunks.map((chunk) =>
          client.post<{ excluded_thread_ids: number[]; active_thread_ids?: number[] }>(
            '/v2/queue-exclusions/status:check',
            { thread_ids: chunk },
          ),
        ),
      )
      const excluded = new Set<number>()
      const active = new Set<number>()
      for (const result of results) {
        for (const id of result.excluded_thread_ids ?? []) excluded.add(id)
        for (const id of result.active_thread_ids ?? []) active.add(id)
      }
      return {
        excluded_thread_ids: Array.from(excluded),
        active_thread_ids: Array.from(active),
      }
    },
    restoreExclusionGroup: (groupId: number) =>
      client.post<BulkQueueRestoreResponse>(`/v2/queue-exclusion-groups/${groupId}/restore`),
    reactivate: (data: ReactivateThreadPayload) =>
      client.post<Thread, ReactivateThreadPayload>('/v1/threads/reactivate', data),
    listStale: (days = 30) => client.get<Thread[]>('/v1/threads/stale', { params: { days } }),
    setCurrentIssue: (id: number, issueNumber: string) =>
      client.post<SetCurrentIssueResponse, { issue_number: string }>(`/v1/threads/${id}:setCurrentIssue`, { issue_number: issueNumber }),
    /**
     * Advisory existing-volume lookup for an Add Series or Edit/Rename
     * candidate (#3612, #5705). Read-only: it never creates, merges, or
     * renames. The canonical v2 surface is a scoped AIP-136 collection custom
     * method, so it never competes with `GET /v2/threads`'s filter/search.
     */
    checkPotentialDuplicates: (data: CheckPotentialDuplicatesRequest) =>
      client.post<CheckPotentialDuplicatesResponse, CheckPotentialDuplicatesRequest>(
        '/v2/threads:checkDuplicates',
        data,
      ),
  }
}

export const threadsApi = createThreadsApi(defaultHttpClient())
