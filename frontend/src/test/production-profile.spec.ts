import { expect, test, type Page, type Request } from '@playwright/test'
import {
  SELECTORS,
  setRangeInput,
  submitRatingAndWaitForRateResponse,
} from './helpers'

type ApiRecord = {
  method: string
  normalizedUrl: string
  status: number
  durationMs: number
  startedAt: number
  requestId: string | null
  cacheStatus: string | null
  databaseQueries: string | null
  serverTiming: string | null
}

type NetworkProfile = {
  records: ApiRecord[]
  transportFailures: string[]
  finish: () => Promise<void>
}

type ThreadListPayload = {
  threads?: unknown[]
}

type SessionListPayload = {
  sessions?: unknown[]
}

const SOURCE_HAR = {
  capturedAt: '2026-07-30T15:25:46.699-05:00',
  durationMs: 200_602,
  apiRequests: 198,
  accountShape: 'Josh production account after the Vercel, Neon, and Upstash migration',
  actions: [
    'cold authenticated startup and refresh recovery',
    'queue, history, and analytics navigation',
    'rate pending thread',
    'roll and rate',
    'roll and snooze',
    'roll and dismiss pending',
    'manual thread selection and queue movement',
    'open a large issue editor and mutate issue state',
    'dependency management',
    'bug report submission',
    'stale-thread reactivation',
    'manual die changes',
    'final roll and rating',
  ],
} as const

function numericEnvironmentValue(name: string, fallback: number): number {
  const rawValue = process.env[name]
  if (rawValue === undefined) return fallback

  const parsed = Number(rawValue)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive number; received ${JSON.stringify(rawValue)}`)
  }

  return parsed
}

function isApiRequest(url: string): boolean {
  return new URL(url).pathname.startsWith('/api/')
}

function normalizeApiUrl(rawUrl: string): string {
  const url = new URL(rawUrl)
  const normalizedPath = url.pathname.replace(/\/\d+(?=\/|:|$)/g, '/:id')
  const normalizedParams = new URLSearchParams()

  for (const [key, value] of [...url.searchParams.entries()].sort(([left], [right]) =>
    left.localeCompare(right)
  )) {
    const normalizedValue = key === 'page_token' || key.endsWith('_id') ? ':value' : value
    normalizedParams.append(key, normalizedValue)
  }

  const query = normalizedParams.toString()
  return query ? `${normalizedPath}?${query}` : normalizedPath
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function installNetworkProfile(page: Page): NetworkProfile {
  const requestStarts = new Map<Request, number>()
  const failedRequests = new Set<Request>()
  const records: ApiRecord[] = []
  const transportFailures: string[] = []
  const responseTasks: Array<Promise<void>> = []

  const recordTransportFailure = (request: Request, reason: string) => {
    if (failedRequests.has(request)) return
    failedRequests.add(request)
    transportFailures.push(`${request.method()} ${normalizeApiUrl(request.url())}: ${reason}`)
  }

  page.on('request', (request) => {
    if (isApiRequest(request.url())) {
      requestStarts.set(request, Date.now())
    }
  })

  page.on('requestfailed', (request) => {
    if (!isApiRequest(request.url()) || !requestStarts.has(request)) return

    recordTransportFailure(request, request.failure()?.errorText ?? 'unknown failure')
    requestStarts.delete(request)
  })

  page.on('response', (response) => {
    if (!isApiRequest(response.url())) return

    const request = response.request()
    const startedAt = requestStarts.get(request)
    if (startedAt === undefined) return

    responseTasks.push((async () => {
      try {
        await response.finished()
        const headers = await response.allHeaders()

        records.push({
          method: request.method(),
          normalizedUrl: normalizeApiUrl(response.url()),
          status: response.status(),
          durationMs: Date.now() - startedAt,
          startedAt,
          requestId: headers['x-request-id'] ?? null,
          cacheStatus: headers['x-app-cache'] ?? null,
          databaseQueries: headers['x-app-db-queries'] ?? null,
          serverTiming: headers['server-timing'] ?? null,
        })
      } catch (error) {
        recordTransportFailure(request, errorMessage(error))
      } finally {
        requestStarts.delete(request)
      }
    })())
  })

  return {
    records,
    transportFailures,
    finish: async () => {
      await page.waitForTimeout(500)

      while (true) {
        const pending = responseTasks.splice(0, responseTasks.length)
        if (pending.length > 0) {
          await Promise.all(pending)
          continue
        }

        await page.waitForTimeout(100)
        if (responseTasks.length === 0) break
      }

      records.sort((left, right) => left.startedAt - right.startedAt)
    },
  }
}

function percentile(values: number[], quantile: number): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * quantile) - 1)
  return sorted[index] ?? 0
}

function findDuplicateGetBursts(records: ApiRecord[], windowMs: number): string[] {
  const lastStartedByUrl = new Map<string, number>()
  const duplicates: string[] = []

  for (const record of records) {
    if (record.method !== 'GET') continue

    const previousStart = lastStartedByUrl.get(record.normalizedUrl)
    if (previousStart !== undefined && record.startedAt - previousStart <= windowMs) {
      duplicates.push(`${record.normalizedUrl} repeated after ${record.startedAt - previousStart} ms`)
    }
    lastStartedByUrl.set(record.normalizedUrl, record.startedAt)
  }

  return duplicates
}

async function readAccessToken(page: Page): Promise<string> {
  await expect.poll(
    () => page.evaluate(() =>
      localStorage.getItem('auth_token')
      ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
      ?? null
    ),
    { timeout: 30_000 },
  ).not.toBeNull()

  const token = await page.evaluate(() =>
    localStorage.getItem('auth_token')
    ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
    ?? null
  )
  if (!token) throw new Error('The supplied production storage state did not yield an access token')
  return token
}

async function assertFullAccountShape(page: Page, token: string): Promise<{
  threadCount: number
  sessionCount: number
}> {
  const minThreads = numericEnvironmentValue('PROD_PROFILE_MIN_THREADS', 100)
  const minSessions = numericEnvironmentValue('PROD_PROFILE_MIN_SESSIONS', 25)
  const headers = { Authorization: `Bearer ${token}` }

  const [threadsResponse, sessionsResponse] = await Promise.all([
    page.request.get('/api/threads/?page_size=200', { headers }),
    page.request.get('/api/sessions/?page_size=200', { headers }),
  ])

  expect(threadsResponse.ok(), 'Full-account thread probe').toBeTruthy()
  expect(sessionsResponse.ok(), 'Full-account session probe').toBeTruthy()

  const threadsPayload = await threadsResponse.json() as ThreadListPayload | unknown[]
  const sessionsPayload = await sessionsResponse.json() as SessionListPayload | unknown[]
  const threads = Array.isArray(threadsPayload) ? threadsPayload : threadsPayload.threads ?? []
  const sessions = Array.isArray(sessionsPayload) ? sessionsPayload : sessionsPayload.sessions ?? []

  expect(
    threads.length,
    `Production profile must use a full account with at least ${minThreads} loaded threads`,
  ).toBeGreaterThanOrEqual(minThreads)
  expect(
    sessions.length,
    `Production profile must use a mature account with at least ${minSessions} loaded sessions`,
  ).toBeGreaterThanOrEqual(minSessions)

  return { threadCount: threads.length, sessionCount: sessions.length }
}

async function navigateSourcePages(page: Page): Promise<void> {
  await page.goto('/queue', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Read Queue' })).toBeVisible()

  await page.goto('/history', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'History', exact: true })).toBeVisible()

  await page.goto('/analytics', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator(SELECTORS.roll.mainDie).or(page.locator('[data-roll-pool]')).first()).toBeVisible()
}

async function rateOrRoll(page: Page, rating: string): Promise<void> {
  const ratingInput = page.locator(SELECTORS.rate.ratingInput)
  if (!(await ratingInput.isVisible())) {
    await page.locator(SELECTORS.roll.mainDie).click()
    await expect(ratingInput).toBeVisible()
  }

  await setRangeInput(page, SELECTORS.rate.ratingInput, rating)
  await submitRatingAndWaitForRateResponse(page, () => page.click(SELECTORS.rate.submitButton))
  await expect(page.locator(SELECTORS.roll.mainDie).or(page.locator('[data-roll-pool]')).first()).toBeVisible()
}

async function exerciseQueueAndIssueEditor(page: Page): Promise<void> {
  await page.goto('/queue', { waitUntil: 'domcontentloaded' })
  const firstThread = page.locator(SELECTORS.threadList.threadItem).first()
  await expect(firstThread).toBeVisible()

  const actionNames = ['Move to Front', 'Move to Back']
  for (const actionName of actionNames) {
    const actionButton = firstThread.locator('button[aria-label="Thread actions"]')
    if (await actionButton.isVisible()) {
      await actionButton.click()
      const menu = page.getByRole('menu')
      const action = menu.getByRole('menuitem', { name: actionName })
      if (await action.isVisible()) {
        await action.click()
      } else {
        await page.keyboard.press('Escape')
      }
    }
  }

  await firstThread.click()
  await page.waitForURL('**/thread/**')
  const editButton = page.getByRole('button', { name: 'Edit', exact: true })
  await expect(editButton).toBeVisible()
  await editButton.click()

  const editDialog = page.getByRole('dialog', { name: 'Edit Thread', exact: true })
  await expect(editDialog).toBeVisible()

  const showAll = editDialog.getByRole('button', { name: /^Show all \d+$/ })
  if (await showAll.isVisible()) await showAll.click()

  const issueToggle = editDialog.getByRole('button', { name: /^Toggle issue #/ }).first()
  if (await issueToggle.isVisible()) {
    await issueToggle.click()
    await issueToggle.click()
  }

  const cancel = editDialog.getByRole('button', { name: /Cancel|Close/ }).first()
  if (await cancel.isVisible()) await cancel.click()
}

test('full production account follows the HAR-derived browser workload', async ({ page }, testInfo) => {
  test.skip(
    testInfo.config.metadata.productionProfile !== true,
    'Run with playwright.prod-profile.config.ts and a production storage state.',
  )

  const maxApiDurationMs = numericEnvironmentValue('PROD_PROFILE_MAX_API_MS', 5_000)
  const minApiRequests = numericEnvironmentValue('PROD_PROFILE_MIN_API_REQUESTS', 40)
  const maxApiRequests = numericEnvironmentValue('PROD_PROFILE_MAX_API_REQUESTS', SOURCE_HAR.apiRequests)
  const duplicateWindowMs = numericEnvironmentValue('PROD_PROFILE_DUPLICATE_WINDOW_MS', 250)

  const profile = installNetworkProfile(page)

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#root')).toBeVisible()
  const token = await readAccessToken(page)
  const accountShape = await assertFullAccountShape(page, token)

  await navigateSourcePages(page)
  await rateOrRoll(page, '4.0')

  await page.locator(SELECTORS.roll.mainDie).click()
  await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible()
  const snoozeButton = page.locator(SELECTORS.rate.snoozeButton)
  if (await snoozeButton.isVisible()) await snoozeButton.click()

  await rateOrRoll(page, '3.5')
  await exerciseQueueAndIssueEditor(page)

  await page.goto('/analytics', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()
  await page.goto('/history', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'History', exact: true })).toBeVisible()

  await profile.finish()

  const failedResponses = profile.records.filter((record) => record.status >= 400)
  const slowResponses = profile.records.filter((record) => record.durationMs > maxApiDurationMs)
  const duplicateGetBursts = findDuplicateGetBursts(profile.records, duplicateWindowMs)
  const legacyDependencyRequests = profile.records.filter((record) =>
    record.normalizedUrl === '/api/v1/issues/:id/dependencies'
  )
  const batchDependencyRequests = profile.records.filter((record) =>
    record.normalizedUrl === '/api/v1/threads/:id/issue-dependencies'
  )
  const durations = profile.records.map((record) => record.durationMs)

  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl: testInfo.project.use.baseURL,
    sourceHar: SOURCE_HAR,
    accountShape,
    thresholds: {
      maxApiDurationMs,
      minApiRequests,
      maxApiRequests,
      duplicateWindowMs,
    },
    summary: {
      apiRequests: profile.records.length,
      sourceHarRequestRatio: profile.records.length / SOURCE_HAR.apiRequests,
      failedResponses: failedResponses.length,
      transportFailures: profile.transportFailures.length,
      slowResponses: slowResponses.length,
      duplicateGetBursts: duplicateGetBursts.length,
      medianMs: percentile(durations, 0.5),
      p95Ms: percentile(durations, 0.95),
      maxMs: Math.max(0, ...durations),
      cacheStatuses: profile.records.reduce<Record<string, number>>((counts, record) => {
        const status = record.cacheStatus ?? 'not-reported'
        counts[status] = (counts[status] ?? 0) + 1
        return counts
      }, {}),
    },
    duplicateGetBursts,
    transportFailures: profile.transportFailures,
    records: profile.records,
  }

  await testInfo.attach('production-profile.json', {
    body: Buffer.from(JSON.stringify(report, null, 2)),
    contentType: 'application/json',
  })

  expect(profile.transportFailures, 'Transport failures').toEqual([])
  expect(failedResponses, 'API responses with status >= 400').toEqual([])
  expect(slowResponses, `API responses slower than ${maxApiDurationMs} ms`).toEqual([])
  expect(profile.records.length, 'Minimum full-account workload').toBeGreaterThanOrEqual(minApiRequests)
  expect(profile.records.length, 'Maximum HAR-derived request budget').toBeLessThanOrEqual(maxApiRequests)
  expect(legacyDependencyRequests, 'Legacy one-request-per-issue dependency calls').toEqual([])
  expect(batchDependencyRequests.length, 'Thread dependency batch requests').toBeGreaterThanOrEqual(1)
  expect(duplicateGetBursts, 'Duplicate GET requests inside the burst window').toEqual([])
})
