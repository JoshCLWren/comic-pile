/**
 * Reading-mode acceptance in the shipped build (issue #1734/#1945).
 *
 * The quiz launcher is compile-time feature-gated off in production; the
 * original acceptance block asserted an always-available quiz flow that the
 * shipped build deliberately does not expose. Those assertions were retired
 * with the superseded UI. The quiz component's two-question flow is covered by
 * `src/unit/ReadingModeQuiz.test.tsx`; this browser spec now pins the live v2
 * reading-mode persistence contract and the gated Roll surface instead.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { getAuthToken, gotoRollPage, waitForRollPageReady } from './helpers'

let quizEnabled = false

test.beforeAll(async ({ browser }) => {
  const probe = await browser.newPage()
  await probe.goto('/')
  quizEnabled = await probe.evaluate(
    // SAFETY: the test toggles only the readingModeQuiz flag the bootstrap reader reads
    () => (window as { __COMIC_PILE_FEATURES__?: { readingModeQuiz?: boolean } })
      .__COMIC_PILE_FEATURES__?.readingModeQuiz === true,
  )
  await probe.close()
})

test.describe('reading-mode quiz acceptance', () => {
  test('the shipped build keeps the quiz feature flag off', async () => {
    // #1945: the quiz persists its result but production Roll does not consume
    // it yet, so the launcher is gated off by default.
    expect(quizEnabled).toBe(false)
  })

  test('a manual reading mode persists through the Rust v2 endpoint', async ({
    authenticatedPage,
  }) => {
    const page: Page = authenticatedPage
    const token = await getAuthToken(page)
    const seed = await page.request.put('/api/v2/reading-mode', {
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
      data: { bandwidth: 'light', intent: 'momentum', source: 'manual' },
    })
    expect(seed.ok(), `reading-mode PUT failed: ${seed.status()}`).toBe(true)

    const response = await page.request.get('/api/v2/reading-mode', {
      headers: { Accept: 'application/json' },
    })
    expect(response.ok()).toBe(true)
    // SAFETY: the test reads only the mode fields it asserts
    const body = (await response.json()) as {
      bandwidth: string
      intent: string
      source: string
    }
    expect(body.bandwidth).toBe('light')
    expect(body.intent).toBe('momentum')
    expect(body.source).toBe('manual')
  })

  test('the Roll surface never auto-opens the quiz', async ({ authenticatedPage }) => {
    const page: Page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await expect(page.getByTestId('open-reading-mode-quiz')).toBeHidden()
    await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()
  })
})

test.describe('reading-mode quiz gating (issue #1945)', () => {
  test('hides the launcher and suggestion prompts from the normal production Roll surface', async ({
    authenticatedPage,
  }) => {
    expect(quizEnabled).toBe(false)
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await expect(page.getByTestId('open-reading-mode-quiz')).toBeHidden()
    await expect(page.getByTestId('reading-mode-suggestion')).toBeHidden()
  })
})
