import { defaultHttpClient, type HttpClient } from './httpClient'
import type { Thread } from '../types'

/**
 * Build the migration service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every migration request.
 * @returns The migration API bound to `client`.
 */
export function createMigrationApi(client: HttpClient) {
  return {
    migrateThread: (threadId: number, data: { last_issue_read: number; total_issues: number }) =>
      client.post<Thread, { last_issue_read: number; total_issues: number }>(`/v1/threads/${threadId}:migrateToIssues`, data),
  }
}

export const migrationApi = createMigrationApi(defaultHttpClient())