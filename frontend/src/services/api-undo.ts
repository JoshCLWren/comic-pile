import api from './api'
import type { SessionSnapshotsResponse } from '../types'

export const undoApi = {
  undo: (sessionId: number | string, snapshotId: number | string) =>
    api.post<void>(`/v1/undo/${sessionId}/undo/${snapshotId}`),
  listSnapshots: (sessionId: number | string) => api.get<SessionSnapshotsResponse>(`/v1/undo/${sessionId}/snapshots`),
}
