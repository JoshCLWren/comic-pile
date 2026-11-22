import { defaultHttpClient, type HttpClient } from './httpClient'
import type { SessionSnapshotsResponse } from '../types'

/**
 * Build the undo service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every undo request.
 * @returns The undo API bound to `client`.
 */
export function createUndoApi(client: HttpClient) {
  return {
    undo: (sessionId: number | string, snapshotId: number | string) =>
      client.post<void>(`/v2/undo/${sessionId}/snapshots/${snapshotId}/restore`),
    listSnapshots: (sessionId: number | string) => client.get<SessionSnapshotsResponse>(`/v2/undo/${sessionId}/snapshots`),
  }
}

export const undoApi = createUndoApi(defaultHttpClient())
