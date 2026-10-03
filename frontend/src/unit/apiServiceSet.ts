import type { HttpClient } from '../services/httpClient'
import { createAuthApi } from '../services/api-auth'
import { createBugReportsApi } from '../services/api-bug-reports'
import { createMigrationApi } from '../services/api-migration'
import { createPreferencesApi } from '../services/api-preferences'
import { createTasksApi } from '../services/api-tasks'
import { createCreatorsApi } from '../services/api-creators'
import { createDependenciesApi } from '../services/api-dependencies'
import { createQueueApi } from '../services/api-queue'
import { createRateApi } from '../services/api-rate'
import { createRollApi } from '../services/api-roll'
import { createSessionApi } from '../services/api-sessions'
import { createSnoozeApi } from '../services/api-snooze'
import { createThreadsApi } from '../services/api-threads'
import { createUndoApi } from '../services/api-undo'

/**
 * Assemble every service the API-routing test exercises against one transport.
 *
 * @param client - The HTTP transport the services must use.
 * @returns The service set bound to `client`.
 */
export function createApiServiceSet(client: HttpClient) {
  return {
    authApi: createAuthApi(client),
    bugReportsApi: createBugReportsApi(client),
    creatorsApi: createCreatorsApi(client),
    dependenciesApi: createDependenciesApi(client),
    migrationApi: createMigrationApi(client),
    preferencesApi: createPreferencesApi(client),
    queueApi: createQueueApi(client),
    rateApi: createRateApi(client),
    rollApi: createRollApi(client),
    sessionApi: createSessionApi(client),
    snoozeApi: createSnoozeApi(client),
    tasksApi: createTasksApi(client),
    threadsApi: createThreadsApi(client),
    undoApi: createUndoApi(client),
  }
}
