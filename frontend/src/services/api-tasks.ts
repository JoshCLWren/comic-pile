import { defaultHttpClient, type HttpClient } from './httpClient'
import type { AnalyticsMetrics } from '../types'

/**
 * Build the analytics tasks service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every analytics request.
 * @returns The analytics tasks API bound to `client`.
 */
export function createTasksApi(client: HttpClient) {
  return {
    getMetrics: () => client.get<AnalyticsMetrics>('/v1/analytics/metrics'),
  }
}

export const tasksApi = createTasksApi(defaultHttpClient())
