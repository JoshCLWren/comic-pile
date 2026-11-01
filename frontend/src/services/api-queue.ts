import { defaultHttpClient, type HttpClient } from './httpClient'

/**
 * Rank beyond any real queue used to express "back".
 *
 * The v2 queue-entry resource is patched with a target rank, so appending does
 * not need a custom action endpoint. A rank past the end places the entry last.
 */
const LAST_QUEUE_POSITION = 2_147_483_647

let queueOrderSequence = 0

/**
 * Build a retry key so a duplicated shuffle request replays one revision.
 *
 * @returns A client-generated idempotency key.
 */
function newQueueOrderKey(): string {
  const uuid = globalThis.crypto?.randomUUID?.()
  if (uuid) return uuid
  queueOrderSequence += 1
  return `queue-order-${Date.now()}-${queueOrderSequence}`
}

/**
 * Build the queue service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every queue request.
 * @returns The queue API bound to `client`.
 */
export function createQueueApi(client: HttpClient) {
  const setPosition = (id: number, position: number) =>
    client.patch<void, { position: number }>(`/v2/queue-entries/${id}`, { position })

  return {
    moveToPosition: (id: number, position: number) => setPosition(id, position),
    moveToFront: (id: number) => setPosition(id, 1),
    moveToBack: (id: number) => setPosition(id, LAST_QUEUE_POSITION),
    shuffle: (idempotencyKey: string = newQueueOrderKey()) =>
      client.post<void, { idempotency_key: string }>('/v2/queue-orders', {
        idempotency_key: idempotencyKey,
      }),
  }
}

export const queueApi = createQueueApi(defaultHttpClient())
