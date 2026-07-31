import {
  type BrowserContext,
  type Page,
  type Request,
  type Response,
  type TestInfo,
} from '@playwright/test'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import workloadActions from './fixtures/production-profile-workload.actions.json'
import workloadManifest from './fixtures/production-profile-workload.json'
export { default as workloadRoutes } from './fixtures/production-profile-workload.routes.json'

export type WorkloadScope = 'workload' | 'fixture-setup' | 'cleanup' | 'reconciliation'

export type ActionGroup = {
  id: string
  phase: string
  label: string
  requestCount: number
  expectedRequestCountRange: [number, number]
  pauseAfterPreviousActionMs: number
  expectedFollowUps: string[]
}

export type ApiRecord = {
  sequence: number
  actionId: string
  scope: WorkloadScope
  method: string
  route: string
  status: number | null
  startedAt: number
  durationMs: number
  requestBodyShape: unknown
  requestId: string | null
  cacheStatus: string | null
  databaseQueries: number | null
  serverTiming: string | null
  vercelId: string | null
  transportFailure: string | null
}

export type ActionTimelineEntry = {
  id: string
  phase: string
  label: string
  startedAt: string
  finishedAt: string
  durationMs: number
  pauseMs: number
  requestCount: number
  status: 'completed' | 'failed' | 'excluded'
  note?: string
}

export type BrowserApiResult<T> = {
  ok: boolean
  status: number
  body: T
}

export type Thread = {
  id: number
  title: string
  format: string
  issues_remaining: number
  total_issues: number | null
  queue_position: number
  status: string
  notes?: string | null
  last_rating?: number | null
}

export type ThreadListResponse = {
  threads: Thread[]
  next_page_token: string | null
}

export type Issue = {
  id: number
  thread_id: number
  issue_number: string
  status: 'read' | 'unread'
}

export type IssueListResponse = {
  issues: Issue[]
  total_count: number
  next_page_token: string | null
}

export type SessionCurrent = {
  id: number
  current_die: number
  manual_die?: number | null
  pending_thread_id?: number | null
  ladder_path?: string | null
  active_thread?: { id: number; issue_number?: string | null } | null
}

export type SessionListResponse = {
  sessions: unknown[]
  next_page_token: string | null
}

export type AnalyticsMetrics = {
  total_threads: number
  active_threads: number
  completed_threads: number
  event_stats?: Record<string, number>
}

export type RollResponse = {
  thread_id: number
  title: string
  issue_number: string | null
}

export type Dependency = {
  id: number
}

export type ThreadDependenciesResponse = {
  blocking: Dependency[]
  blocked_by: Dependency[]
}

export type FixtureState = {
  primary: Thread
  dependencyTarget: Thread
  completed: Thread
  primaryIssues: Issue[]
  targetIssues: Issue[]
  completedIssues: Issue[]
  createdDependencyIds: Set<number>
  createdThreadIds: Set<number>
}

export type AccountComplexitySnapshot = {
  capturedAt: string
  totalThreads: number
  activeThreads: number
  completedThreads: number
  staleThreads: number
  firstHistoryPageSize: number
  historyHasNextPage: boolean
  currentSession: {
    id: number
    currentDie: number
    manualDie: number | null
    pendingThreadPresent: boolean
    ladderSteps: number
    activeThreadPresent: boolean
  }
  analytics: {
    totalThreads: number
    activeThreads: number
    completedThreads: number
    eventStats: Record<string, number>
  }
}

export type RatingOutcome = {
  actionId: string
  threadId: number
  rating: number
  requestStatus: number | null
  classification: 'definite-success' | 'definite-failure' | 'unknown-outcome'
  authoritativeStateChecked: boolean
  authoritativeRating: number | null
  detail: string
}

export type CleanupReport = {
  attempted: boolean
  dependencyIdsDeleted: number[]
  threadIdsDeleted: number[]
  fixtureThreadsRemaining: number[]
  unrelatedThreadStateChanged: string[]
  verified: boolean
  errors: string[]
}

export type NetworkProfile = {
  records: ApiRecord[]
  settle: () => Promise<void>
  finish: () => Promise<void>
  getCapturedAccessToken: () => string | null
  getAuthenticatedUsername: () => string | null
}

export class BrowserApiError extends Error {
  readonly status: number | null
  readonly transportFailure: boolean

  constructor(message: string, status: number | null, transportFailure: boolean) {
    super(message)
    this.name = 'BrowserApiError'
    this.status = status
    this.transportFailure = transportFailure
  }
}

export const manifest = {
  ...workloadManifest,
  actionGroups: workloadActions.actionGroups,
} as unknown as {
  manifestVersion: string
  source: {
    fileName: string
    sha256: string
    apiRequestCount: number
    capturedAt: string
  }
  sourceAccountBaseline: Record<string, unknown>
  baseline: {
    latencyMs: Record<string, number>
    expectedEquivalentWorkloadRequestCountRange: [number, number]
  }
  actionGroups: ActionGroup[]
  coverage: Array<{ action: string; classification: string; reason: string }>
}

export const actionById = new Map(manifest.actionGroups.map((action) => [action.id, action]))
export const expectedActionIds = manifest.actionGroups.map((action) => action.id)
export const fixturePrefix = 'PROD PROFILE FIXTURE'
export const defaultUsername = 'Josh_Digital_Comics'
export const requestTimeoutMs = 10_000

export function numericEnvironmentValue(name: string, fallback: number, minimum = 0): number {
  const rawValue = process.env[name]
  if (rawValue === undefined) return fallback

  const parsed = Number(rawValue)
  if (!Number.isFinite(parsed) || parsed < minimum) {
    throw new Error(`${name} must be a number greater than or equal to ${minimum}`)
  }
  return parsed
}

export function percentile(values: number[], quantile: number): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * quantile) - 1))
  return Math.round((sorted[index] ?? 0) * 100) / 100
}

export function normalizeRoute(rawUrl: string): string {
  const url = new URL(rawUrl)
  const normalizedPath = url.pathname.replace(/\/\d+(?=\/|:|$)/g, '/:id')
  const params = new URLSearchParams()
  for (const [key, value] of [...url.searchParams.entries()].sort(([left], [right]) =>
    left.localeCompare(right),
  )) {
    const normalizedValue = key === 'page_token' || key.endsWith('_id') ? ':value' : value
    params.append(key, normalizedValue)
  }
  const query = params.toString()
  return query ? `${normalizedPath}?${query}` : normalizedPath
}

export function safeBodyShape(rawBody: string | null): unknown {
  if (!rawBody) return null

  try {
    const value = JSON.parse(rawBody) as unknown
    return shapeOf(value)
  } catch {
    return { body: 'non-json' }
  }
}

export function shapeOf(value: unknown): unknown {
  if (value === null) return null
  if (Array.isArray(value)) return value.length === 0 ? [] : [shapeOf(value[0])]
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, shapeOf(nested)]),
    )
  }
  return typeof value
}

export function parseDatabaseQueryCount(value: string | undefined): number | null {
  if (value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function isApiRequest(url: string): boolean {
  return new URL(url).pathname.startsWith('/api/')
}

export function loadHarCookies(harPath: string, baseUrl: string): Array<{
  name: string
  value: string
  domain: string
  path: string
  expires?: number
  httpOnly?: boolean
  secure?: boolean
  sameSite?: 'Strict' | 'Lax' | 'None'
}> {
  const raw = JSON.parse(readFileSync(harPath, 'utf8')) as {
    log?: {
      entries?: Array<{
        request?: { cookies?: Array<Record<string, unknown>> }
        response?: { cookies?: Array<Record<string, unknown>> }
      }>
    }
  }
  const base = new URL(baseUrl)
  const cookiesByKey = new Map<string, ReturnType<typeof loadHarCookies>[number]>()

  for (const entry of raw.log?.entries ?? []) {
    for (const source of [entry.request?.cookies ?? [], entry.response?.cookies ?? []]) {
      for (const cookie of source) {
        const name = typeof cookie.name === 'string' ? cookie.name : null
        const value = typeof cookie.value === 'string' ? cookie.value : null
        if (!name || value === null) continue

        const domain = typeof cookie.domain === 'string' && cookie.domain
          ? cookie.domain
          : base.hostname
        const path = typeof cookie.path === 'string' && cookie.path ? cookie.path : '/'
        const sameSiteRaw = typeof cookie.sameSite === 'string' ? cookie.sameSite.toLowerCase() : ''
        const sameSite = sameSiteRaw === 'strict'
          ? 'Strict'
          : sameSiteRaw === 'none'
            ? 'None'
            : sameSiteRaw === 'lax'
              ? 'Lax'
              : undefined
        const expires = typeof cookie.expires === 'string'
          ? Math.floor(Date.parse(cookie.expires) / 1000)
          : undefined

        cookiesByKey.set(`${name}|${domain}|${path}`, {
          name,
          value,
          domain,
          path,
          ...(Number.isFinite(expires) ? { expires } : {}),
          ...(typeof cookie.httpOnly === 'boolean' ? { httpOnly: cookie.httpOnly } : {}),
          ...(typeof cookie.secure === 'boolean' ? { secure: cookie.secure } : {}),
          ...(sameSite ? { sameSite } : {}),
        })
      }
    }
  }

  return [...cookiesByKey.values()].filter((cookie) =>
    cookie.name === 'refresh_token' || cookie.name === 'csrf_token',
  )
}

export async function installCredentialSource(context: BrowserContext, baseUrl: string): Promise<string> {
  const storageStatePath = process.env.PROD_PROFILE_STORAGE_STATE
  if (storageStatePath) {
    if (!existsSync(storageStatePath)) {
      throw new Error(`PROD_PROFILE_STORAGE_STATE does not exist: ${storageStatePath}`)
    }
    return `storage-state:${createHash('sha256').update(storageStatePath).digest('hex').slice(0, 12)}`
  }

  const harPath = process.env.PROD_PROFILE_HAR_PATH
  if (!harPath || !existsSync(harPath)) {
    throw new Error(
      'Set PROD_PROFILE_STORAGE_STATE to an authenticated Playwright storage state or ' +
      'PROD_PROFILE_HAR_PATH to the local credential-bearing source HAR.',
    )
  }

  const cookies = loadHarCookies(harPath, baseUrl)
  if (!cookies.some((cookie) => cookie.name === 'refresh_token')) {
    throw new Error('The supplied HAR does not contain a refresh_token cookie.')
  }
  await context.addCookies(cookies)
  return `har:${createHash('sha256').update(readFileSync(harPath)).digest('hex').slice(0, 12)}`
}

export function installNetworkProfile(
  page: Page,
  currentContext: () => { actionId: string; scope: WorkloadScope },
): NetworkProfile {
  const starts = new Map<Request, {
    startedAt: number
    actionId: string
    scope: WorkloadScope
    requestBodyShape: unknown
  }>()
  const records: ApiRecord[] = []
  const tasks: Array<Promise<void>> = []
  let capturedAccessToken: string | null = null
  let authenticatedUsername: string | null = null
  let sequence = 0

  page.on('request', (request) => {
    if (!isApiRequest(request.url())) return
    const context = currentContext()
    starts.set(request, {
      startedAt: Date.now(),
      actionId: context.actionId,
      scope: context.scope,
      requestBodyShape: safeBodyShape(request.postData()),
    })
  })

  page.on('requestfailed', (request) => {
    if (!isApiRequest(request.url())) return
    const start = starts.get(request)
    if (!start) return
    records.push({
      sequence: sequence++,
      actionId: start.actionId,
      scope: start.scope,
      method: request.method(),
      route: normalizeRoute(request.url()),
      status: null,
      startedAt: start.startedAt,
      durationMs: Date.now() - start.startedAt,
      requestBodyShape: start.requestBodyShape,
      requestId: null,
      cacheStatus: null,
      databaseQueries: null,
      serverTiming: null,
      vercelId: null,
      transportFailure: request.failure()?.errorText ?? 'unknown transport failure',
    })
    starts.delete(request)
  })

  page.on('response', (response: Response) => {
    if (!isApiRequest(response.url())) return
    const request = response.request()
    const start = starts.get(request)
    if (!start) return

    tasks.push((async () => {
      try {
        await response.finished()
        const headers = await response.allHeaders()
        const pathname = new URL(response.url()).pathname

        if (pathname === '/api/auth/refresh' && response.ok()) {
          const payload = await response.json() as { access_token?: unknown }
          if (typeof payload.access_token === 'string') capturedAccessToken = payload.access_token
        }
        if (pathname === '/api/auth/me' && response.ok()) {
          const payload = await response.json() as { username?: unknown }
          if (typeof payload.username === 'string') authenticatedUsername = payload.username
        }

        records.push({
          sequence: sequence++,
          actionId: start.actionId,
          scope: start.scope,
          method: request.method(),
          route: normalizeRoute(response.url()),
          status: response.status(),
          startedAt: start.startedAt,
          durationMs: Date.now() - start.startedAt,
          requestBodyShape: start.requestBodyShape,
          requestId: headers['x-request-id'] ?? null,
          cacheStatus: headers['x-app-cache'] ?? null,
          databaseQueries: parseDatabaseQueryCount(headers['x-app-db-queries']),
          serverTiming: headers['server-timing'] ?? null,
          vercelId: headers['x-vercel-id'] ?? null,
          transportFailure: null,
        })
      } catch (error) {
        records.push({
          sequence: sequence++,
          actionId: start.actionId,
          scope: start.scope,
          method: request.method(),
          route: normalizeRoute(request.url()),
          status: response.status(),
          startedAt: start.startedAt,
          durationMs: Date.now() - start.startedAt,
          requestBodyShape: start.requestBodyShape,
          requestId: null,
          cacheStatus: null,
          databaseQueries: null,
          serverTiming: null,
          vercelId: null,
          transportFailure: errorText(error),
        })
      } finally {
        starts.delete(request)
      }
    })())
  })

  const settle = async (): Promise<void> => {
    await page.waitForTimeout(100)
    while (tasks.length > 0) {
      await Promise.all(tasks.splice(0, tasks.length))
    }
  }

  return {
    records,
    settle,
    getCapturedAccessToken: () => capturedAccessToken,
    getAuthenticatedUsername: () => authenticatedUsername,
    finish: async () => {
      await page.waitForTimeout(300)
      await settle()
      records.sort((left, right) => left.startedAt - right.startedAt || left.sequence - right.sequence)
    },
  }
}

export async function waitForCapturedAuth(profile: NetworkProfile, page: Page): Promise<void> {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    if (profile.getCapturedAccessToken() && profile.getAuthenticatedUsername()) return
    await page.waitForTimeout(100)
  }
  throw new Error('Authentication bootstrap did not produce an access token and authenticated user.')
}

export async function browserApi<T>(
  page: Page,
  accessToken: string,
  path: string,
  options: { method?: string; body?: unknown; timeoutMs?: number } = {},
): Promise<BrowserApiResult<T>> {
  const result = await page.evaluate(async ({ token, requestPath, requestOptions }: {
    token: string
    requestPath: string
    requestOptions: { method: string; body?: unknown; timeoutMs: number }
  }) => {
    const method = requestOptions.method ?? 'GET'
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), requestOptions.timeoutMs)

    const readCookie = (name: string): string | null => {
      const prefix = `${encodeURIComponent(name)}=`
      for (const cookie of document.cookie.split('; ')) {
        if (cookie.startsWith(prefix)) return decodeURIComponent(cookie.slice(prefix.length))
      }
      return null
    }

    try {
      const headers: Record<string, string> = {
        Authorization: `Bearer ${token}`,
      }
      if (requestOptions.body !== undefined) headers['Content-Type'] = 'application/json'
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())) {
        const csrfToken = readCookie('csrf_token')
        if (csrfToken) headers['X-CSRF-Token'] = csrfToken
      }

      const response = await fetch(requestPath, {
        method,
        headers,
        body: requestOptions.body === undefined ? undefined : JSON.stringify(requestOptions.body),
        signal: controller.signal,
      })
      const text = await response.text()
      let body: unknown = null
      if (text) {
        try {
          body = JSON.parse(text) as unknown
        } catch {
          body = text
        }
      }
      return { kind: 'response' as const, ok: response.ok, status: response.status, body }
    } catch (error) {
      return {
        kind: 'transport' as const,
        message: error instanceof Error ? error.message : String(error),
      }
    } finally {
      window.clearTimeout(timeout)
    }
  }, {
    token: accessToken,
    requestPath: path,
    requestOptions: {
      method: options.method ?? 'GET',
      body: options.body,
      timeoutMs: options.timeoutMs ?? requestTimeoutMs,
    },
  })

  if (result.kind === 'transport') {
    throw new BrowserApiError(result.message, null, true)
  }
  if (!result.ok) {
    throw new BrowserApiError(
      `${options.method ?? 'GET'} ${path} returned ${result.status}`,
      result.status,
      false,
    )
  }
  return result as BrowserApiResult<T>
}

export async function ensureCsrfCookie(page: Page, accessToken: string): Promise<void> {
  const existing = await page.evaluate(() => document.cookie.includes('csrf_token='))
  if (existing) return
  await browserApi<{ csrf_token: string }>(page, accessToken, '/api/auth/csrf')
}

export async function createThread(
  page: Page,
  accessToken: string,
  payload: { title: string; format: string; issues_remaining: number; notes: string },
): Promise<Thread> {
  return (await browserApi<Thread>(page, accessToken, '/api/threads/', {
    method: 'POST',
    body: payload,
  })).body
}

export async function listIssues(page: Page, accessToken: string, threadId: number): Promise<Issue[]> {
  return (await browserApi<IssueListResponse>(
    page,
    accessToken,
    `/api/v1/threads/${threadId}/issues?page_size=100`,
  )).body.issues
}

export async function setupFixture(page: Page, accessToken: string, runId: string): Promise<FixtureState> {
  const createdThreadIds = new Set<number>()
  const createdDependencyIds = new Set<number>()

  const primary = await createThread(page, accessToken, {
    title: `${fixturePrefix} ${runId} MAIN`,
    format: 'Comics',
    issues_remaining: 40,
    notes: 'Faithful real-user production profile fixture. Safe to delete.',
  })
  createdThreadIds.add(primary.id)
  await browserApi(page, accessToken, `/api/v1/threads/${primary.id}/issues`, {
    method: 'POST',
    body: { issue_range: '1-40' },
  })

  const dependencyTarget = await createThread(page, accessToken, {
    title: `${fixturePrefix} ${runId} DEPENDENCY`,
    format: 'Trade',
    issues_remaining: 4,
    notes: 'Dependency target for production profile fixture.',
  })
  createdThreadIds.add(dependencyTarget.id)
  await browserApi(page, accessToken, `/api/v1/threads/${dependencyTarget.id}/issues`, {
    method: 'POST',
    body: { issue_range: '1-4' },
  })

  const completed = await createThread(page, accessToken, {
    title: `${fixturePrefix} ${runId} COMPLETED`,
    format: 'Comics',
    issues_remaining: 2,
    notes: 'Completed fixture used only for reversible reactivation coverage.',
  })
  createdThreadIds.add(completed.id)
  await browserApi(page, accessToken, `/api/v1/threads/${completed.id}/issues`, {
    method: 'POST',
    body: { issue_range: '1-2' },
  })

  const primaryIssues = await listIssues(page, accessToken, primary.id)
  const targetIssues = await listIssues(page, accessToken, dependencyTarget.id)
  const completedIssues = await listIssues(page, accessToken, completed.id)

  for (const issue of primaryIssues.slice(0, 12)) {
    await browserApi(page, accessToken, `/api/v1/issues/${issue.id}:markRead`, { method: 'POST' })
  }
  for (const issue of completedIssues) {
    await browserApi(page, accessToken, `/api/v1/issues/${issue.id}:markRead`, { method: 'POST' })
  }

  const completedState = (await browserApi<Thread>(page, accessToken, `/api/threads/${completed.id}`)).body
  if (completedState.status !== 'completed') {
    throw new Error(`Completed fixture did not enter completed state; status=${completedState.status}`)
  }

  return {
    primary,
    dependencyTarget,
    completed: completedState,
    primaryIssues: await listIssues(page, accessToken, primary.id),
    targetIssues,
    completedIssues: await listIssues(page, accessToken, completed.id),
    createdDependencyIds,
    createdThreadIds,
  }
}

export function unrelatedThreadFingerprint(threads: Thread[]): Map<number, string> {
  return new Map(
    threads
      .filter((thread) => !thread.title.startsWith(fixturePrefix))
      .map((thread) => [
        thread.id,
        JSON.stringify({
          title: thread.title,
          format: thread.format,
          status: thread.status,
          issues_remaining: thread.issues_remaining,
          total_issues: thread.total_issues,
          notes: thread.notes ?? null,
          queue_position: thread.queue_position,
        }),
      ]),
  )
}

export function compareThreadFingerprints(before: Map<number, string>, after: Map<number, string>): string[] {
  const changes: string[] = []
  for (const [id, value] of before) {
    if (!after.has(id)) changes.push(`unrelated thread ${id} disappeared`)
    else if (after.get(id) !== value) changes.push(`unrelated thread ${id} changed`)
  }
  for (const id of after.keys()) {
    if (!before.has(id)) changes.push(`unexpected unrelated thread ${id} appeared`)
  }
  return changes
}

export async function captureAccountComplexity(page: Page, accessToken: string): Promise<AccountComplexitySnapshot> {
  const [threadList, stale, history, current, analytics] = await Promise.all([
    browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
    browserApi<Thread[]>(page, accessToken, '/api/threads/stale?days=7'),
    browserApi<SessionListResponse>(page, accessToken, '/api/sessions/?page_size=50'),
    browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
    browserApi<AnalyticsMetrics>(page, accessToken, '/api/analytics/metrics'),
  ])
  const threads = threadList.body.threads.filter((thread) => !thread.title.startsWith(fixturePrefix))
  const currentSession = current.body

  return {
    capturedAt: new Date().toISOString(),
    totalThreads: threads.length,
    activeThreads: threads.filter((thread) => thread.status === 'active').length,
    completedThreads: threads.filter((thread) => thread.status === 'completed').length,
    staleThreads: stale.body.filter((thread) => !thread.title.startsWith(fixturePrefix)).length,
    firstHistoryPageSize: history.body.sessions.length,
    historyHasNextPage: history.body.next_page_token !== null,
    currentSession: {
      id: currentSession.id,
      currentDie: currentSession.current_die,
      manualDie: currentSession.manual_die ?? null,
      pendingThreadPresent: currentSession.pending_thread_id !== null && currentSession.pending_thread_id !== undefined,
      ladderSteps: currentSession.ladder_path?.split(',').filter(Boolean).length ?? 0,
      activeThreadPresent: currentSession.active_thread !== null && currentSession.active_thread !== undefined,
    },
    analytics: {
      totalThreads: analytics.body.total_threads,
      activeThreads: analytics.body.active_threads,
      completedThreads: analytics.body.completed_threads,
      eventStats: analytics.body.event_stats ?? {},
    },
  }
}

export async function rateWithReconciliation(
  page: Page,
  accessToken: string,
  actionId: string,
  threadId: number,
  issueNumber: string,
  rating: number,
): Promise<RatingOutcome> {
  try {
    const response = await browserApi<unknown>(page, accessToken, '/api/rate/', {
      method: 'POST',
      body: {
        thread_id: threadId,
        rating,
        finish_session: false,
        issue_number: issueNumber,
      },
    })
    return {
      actionId,
      threadId,
      rating,
      requestStatus: response.status,
      classification: 'definite-success',
      authoritativeStateChecked: false,
      authoritativeRating: null,
      detail: 'Rating endpoint returned a successful HTTP response.',
    }
  } catch (error) {
    const apiError = error instanceof BrowserApiError ? error : null
    if (apiError && !apiError.transportFailure && apiError.status !== null) {
      return {
        actionId,
        threadId,
        rating,
        requestStatus: apiError.status,
        classification: 'definite-failure',
        authoritativeStateChecked: false,
        authoritativeRating: null,
        detail: apiError.message,
      }
    }

    await page.waitForTimeout(750)
    try {
      const authoritative = (await browserApi<Thread>(
        page,
        accessToken,
        `/api/threads/${threadId}`,
      )).body
      const authoritativeRating = typeof authoritative.last_rating === 'number'
        ? authoritative.last_rating
        : null
      return {
        actionId,
        threadId,
        rating,
        requestStatus: null,
        classification: authoritativeRating === rating ? 'definite-success' : 'unknown-outcome',
        authoritativeStateChecked: true,
        authoritativeRating,
        detail: authoritativeRating === rating
          ? 'The client timed out, but authoritative thread state confirms the rating committed.'
          : 'The client timed out and authoritative state could not prove whether the write committed.',
      }
    } catch (reconciliationError) {
      return {
        actionId,
        threadId,
        rating,
        requestStatus: null,
        classification: 'unknown-outcome',
        authoritativeStateChecked: true,
        authoritativeRating: null,
        detail: `Rating transport failed and reconciliation also failed: ${errorText(reconciliationError)}`,
      }
    }
  }
}

export async function cleanupFixture(
  page: Page,
  accessToken: string,
  fixture: FixtureState | null,
  beforeFingerprint: Map<number, string>,
): Promise<CleanupReport> {
  const report: CleanupReport = {
    attempted: fixture !== null,
    dependencyIdsDeleted: [],
    threadIdsDeleted: [],
    fixtureThreadsRemaining: [],
    unrelatedThreadStateChanged: [],
    verified: false,
    errors: [],
  }
  if (!fixture) return report

  for (const dependencyId of [...fixture.createdDependencyIds]) {
    try {
      await browserApi(page, accessToken, `/api/v1/dependencies/${dependencyId}`, { method: 'DELETE' })
      report.dependencyIdsDeleted.push(dependencyId)
    } catch (error) {
      report.errors.push(`dependency ${dependencyId}: ${errorText(error)}`)
    }
  }

  for (const threadId of [...fixture.createdThreadIds].reverse()) {
    try {
      await browserApi(page, accessToken, `/api/threads/${threadId}`, { method: 'DELETE' })
      report.threadIdsDeleted.push(threadId)
    } catch (error) {
      report.errors.push(`thread ${threadId}: ${errorText(error)}`)
    }
  }

  try {
    const threads = (await browserApi<ThreadListResponse>(
      page,
      accessToken,
      '/api/threads/?page_size=200',
    )).body.threads
    report.fixtureThreadsRemaining = threads
      .filter((thread) => fixture.createdThreadIds.has(thread.id))
      .map((thread) => thread.id)
    report.unrelatedThreadStateChanged = compareThreadFingerprints(
      beforeFingerprint,
      unrelatedThreadFingerprint(threads),
    )
  } catch (error) {
    report.errors.push(`cleanup verification: ${errorText(error)}`)
  }

  report.verified = report.errors.length === 0
    && report.fixtureThreadsRemaining.length === 0
    && report.unrelatedThreadStateChanged.length === 0
  return report
}

export function routeSummary(records: ApiRecord[]): Record<string, unknown> {
  const grouped = new Map<string, ApiRecord[]>()
  for (const record of records) {
    const key = `${record.method} ${record.route}`
    const current = grouped.get(key) ?? []
    current.push(record)
    grouped.set(key, current)
  }

  return Object.fromEntries(
    [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([route, rows]) => {
      const durations = rows.map((row) => row.durationMs)
      return [route, {
        count: rows.length,
        p50Ms: percentile(durations, 0.5),
        p90Ms: percentile(durations, 0.9),
        p95Ms: percentile(durations, 0.95),
        p99Ms: percentile(durations, 0.99),
        maxMs: Math.max(...durations),
        statuses: rows.reduce<Record<string, number>>((counts, row) => {
          const status = row.status === null ? 'transport-failure' : String(row.status)
          counts[status] = (counts[status] ?? 0) + 1
          return counts
        }, {}),
      }]
    }),
  )
}

export function duplicateGetBursts(records: ApiRecord[], windowMs: number): Array<{
  route: string
  gapMs: number
  previousActionId: string
  actionId: string
}> {
  const previousByRoute = new Map<string, ApiRecord>()
  const duplicates: Array<{
    route: string
    gapMs: number
    previousActionId: string
    actionId: string
  }> = []
  for (const record of records) {
    if (record.method !== 'GET') continue
    const previous = previousByRoute.get(record.route)
    if (previous) {
      const gapMs = record.startedAt - previous.startedAt
      if (gapMs <= windowMs) {
        duplicates.push({
          route: record.route,
          gapMs,
          previousActionId: previous.actionId,
          actionId: record.actionId,
        })
      }
    }
    previousByRoute.set(record.route, record)
  }
  return duplicates
}

export async function attachJson(testInfo: TestInfo, name: string, value: unknown): Promise<void> {
  await testInfo.attach(name, {
    body: Buffer.from(JSON.stringify(value, null, 2)),
    contentType: 'application/json',
  })
}

