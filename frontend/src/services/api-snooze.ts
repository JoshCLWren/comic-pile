import { defaultHttpClient, type HttpClient } from './httpClient'

/**
 * Build the snooze service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every snooze request.
 * @returns The snooze API bound to `client`.
 */
export function createSnoozeApi(client: HttpClient) {
  return {
    snooze: () => client.post<void>('/v1/snooze/'),
    unsnooze: (threadId: number) => client.post<void>(`/v1/snooze/${threadId}/unsnooze`),
  }
}

export const snoozeApi = createSnoozeApi(defaultHttpClient())
