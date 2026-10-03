import { defaultHttpClient, type HttpClient } from './httpClient'
import type { Thread } from '../types'

export interface MigrateThreadRequest {
  last_issue_read: number
  total_issues: number
}

/**
 * Build the migration service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every migration request.
 * @returns The migration API bound to `client`.
 */
export function createMigrationApi(client: HttpClient) {
  return {
    migrateThread: (threadId: number, data: MigrateThreadRequest) =>
      client.post<Thread, MigrateThreadRequest>(
        `/v1/threads/${threadId}:migrateToIssues`,
        data,
      ),
  }
}

export const migrationApi = createMigrationApi(defaultHttpClient())
