/**
 * Phase 6 acceptance: the complete two-question reading-mode quiz flow.
 *
 * Covers manual reachability, the two-selection flow, backend recording with
 * source `quiz`, and that cancel/dismiss leaves the prior mode intact.
 *
 * The launcher is feature-gated (issue #1945): the quiz persists its result and
 * the weighting machinery exists, but the production Roll path does not yet
 * consume the quiz-selected mode, so the launcher is hidden by default. These
 * acceptance tests therefore run only when `readingModeQuiz` is enabled; a
 * separate gating suite asserts the launcher is absent in the default build.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { gotoRollPage, waitForRollPageReady } from './helpers'

let quizEnabled = false

test.beforeAll(async ({ browser }) => {
  const probe = await browser.newPage()
  await probe.goto('/')
  quizEnabled = await probe.evaluate(
    () => (window as unknown as { __COMIC_PILE_FEATURES__?: { readingModeQuiz?: boolean } })
      .__COMIC_PILE_FEATURES__?.readingModeQuiz === true,
  )
  await probe.close()
})

async function openQuiz(page: Page): Promise<void> {
  await gotoRollPage(page)
  await waitForRollPageReady(page)
  await page.getByTestId('open-reading-mode-quiz').click()
  await expect(page.getByTestId('reading-mode-quiz')).toBeVisible()
}

test.describe('reading-mode quiz acceptance', () => {
  test('completes the two-question flow and records source quiz', async ({
    authenticatedPage,
  }) => {
    test.skip(!quizEnabled, 'reading-mode quiz launcher is feature-gated')
    const page = authenticatedPage
    await openQuiz(page)

    await expect(page.getByText('How much brain do you have right now?')).toBeVisible()
    await page.getByTestId('quiz-answer-brainpower-substantial').click()
    await page.getByTestId('reading-mode-quiz-next').click()

    await expect(page.getByText('What kind of pick sounds good?')).toBeVisible()
    await page.getByTestId('quiz-answer-pick-explore').click()
    await page.getByTestId('reading-mode-quiz-next').click()

    // Modal closes after submission.
    await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()

    // Backend recorded the mode with source `quiz`.
    const response = await page.request.get('/api/v1/reading-mode', {
      headers: { Accept: 'application/json' },
    })
    expect(response.ok()).toBe(true)
    const body = (await response.json()) as {
      bandwidth: string
      intent: string
      source: string
    }
    expect(body.bandwidth).toBe('deep')
    expect(body.intent).toBe('explore')
    expect(body.source).toBe('quiz')
  })

  test('cancel on the first question leaves the prior mode intact', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    // Seed a manual mode first via the API.
    const seed = await page.request.post('/api/v1/reading-mode', {
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      data: { bandwidth: 'light', intent: 'momentum', source: 'manual' },
    })
    expect(seed.ok()).toBe(true)

    test.skip(!quizEnabled, 'reading-mode quiz launcher is feature-gated')
    await openQuiz(page)
    await page.getByTestId('reading-mode-quiz-back').click()

    // Modal closed without submitting; prior manual mode is unchanged.
    await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()
    const response = await page.request.get('/api/v1/reading-mode')
    const body = (await response.json()) as { bandwidth: string; source: string }
    expect(body.bandwidth).toBe('light')
    expect(body.source).toBe('manual')
  })

  test('quiz is always manually reachable and never auto-opens', async ({
    authenticatedPage,
  }) => {
    test.skip(!quizEnabled, 'reading-mode quiz launcher is feature-gated')
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await expect(page.getByTestId('open-reading-mode-quiz')).toBeVisible()
    await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()
  })
})

test.describe('reading-mode quiz gating (issue #1945)', () => {
  test('hides the launcher and suggestion prompts from the normal production Roll surface', async ({
    authenticatedPage,
  }) => {
    test.skip(quizEnabled, 'gating only applies when the launcher feature is disabled')
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await expect(page.getByTestId('open-reading-mode-quiz')).toBeHidden()
    await expect(page.getByTestId('reading-mode-suggestion')).toBeHidden()
  })
})
