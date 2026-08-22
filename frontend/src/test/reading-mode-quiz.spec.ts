/**
 * Phase 6 acceptance: the complete two-question reading-mode quiz flow.
 *
 * Covers manual reachability, the two-selection flow, backend recording with
 * source `quiz`, and that cancel/dismiss leaves the prior mode intact.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { gotoRollPage, waitForRollPageReady } from './helpers'

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
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await expect(page.getByTestId('open-reading-mode-quiz')).toBeVisible()
    await expect(page.getByTestId('reading-mode-quiz')).toBeHidden()
  })
})
