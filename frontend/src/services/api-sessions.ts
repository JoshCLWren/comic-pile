import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  CorrectionSheetExamplesResponse,
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionModeResponse,
  SessionModeUpdateRequest,
  SessionSnapshotsResponse,
  SessionSummary,
} from '../types'

export type SessionListParams = Record<string, string | number | boolean | null>

/**
 * Build the session service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The session service bound to `client`.
 */
export function createSessionApi(client: HttpClient) {
  return {
  list: async (params?: SessionListParams, pageToken?: string | null): Promise<SessionListResponse> => {
    const queryParams = { ...(params ?? {}) } satisfies SessionListParams;
    if (pageToken) {
      queryParams.page_token = pageToken;
    }
    const response = await client.get<SessionListResponse>('/v1/sessions/', {
      params: Object.keys(queryParams).length ? queryParams : undefined,
    })
    return response
  },
  get: (id: number) => client.get<SessionSummary>(`/v1/sessions/${id}`),
  getCurrent: () => client.get<SessionCurrent>('/v1/sessions/current/'),
  getDetails: (id: number | string) => client.get<SessionDetails>(`/v1/sessions/${id}/details`),
  getSnapshots: (id: number | string) => client.get<SessionSnapshotsResponse>(`/v1/sessions/${id}/snapshots`),
  restoreSessionStart: (id: number | string) => client.post<void>(`/v1/sessions/${id}/restore-session-start`),
  updateMode: (data: SessionModeUpdateRequest) =>
    client.patch<SessionModeResponse, SessionModeUpdateRequest>('/v1/roll/session-mode', data),
  getCorrectionExamples: () => client.get<CorrectionSheetExamplesResponse>('/v1/sessions/correction-examples'),
}
}

export const sessionApi = createSessionApi(defaultHttpClient())
