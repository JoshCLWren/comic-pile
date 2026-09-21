import api from './api'
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

export const threadsApi = {
  list: async (params?: ThreadQueryParams, pageToken?: string | null): Promise<ThreadListResponse> => {
    const queryParams = { ...(params ?? {}) } satisfies ThreadQueryParams;
    if (pageToken) {
      queryParams.page_token = pageToken;
    }
    const response = await api.get<ThreadListResponse>('/v1/threads/', {
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

    const response = await api.get<ThreadListResponse>('/v1/threads/completed/threads', {
      params: Object.keys(queryParams).length ? queryParams : undefined,
    })
    return response
  },
  get: (id: number) => api.get<Thread>(`/v1/threads/${id}`),
  create: (data: ThreadCreatePayload) => api.post<Thread, ThreadCreatePayload>('/v1/threads/', data),
  update: (id: number, data: ThreadUpdatePayload) =>
    api.put<Thread, ThreadUpdatePayload>(`/v1/threads/${id}`, data),
  delete: (id: number) => api.delete<void>(`/v1/threads/${id}`),
  reactivate: (data: ReactivateThreadPayload) =>
    api.post<Thread, ReactivateThreadPayload>('/v1/threads/reactivate', data),
  listStale: (days = 30) => api.get<Thread[]>('/v1/threads/stale', { params: { days } }),
  setPending: (id: number) => api.post<RollResponse>(`/v1/threads/${id}/set-pending`),
  setCurrentIssue: (id: number, issueNumber: string) =>
    api.post<SetCurrentIssueResponse, { issue_number: string }>(`/v1/threads/${id}:setCurrentIssue`, { issue_number: issueNumber }),
}
