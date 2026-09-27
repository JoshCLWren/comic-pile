import { defaultHttpClient, type HttpClient } from './httpClient'

/**
 * Build the queue service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every queue request.
 * @returns The queue API bound to `client`.
 */
export function createQueueApi(client: HttpClient) {
  return {
    moveToPosition: (id: number, position: number) =>
      client.put<void, { new_position: number }>(`/v1/queue/threads/${id}/position/`, { new_position: position }),
    moveToFront: (id: number) => client.put<void>(`/v1/queue/threads/${id}/front/`),
    moveToBack: (id: number) => client.put<void>(`/v1/queue/threads/${id}/back/`),
    shuffle: () => client.post<void>('/v1/queue/shuffle/'),
  }
}

export const queueApi = createQueueApi(defaultHttpClient())
