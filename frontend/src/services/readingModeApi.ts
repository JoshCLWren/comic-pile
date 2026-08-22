import api from './api'
import type { SessionModeResponse, SessionModeUpdateRequest } from '../types/readingMode'

/** Canonical session-mode API client used by the reading quiz. */
export const readingModeApi = {
  get: (sessionId: number) =>
    api.get<SessionModeResponse>(`/v1/sessions/${sessionId}/mode`),
  set: (sessionId: number, request: SessionModeUpdateRequest) =>
    api.post<SessionModeResponse>(`/v1/sessions/${sessionId}/mode`, request),
}
