import api from './api'
import type { HttpClient } from './httpClient'
import type {
  ReactivateThreadPayload,
  RollResponse,
  SetCurrentIssueResponse,
  Thread,
  ThreadCreatePayload,
  ThreadListResponse,
  ThreadQueryParams,
  ThreadUpdatePayload,
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
      const response = await client.get<ThreadListResponse>('/v1/threads/', {
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
    get: (id: number) => client.get<Thread>(`/v1/threads/${id}`),
    create: (data: ThreadCreatePayload) => client.post<Thread, ThreadCreatePayload>('/v1/threads/', data),
    update: (id: number, data: ThreadUpdatePayload) =>
      client.put<Thread, ThreadUpdatePayload>(`/v1/threads/${id}`, data),
    delete: (id: number) => client.delete<void>(`/v1/threads/${id}`),
    reactivate: (data: ReactivateThreadPayload) =>
      client.post<Thread, ReactivateThreadPayload>('/v1/threads/reactivate', data),
    listStale: (days = 30) => client.get<Thread[]>('/v1/threads/stale', { params: { days } }),
    setPending: (id: number) => client.post<RollResponse>(`/v1/threads/${id}/set-pending`),
    setCurrentIssue: (id: number, issueNumber: string) =>
      client.post<SetCurrentIssueResponse, { issue_number: string }>(`/v1/threads/${id}:setCurrentIssue`, { issue_number: issueNumber }),
  }
}

export const threadsApi = createThreadsApi(api)
