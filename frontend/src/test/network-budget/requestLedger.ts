import axios, {
  AxiosHeaders,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'

/** Query parameters with every value materialised as a string list. */
export type QueryValues = Record<string, string[]>

/** Handlers keyed by canonical `METHOD /path` identity. */
export type HandlerMap = Record<string, LedgerHandler>

/** Request counts keyed by canonical request identity. */
export type RequestCounts = Record<string, number>

/** Path and query parsed from one fully-built request URI. */
export interface ParsedRequestUrl {
  path: string
  query: QueryValues
}

/**
 * One request as the frontend actually emitted it at the axios transport
 * boundary, after request interceptors (auth headers, retries) and before the
 * response interceptor unwraps the payload.
 */
export interface RecordedRequest {
  /** Uppercase HTTP verb. */
  method: string
  /** Origin-relative pathname, including the client `baseURL` (`/api/...`). */
  path: string
  /** Query parameters with every value materialised as a string list. */
  query: QueryValues
  /** Canonical `METHOD path?sorted-query` identity used in budgets/reports. */
  url: string
  /** Monotonic position inside the ledger, starting at 1. */
  sequence: number
  /** True when the request carried an `Authorization` header. */
  authenticated: boolean
  /** Caller-provided label for the UI action being measured. */
  action: string
}

/** Response a handler supplies for a recorded request. */
export interface LedgerResponse {
  status?: number
  data?: unknown
  headers?: Record<string, string>
}

/**
 * Resolve a recorded request to a deterministic response.
 *
 * Returning `undefined` means the request is unhandled; it is still recorded
 * and answered with the ledger's default response so a missing stub is visible
 * as an explicit `unhandled()` assertion rather than a silent network call.
 */
export type LedgerHandler = (request: RecordedRequest) => LedgerResponse | undefined

/** Options for {@link installNetworkLedger}. */
export interface NetworkLedgerOptions {
  /** Handlers keyed by `METHOD /path`. */
  handlers?: HandlerMap
  /** Response used when no handler matches. Defaults to `{ status: 200, data: {} }`. */
  defaultResponse?: LedgerResponse
  /** Label applied to requests recorded before the next `beginAction`. */
  initialAction?: string
}

/** Mutable, inspectable request ledger installed on the app's axios client. */
export interface NetworkLedger {
  /** Replace the app axios adapter with this ledger. */
  attach: (client: { defaults: { adapter?: unknown } }) => void
  /** Label subsequent requests as belonging to one UI action. */
  beginAction: (action: string) => void
  /** Forget all recorded requests and unhandled keys. */
  reset: () => void
  /** Requests recorded so far, in emission order. */
  requests: () => RecordedRequest[]
  /** Requests recorded since a sequence marker (inclusive of the marker+1). */
  since: (marker: number) => RecordedRequest[]
  /** Current sequence marker for scoping one action. */
  mark: () => number
  /** Counts keyed by canonical request identity. */
  summary: () => RequestCounts
  /** Canonical identities requested more than once, with counts. */
  duplicates: () => RequestCounts
  /** `METHOD path` keys that had no matching handler. */
  unhandled: () => string[]
  /** Requests still in flight. */
  pending: () => number
}

function parseUrl(rawUrl: string): ParsedRequestUrl {
  const parsed = new URL(rawUrl, 'http://comic-pile.test')
  const query: QueryValues = {}
  parsed.searchParams.forEach((value, key) => {
    query[key] = [...(query[key] ?? []), value]
  })
  return { path: parsed.pathname, query }
}

/**
 * Sort query keys and values so equivalent parameter orderings share one
 * canonical budget identity.
 *
 * @param query - Query map to canonicalise.
 * @returns Deterministically ordered query string without a leading `?`.
 */
export function canonicalQuery(query: QueryValues): string {
  return Object.keys(query)
    .sort()
    .map(key => {
      const values = [...query[key]].sort()
      return values.map(value => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`).join('&')
    })
    .filter(Boolean)
    .join('&')
}

/**
 * Build the canonical `METHOD path?sorted-query` identity.
 *
 * @param method - HTTP verb.
 * @param path - Origin-relative pathname.
 * @param query - Query values keyed by parameter name.
 * @returns The canonical request identity.
 */
export function canonicalRequest(
  method: string,
  path: string,
  query: QueryValues,
): string {
  const search = canonicalQuery(query)
  return `${method.toUpperCase()} ${path}${search ? `?${search}` : ''}`
}

function buildResponse(config: InternalAxiosRequestConfig, response: LedgerResponse): AxiosResponse {
  return {
    data: response.data ?? {},
    status: response.status ?? 200,
    statusText: response.status && response.status >= 400 ? 'Error' : 'OK',
    headers: response.headers ?? {},
    config,
    request: {},
  }
}

function buildError(config: InternalAxiosRequestConfig, response: LedgerResponse): Error {
  const status = response.status ?? 500
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    config,
    response: {
      data: response.data ?? {},
      status,
      statusText: 'Error',
      headers: response.headers ?? {},
      config,
      request: {},
    },
  })
}

/**
 * Create and install a deterministic request ledger on an axios client.
 *
 * The adapter only replaces the terminal transport. The real request and
 * response interceptor pipeline still runs, so authentication headers,
 * refresh-before-retry, and payload unwrapping behave exactly as in the app.
 *
 * @param client - App axios client whose `defaults.adapter` is replaced.
 * @param options - Response handlers and fallback behaviour.
 * @returns The ledger for assertions and reporting.
 */
export function installNetworkLedger(
  client: { defaults: { adapter?: unknown } },
  options: NetworkLedgerOptions = {},
): NetworkLedger {
  const requests: RecordedRequest[] = []
  const unhandled: string[] = []
  let sequence = 0
  let action = options.initialAction ?? 'mount'
  const handlers: HandlerMap = options.handlers ?? {}
  const defaultResponse = options.defaultResponse ?? { status: 200, data: {} }

  const resolve = (request: RecordedRequest): LedgerResponse | undefined => {
    const handler = handlers[`${request.method} ${request.path}`]
    return handler?.(request)
  }

  const adapter: AxiosAdapter = async config => {
    const method = (config.method ?? 'get').toUpperCase()
    const { path, query } = parseUrl(axios.getUri(config))
    const authorization = AxiosHeaders.from(config.headers).get('Authorization')
    sequence += 1
    const request: RecordedRequest = {
      method,
      path,
      query,
      url: canonicalRequest(method, path, query),
      sequence,
      authenticated: Boolean(authorization),
      action,
    }
    requests.push(request)

    const response = resolve(request)
    if (!response) {
      const key = `${method} ${path}`
      if (!unhandled.includes(key)) unhandled.push(key)
    }
    const settled = response ?? defaultResponse
    if ((settled.status ?? 200) >= 400) {
      throw buildError(config, settled)
    }
    return buildResponse(config, settled)
  }

  const ledger: NetworkLedger = {
    attach: target => {
      target.defaults.adapter = adapter
    },
    beginAction: next => {
      action = next
    },
    reset: () => {
      requests.length = 0
      unhandled.length = 0
      sequence = 0
    },
    requests: () => [...requests],
    since: marker => requests.filter(request => request.sequence > marker),
    mark: () => sequence,
    summary: () => {
      const counts: RequestCounts = {}
      for (const request of requests) counts[request.url] = (counts[request.url] ?? 0) + 1
      return counts
    },
    duplicates: () => {
      const counts = ledger.summary()
      return Object.fromEntries(Object.entries(counts).filter(([, count]) => count > 1))
    },
    unhandled: () => [...unhandled],
    pending: () => 0,
  }

  ledger.attach(client)
  return ledger
}

/**
 * Render one request row for the coordinator's before/after matrix.
 *
 * @param requests - Requests in one action window.
 * @returns Compact `METHOD path?sorted-query xN` lines.
 */
export function describeRequests(requests: RecordedRequest[]): string[] {
  const counts: RequestCounts = {}
  for (const request of requests) counts[request.url] = (counts[request.url] ?? 0) + 1
  return Object.entries(counts)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([url, count]) => `${url} x${count}`)
}
