/**
 * In-test HTTP request recorder for request-budget regressions (#4501).
 *
 * Wraps the standard {@link createHttpClientStub} transport so a route can run
 * through its real service layer while the test records the exact HTTP method,
 * path, and query parameters the browser would send.
 */
import { createHttpClientStub } from './httpClientStub'
import type { HttpClient } from '../services/httpClient'

/** JSON value accepted by a recorded response or request body. */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | JsonValue[]
  | { [key: string]: JsonValue }

/** One HTTP call observed at the transport seam. */
export type RecordedCall = {
  method: string
  url: string
  params?: Record<string, string | number>
  data?: JsonValue
}

/** Responder invoked for each recorded call. */
export type Responder = (call: RecordedCall) => JsonValue | Promise<JsonValue>

/**
 * Build a recording transport plus the list of calls it observed.
 *
 * @param responder - Returns the response body for one call.
 * @returns The capture list and an `HttpClient` backed by it.
 */
export function createRequestRecorder(responder: Responder) {
  const calls: RecordedCall[] = []
  const client = createHttpClientStub()
  const respond = (
    method: string,
    url: string,
    params?: Record<string, string | number>,
    data?: JsonValue,
  ) => {
    const call = { method, url, params, data }
    calls.push(call)
    return Promise.resolve(responder(call))
  }
  client.get.mockImplementation(
    (url: string, config?: { params?: Record<string, string | number> }) =>
      respond('GET', url, config?.params),
  )
  client.delete.mockImplementation(
    (url: string, config?: { params?: Record<string, string | number> }) =>
      respond('DELETE', url, config?.params),
  )
  client.post.mockImplementation((url: string, data?: JsonValue) =>
    respond('POST', url, undefined, data),
  )
  client.put.mockImplementation((url: string, data?: JsonValue) =>
    respond('PUT', url, undefined, data),
  )
  client.patch.mockImplementation((url: string, data?: JsonValue) =>
    respond('PATCH', url, undefined, data),
  )
  return { calls, client }
}

/**
 * Canonical `METHOD path?sorted-query` key for one recorded call.
 *
 * @param call - Recorded transport call.
 * @returns Stable request key for budget assertions.
 */
export function requestKey(call: RecordedCall): string {
  const params = call.params
    ? `?${Object.keys(call.params)
        .sort()
        .map((name) => `${name}=${String(call.params?.[name])}`)
        .join('&')}`
    : ''
  return `${call.method} ${call.url}${params}`
}

/**
 * Count every distinct request key so duplicate in-flight/retry calls fail a
 * budget assertion instead of being collapsed by a `Set`.
 *
 * @param calls - Recorded transport calls.
 * @returns Request key to observed count.
 */
export function requestCounts(calls: RecordedCall[]) {
  const counts: Record<string, number> = {}
  for (const call of calls) {
    const key = requestKey(call)
    counts[key] = (counts[key] ?? 0) + 1
  }
  return counts
}

/**
 * Read the thread ids from a batch request body.
 *
 * @param call - Recorded `POST` call.
 * @returns Requested ids, or an empty list for an unrelated body.
 */
export function requestedThreadIds(call: RecordedCall): number[] {
  // SAFETY: the only batch body recorded in these tests is the service's own `{ thread_ids: number[] }` payload.
  const body = call.data as { thread_ids?: number[] } | undefined
  return Array.isArray(body?.thread_ids) ? body.thread_ids : []
}
