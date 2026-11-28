import { defaultHttpClient, type HttpClient } from './httpClient'
import { migrateThreadToIssues } from './api-issues'
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
    /**
     * Compose the retired one-shot migration from scoped v2 issue resources.
     * The request shape and returned Thread contract stay unchanged for the
     * migration dialog, dependency builder and Roll flows (issue #5707).
     */
    migrateThread: (threadId: number, data: MigrateThreadRequest): Promise<Thread> =>
      migrateThreadToIssues(client, threadId, data.last_issue_read, data.total_issues),
  }
}

export const migrationApi = createMigrationApi(defaultHttpClient())
