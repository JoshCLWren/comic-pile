/**
 * Issue #3144 acceptance: the rating card must not advertise a die-ladder move
 * that manual die mode suppresses.
 *
 * Repro from the report: pin a manual die (the header ladder segment), roll,
 * and rate. The card used to keep showing `d20 -> d12` even though the pinned
 * die never changes, so the readout promised a move the session suppresses.
 *
 * These browser checks drive the real header control rather than seeding the
 * API, because that is the reported path and because it also pins the cache
 * behavior the fix depends on: after a die-mode change the roll bootstrap has
 * to be refreshed, otherwise the card would still read the pre-change mode for
 * the rest of the session.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForRollPageReady } from './helpers'

const DESKTOP_VIEWPORT = { width: 1280, height: 800 }

async function pinDieFromHeader(page: Page, die: number): Promise<void> {
  const autoSegment = page.getByRole('button', { name: 'Auto', exact: true })
  await expect(autoSegment).toHaveAttribute('aria-pressed', 'true')

  await page.getByRole('button', { name: `d${die}`, exact: true }).click()

  // The die-mode mutation refreshes the roll bootstrap, so the ladder segment
  // stops reading as automatic without a full page reload.
  await expect(autoSegment).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('button', { name: `d${die}`, exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
}

async function returnToAutomaticMode(page: Page): Promise<void> {
  const autoSegment = page.getByRole('button', { name: 'Auto', exact: true })
  await autoSegment.click()
  await expect(autoSegment).toHaveAttribute('aria-pressed', 'true')
}

async function openRatingView(page: Page, title: string): Promise<void> {
  await page.locator('#main-die-3d').click()
  await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
  await page.getByText(title).first().click()
  await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
}

test.describe('Decision card die readout with a pinned die (#3144)', () => {
  test('a pinned die replaces the ladder move the card would otherwise promise', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const threadTitle = 'Manual Die Readout Thread'
    await createThread(page, {
      title: threadTitle,
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })

    await page.setViewportSize(DESKTOP_VIEWPORT)
    await gotoRollPage(page)
    await waitForRollPageReady(page)
    await pinDieFromHeader(page, 20)

    await openRatingView(page, threadTitle)

    const card = page.getByTestId('decision-card')
    await expect(card).toContainText('Manual mode is active at d20')
    await expect(card).not.toContainText('→')
  })

  test('automatic mode still reports the ladder move', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const threadTitle = 'Automatic Die Readout Thread'
    await createThread(page, {
      title: threadTitle,
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })

    await page.setViewportSize(DESKTOP_VIEWPORT)
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await openRatingView(page, threadTitle)

    const card = page.getByTestId('decision-card')
    await expect(card).toContainText('d6 → d8')
    await expect(card).not.toContainText('Manual mode is active')
  })

  test('leaving manual mode restores the ladder move readout on the next roll', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const threadTitle = 'Die Mode Switch Thread'
    await createThread(page, {
      title: threadTitle,
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })

    await page.setViewportSize(DESKTOP_VIEWPORT)
    await gotoRollPage(page)
    await waitForRollPageReady(page)
    await pinDieFromHeader(page, 20)

    await openRatingView(page, threadTitle)
    await expect(page.getByTestId('decision-card')).toContainText('Manual mode is active at d20')

    await page.getByTestId('cancel-roll').click()
    await expect(page.locator('#main-die-3d')).toBeVisible({ timeout: 15000 })
    await returnToAutomaticMode(page)

    await openRatingView(page, threadTitle)
    await expect(page.getByTestId('decision-card')).toContainText('d6 → d8')
  })
})