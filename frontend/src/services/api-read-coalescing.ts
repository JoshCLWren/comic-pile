import {
  getAccessToken,
  sessionApi,
  threadsApi,
} from './api'

type InFlightRead = {
  request: Promise<unknown>
  startedAt: number
}

const COALESCE_BURST_WINDOW_MS = 250
const inFlightReads = new Map<string, InFlightRead>()
let installed = false

function stableSerialize(value: unknown): string {
  if (value === undefined) return 'undefined'
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(stableSerialize).join(',')}]`

  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, entryValue]) => `${JSON.stringify(key)}:${stableSerialize(entryValue)}`)
  return `{${entries.join(',')}}`
}

export function coalesceRead<T>(key: string, loader: () => Promise<T>): Promise<T> {
  const startedAt = Date.now()
  const existing = inFlightReads.get(key)
  if (
    existing
    && startedAt - existing.startedAt <= COALESCE_BURST_WINDOW_MS
  ) {
    return existing.request as Promise<T>
  }

  const request = loader()
  inFlightReads.set(key, { request, startedAt })

  const removeRequest = () => {
    if (inFlightReads.get(key)?.request === request) {
      inFlightReads.delete(key)
    }
  }
  void request.then(removeRequest, removeRequest)

  return request
}

export function clearCoalescedReads(): void {
  inFlightReads.clear()
}

function requestKey(operation: string, args: readonly unknown[]): string {
  return `${getAccessToken() ?? 'anonymous'}:${operation}:${stableSerialize(args)}`
}

export function installApiReadCoalescing(): void {
  if (installed) return
  installed = true

  const originalThreadsList = threadsApi.list.bind(threadsApi)
  const originalStaleThreads = threadsApi.listStale.bind(threadsApi)
  const originalCurrentSession = sessionApi.getCurrent.bind(sessionApi)

  threadsApi.list = ((...args: Parameters<typeof originalThreadsList>) =>
    coalesceRead(
      requestKey('threads.list', args),
      () => originalThreadsList(...args),
    )) as typeof threadsApi.list

  threadsApi.listStale = ((...args: Parameters<typeof originalStaleThreads>) =>
    coalesceRead(
      requestKey('threads.listStale', args),
      () => originalStaleThreads(...args),
    )) as typeof threadsApi.listStale

  sessionApi.getCurrent = ((...args: Parameters<typeof originalCurrentSession>) =>
    coalesceRead(
      requestKey('session.getCurrent', args),
      () => originalCurrentSession(...args),
    )) as typeof sessionApi.getCurrent
}
