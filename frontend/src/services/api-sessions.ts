import api from './api'
import type {
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionModeResponse,
  SessionModeUpdateRequest,
  SessionSnapshotsResponse,
  SessionSummary,
} from '../types'

export type SessionListParams = Record<string, string | number | boolean | null>

export const sessionApi = {
  list: async (params?: SessionListParams, pageToken?: string | null): Promise<SessionListResponse> => {
    const queryParams = { ...(params ?? {}) } satisfies SessionListParams;
    if (pageToken) {
      queryParams.page_token = pageToken;
    }
    const response = await api.get<SessionListResponse>('/v1/sessions/', {
      params: Object.keys(queryParams).length ? queryParams : undefined,
    })
    return response
  },
  get: (id: number) => api.get<SessionSummary>(`/v1/sessions/${id}`),
  getCurrent: () => api.get<SessionCurrent>('/v1/sessions/current/'),
  getDetails: (id: number | string) => api.get<SessionDetails>(`/v1/sessions/${id}/details`),
  getSnapshots: (id: number | string) => api.get<SessionSnapshotsResponse>(`/v1/sessions/${id}/snapshots`),
  restoreSessionStart: (id: number | string) => api.post<void>(`/v1/sessions/${id}/restore-session-start`),
  updateMode: (data: SessionModeUpdateRequest) =>
    api.patch<SessionModeResponse, SessionModeUpdateRequest>('/v1/roll/session-mode', data),
}
