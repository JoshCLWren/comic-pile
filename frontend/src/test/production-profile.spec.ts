import { expect, test, type APIResponse, type Page, type Request } from '@playwright/test'
import {
  SELECTORS,
  createThread,
  generateTestUser,
  setRangeInput,
  submitRatingAndWaitForRateResponse,
} from './helpers'

type ApiRecord = {
  method: string
  path: string
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

type RegistrationResponse = {
  access_token?: unknown
}

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
    transportFailures.push(
      `${request.method()} ${normalizeApiUrl(request.url())}: ${reason}`,
    )
  }

  page.on('request', (request) => {
    if (isApiRequest(request.url())) {
      requestStarts.set(request, Date.now())
    }
  })

  page.on('requestfailed', (request) => {
    if (!isApiRequest(request.url()) || !requestStarts.has(request)) return

    recordTransportFailure(
      request,
      request.failure()?.errorText ?? 'unknown failure',
    )
    requestStarts.delete(request)
  })

  page.on('response', (response) => {
    if (!isApiRequest(response.url())) return

    const request = response.request()
    const startedAt = requestStarts.get(request)

    // Ignore responses for requests that began before the profile was installed.
    // Falling back to Date.now() would understate their duration, especially for redirects.
    if (startedAt === undefined) return

    responseTasks.push((async () => {
      try {
        await response.finished()
        const headers = await response.allHeaders()
        const url = new URL(response.url())

        records.push({
          method: request.method(),
          path: url.pathname,
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

function percentile(values: number[], quantile: number): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * quantile) - 1)
  return sorted[index] ?? 0
}

async function assertProductionHealth(response: APIResponse, durationMs: number): Promise<void> {
  if (response.ok()) return

  const headers = response.headers()
  const body = (await response.text()).slice(0, 2_000)
  const vercelHeaders = Object.fromEntries(
    Object.entries(headers).filter(([name]) =>
      ['server', 'date', 'x-vercel-id', 'x-vercel-cache'].includes(name),
    ),
  )

  throw new Error(
    `Production health check failed after ${durationMs} ms: ${response.status()} ${response.statusText()}\n` +
      `URL: ${response.url()}\n` +
      `Vercel headers: ${JSON.stringify(vercelHeaders)}\n` +
      `Response body: ${body || '(empty)'}`,
  )
}

async function setupProductionProfileUser(page: Page): Promise<void> {
  const user = generateTestUser()
  const response = await page.request.post('/api/auth/register', {
    data: {
      username: user.username,
      email: user.email,
      password: user.password,
    },
    timeout: 30000,
  })
  const responseText = await response.text()

  if (!response.ok()) {
    throw new Error(
      `Production profile registration failed: ${response.status()} ${response.statusText()} ${responseText.slice(0, 500)}`,
    )
  }

  let payload: RegistrationResponse
  try {
    payload = JSON.parse(responseText) as RegistrationResponse
  } catch {
    throw new Error(`Production profile registration returned invalid JSON: ${responseText.slice(0, 500)}`)
  }

  if (typeof payload.access_token !== 'string' || payload.access_token.length === 0) {
    throw new Error(`Production profile registration returned no access token: ${responseText.slice(0, 500)}`)
  }

  await page.addInitScript((accessToken: string) => {
    localStorage.setItem('auth_token', accessToken)
    ;(window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN = accessToken
  }, payload.access_token)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
}

test('HAR-derived production journey stays within request budgets', async ({ page }, testInfo) => {
  test.skip(
    testInfo.config.metadata.productionProfile !== true,
    'Run with playwright.prod-profile.config.ts against an explicit production URL.',
  )

  const maxApiDurationMs = numericEnvironmentValue('PROD_PROFILE_MAX_API_MS', 5000)
  const maxApiRequests = numericEnvironmentValue('PROD_PROFILE_MAX_API_REQUESTS', 60)
  const duplicateWindowMs = numericEnvironmentValue('PROD_PROFILE_DUPLICATE_WINDOW_MS', 250)

  const healthStartedAt = Date.now()
  const health = await page.request.get('/health')
  await assertProductionHealth(health, Date.now() - healthStartedAt)

  await setupProductionProfileUser(page)
  const profileTitle = `Production Profile ${Date.now()}`
  await createThread(page, {
    title: profileTitle,
    format: 'Comics',
    issues_remaining: 40,
    issue_range: '1-40',
  })
  await createThread(page, {
    title: `${profileTitle} Side A`,
    format: 'Manga',
    issues_remaining: 4,
    issue_range: '1-4',
  })
  await createThread(page, {
    title: `${profileTitle} Side B`,
    format: 'Novel',
    issues_remaining: 3,
    issue_range: '1-3',
  })

  const profile = installNetworkProfile(page)

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible()
  await page.click(SELECTORS.roll.mainDie)
  await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible()
  await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0')
  await submitRatingAndWaitForRateResponse(page, () => page.click(SELECTORS.rate.submitButton))
  await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible()
  await page.waitForLoadState('networkidle')

  await page.goto('/queue', { waitUntil: 'domcontentloaded' })
  const profileTitleText = page.getByText(profileTitle, { exact: true }).first()
  await expect(profileTitleText).toBeVisible()
  const threadCard = profileTitleText.locator(
    'xpath=ancestor::*[@data-testid="queue-thread-item"]',
  )
  await expect(threadCard).toHaveCount(1)
  await threadCard.click()
  await page.waitForURL('**/thread/**')
  const threadTitle = page.getByRole('heading', { name: profileTitle, exact: true })
  await expect(threadTitle).toBeVisible()

  const threadHeader = threadTitle.locator('xpath=ancestor::header')
  await threadHeader.getByRole('button', { name: 'Edit', exact: true }).click()
  const editDialog = page.getByRole('dialog', { name: 'Edit Thread', exact: true })
  await expect(editDialog).toBeVisible()
  const showAllIssues = editDialog.getByRole('button', { name: 'Show all 40', exact: true })
  await expect(showAllIssues).toBeVisible()
  await showAllIssues.click()
  const issueToggles = editDialog.getByRole('button', { name: /^Toggle issue #/ })
  await expect(issueToggles).toHaveCount(40)
  const firstIssueToggle = issueToggles.first()
  const toggleIssueResponse = page.waitForResponse((response) => {
    const path = new URL(response.url()).pathname
    return (
      /:(markRead|markUnread)$/.test(path)
      && response.request().method() === 'POST'
    )
  })
  await firstIssueToggle.click()
  expect((await toggleIssueResponse).ok()).toBeTruthy()
  await page.waitForLoadState('networkidle')

  await page.goto('/history', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'History', exact: true })).toBeVisible()
  await page.waitForLoadState('networkidle')
  await page.goto('/analytics', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()
  await page.waitForLoadState('networkidle')

  await profile.finish()

  const failedResponses = profile.records.filter((record) => record.status >= 400)
  const slowResponses = profile.records.filter((record) => record.durationMs > maxApiDurationMs)
  const legacyDependencyRequests = profile.records.filter((record) =>
    /^\/api\/v1\/issues\/:id\/dependencies$/.test(record.normalizedUrl)
  )
  const batchDependencyRequests = profile.records.filter((record) =>
    record.normalizedUrl === '/api/v1/threads/:id/issue-dependencies'
  )
  const duplicateGetBursts = findDuplicateGetBursts(profile.records, duplicateWindowMs)
  const durations = profile.records.map((record) => record.durationMs)

  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl: testInfo.project.use.baseURL,
    thresholds: {
      maxApiDurationMs,
      maxApiRequests,
      duplicateWindowMs,
    },
    summary: {
      apiRequests: profile.records.length,
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
  expect(
    slowResponses,
    `API responses slower than ${maxApiDurationMs} ms`,
  ).toEqual([])
  expect(profile.records.length, 'Total API request budget').toBeLessThanOrEqual(maxApiRequests)
  expect(legacyDependencyRequests, 'Legacy one-request-per-issue dependency calls').toEqual([])
  expect(batchDependencyRequests, 'Expected one dependency batch request').toHaveLength(1)
  expect(duplicateGetBursts, 'Duplicate GET requests inside the burst window').toEqual([])
})
