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
  await page.getByRole('button', { name: `d${die}`, exact: true }).click()

  // The die-command mutation refreshes the roll bootstrap, so the chosen die
  // reads as the selected ladder segment without a full page reload. There is
  // no Auto/Manual segment any more (#4353): the die is event-derived.
  await expect(page.getByRole('button', { name: `d${die}`, exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
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

    // #4279 regression: the manual choice is one die event, so it survives
    // navigating away and back without any sticky session mode.
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await gotoRollPage(page)
    await waitForRollPageReady(page)
    await expect(page.getByRole('button', { name: 'd20', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    )

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
})
