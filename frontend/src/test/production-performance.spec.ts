import { mkdir, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { expect, test, type Page, type Response } from '@playwright/test'

type PerformanceSample = {
  capturedAt: string
  deploymentId: string
  runAttempt: string
  classification: 'cold' | 'warm' | 'unknown'
  documentResponseMs: number
  shellReadyMs: number
  firstApiResponseMs: number
  queueReadyMs: number
  firstApiPath: string | null
  firstApiStatus: number | null
  serverTiming: string | null
}

type TimedResponse = {
  response: Response
  arrivedAtMs: number
}

const outputPath = process.env.PROD_PERFORMANCE_OUTPUT ?? '../test-results/production-performance.json'

function elapsedSince(startedAt: number): number {
  return Math.round(performance.now() - startedAt)
}

function classifyInvocation(serverTiming: string | null): PerformanceSample['classification'] {
  if (!serverTiming) return 'unknown'
  const normalized = serverTiming.toLowerCase()
  if (normalized.includes('cold')) return 'cold'
  if (normalized.includes('warm')) return 'warm'
  return 'unknown'
}

async function waitForFirstApiResponse(page: Page, startedAt: number): Promise<TimedResponse> {
  const response = await page.waitForResponse((candidate) => {
    const path = new URL(candidate.url()).pathname
    return path.startsWith('/api/') && candidate.request().resourceType() !== 'document'
  })
  return { response, arrivedAtMs: elapsedSince(startedAt) }
}

test('records production startup and queue milestones', async ({ page }, testInfo) => {
  const startedAt = performance.now()
  const firstApiResponsePromise = waitForFirstApiResponse(page, startedAt)

  const documentResponse = await page.goto('/', { waitUntil: 'domcontentloaded' })
  expect(documentResponse, 'Initial document response').not.toBeNull()

  const navigation = await page.evaluate(() => {
    const [entry] = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[]
    return entry
      ? { responseStart: entry.responseStart, startTime: entry.startTime }
      : { responseStart: 0, startTime: 0 }
  })
  const documentResponseMs = Math.round(navigation.responseStart - navigation.startTime)

  await expect(page.locator('[data-app-shell-ready="true"]')).toBeVisible({ timeout: 60_000 })
  const shellReadyMs = elapsedSince(startedAt)

  const { response: firstApiResponse, arrivedAtMs: firstApiResponseMs } =
    await firstApiResponsePromise
  const firstApiHeaders = await firstApiResponse.allHeaders()
  const serverTiming = firstApiHeaders['server-timing'] ?? null

  await page.goto('/queue', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Read Queue' })).toBeVisible({ timeout: 60_000 })
  const queueReadyMs = elapsedSince(startedAt)

  const sample: PerformanceSample = {
    capturedAt: new Date().toISOString(),
    deploymentId: process.env.PROD_DEPLOYMENT_ID ?? process.env.GITHUB_SHA ?? 'unknown',
    runAttempt: process.env.GITHUB_RUN_ATTEMPT ?? 'local',
    classification: classifyInvocation(serverTiming),
    documentResponseMs,
    shellReadyMs,
    firstApiResponseMs,
    queueReadyMs,
    firstApiPath: new URL(firstApiResponse.url()).pathname,
    firstApiStatus: firstApiResponse.status(),
    serverTiming,
  }

  await mkdir(dirname(outputPath), { recursive: true })
  await writeFile(outputPath, `${JSON.stringify(sample, null, 2)}\n`, 'utf8')
  await testInfo.attach('production-performance.json', {
    body: Buffer.from(JSON.stringify(sample, null, 2)),
    contentType: 'application/json',
  })

  expect(sample.documentResponseMs).toBeGreaterThanOrEqual(0)
  expect(sample.firstApiResponseMs).toBeGreaterThanOrEqual(0)
  expect(sample.firstApiStatus).toBeLessThan(400)
})
