import { createNativeV2Client } from '../generated/nativeV2Client'
import { defaultHttpClient, type HttpClient } from './httpClient'

/**
 * Build the analytics tasks service bound to an HTTP client.
 *
 * The generated native v2 client owns the v2 analytics URL and transport
 * contract; this adapter keeps the existing `getMetrics` caller shape.
 *
 * @param client - HTTP transport used for every analytics request.
 * @returns The analytics tasks API bound to `client`.
 */
export function createTasksApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)
  return {
    getMetrics: () => nativeV2.metrics(),
  }
}

export const tasksApi = createTasksApi(defaultHttpClient())
