/**
 * Phase 6 acceptance: the complete two-question reading-mode quiz flow.
 *
 * The launcher is feature-gated (issue #1945): the quiz persists its result and
 * the weighting machinery exists, but the production Roll path does not yet
 * consume the quiz-selected mode, so the launcher is hidden by default. These
 * acceptance tests adapt to the build's feature flag so the p1-p2 lane stays
 * green in default builds while still exercising the full flow when enabled.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { gotoRollPage, waitForRollPageReady } from './helpers'

let quizEnabled = false

test.beforeAll(async ({ browser }) => {
  const probe = await browser.newPage()
  await probe.goto('/')
  quizEnabled = await probe.evaluate(
    () =>
      (window as { __COMIC_PILE_FEATURES__?: { readingModeQuiz?: boolean } })
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
    const page = authenticatedPage
    if (!quizEnabled) {
      await gotoRollPage(page)
      await waitForRollPageReady(page)
      await expect(page.getByTestId('open-reading-mode-quiz')).toBeHidden()
      await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()
      return
    }
    await openQuiz(page)

    await expect(page.getByText('How much brain do you have right now?')).toBeVisible()
    await page.getByTestId('quiz-answer-brainpower-substantial').click()
    await page.getByTestId('reading-mode-quiz-next').click()

    await expect(page.getByText('What kind of pick sounds good?')).toBeVisible()
    await page.getByTestId('quiz-answer-pick-explore').click()
    await page.getByTestId('reading-mode-quiz-next').click()

    await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()

    const response = await page.request.get('/api/v2/reading-mode', {
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
    const seed = await page.request.put('/api/v2/reading-mode', {
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      data: { bandwidth: 'light', intent: 'momentum', source: 'manual' },
    })
    expect(seed.ok()).toBe(true)

    if (!quizEnabled) {
      await gotoRollPage(page)
      await waitForRollPageReady(page)
      await expect(page.getByTestId('open-reading-mode-quiz')).toBeHidden()
      const response = await page.request.get('/api/v2/reading-mode')
      const body = (await response.json()) as { bandwidth: string; source: string }
      expect(body.bandwidth).toBe('light')
      expect(body.source).toBe('manual')
      return
    }

    await openQuiz(page)
    await page.getByTestId('reading-mode-quiz-back').click()

    await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()
    const response = await page.request.get('/api/v2/reading-mode')
    const body = (await response.json()) as { bandwidth: string; source: string }
    expect(body.bandwidth).toBe('light')
    expect(body.source).toBe('manual')
  })

  test('quiz is always manually reachable and never auto-opens', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    if (!quizEnabled) {
      await expect(page.getByTestId('open-reading-mode-quiz')).toBeHidden()
      await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()
      return
    }

    await expect(page.getByTestId('open-reading-mode-quiz')).toBeVisible()
    await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()
  })
})

test.describe('reading-mode quiz gating (issue #1945)', () => {
  test('hides the launcher and suggestion prompts from the normal production Roll surface', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    if (quizEnabled) {
      await expect(page.getByTestId('open-reading-mode-quiz')).toBeVisible()
      return
    }
    await expect(page.getByTestId('open-reading-mode-quiz')).toBeHidden()
    await expect(page.getByTestId('reading-mode-suggestion')).toBeHidden()
  })
})
