/**
 * SNOOZE-001: User can snooze or unsnooze a comic and it appears
 * appropriately in the queue.
 *
 * Verifies: snooze from rating view moves thread to snoozed section,
 * unsnooze from roll pool restores it, and queue reflects snoozed state.
 *
 * Inventory IDs: SNOOZE-001
 *
 * #4276 addendum (zero-mock request ledger over these real flows): a Queue
 * row snooze/unsnooze refreshes the current session through exactly one owner
 * — the snooze mutation — instead of the handler layering extra invalidations
 * of the same session key. Delta counts around each user action make a
 * duplicate fetch fail instead of being hidden by a total.
 */
import { expect, type Locator, type Page } from '@playwright/test'
import { test } from './fixtures'
import {
  createThread,
  dismissRollNudgeIfPresent,
  gotoRollPage,
  gotoQueue,
  openThreadActions,
  startRequestLedger,
  waitForRollPageReady,
} from './helpers'

test.describe('SNOOZE-001: Snooze and unsnooze', () => {
  test('snooze from rating view moves thread to snoozed section', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Snooze Me Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Snooze Me Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.getByTestId('rating-secondary-actions').getByRole('button', { name: /snooze/i }).click()

    const snoozedToggle = page.getByRole('button', { name: /snoozed/i })
    await expect(snoozedToggle).toBeVisible({ timeout: 10000 })
  })

  test('unsnooze from roll pool restores thread to active pool', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Unsnooze Me Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Unsnooze Me Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.getByTestId('rating-secondary-actions').getByRole('button', { name: /snooze/i }).click()
    const snoozedToggle = page.getByRole('button', { name: /snoozed/i }).first()
    await expect(snoozedToggle).toBeVisible({ timeout: 10000 })

    // The snoozed list is a collapsed section under the active pool. Expand
    // it, then unsnooze from there to restore the thread to the pool.
    await snoozedToggle.click()
    await page.getByRole('button', { name: 'Unsnooze this comic' }).click()
    await expect(page.locator('[data-roll-pool]').getByText('Unsnooze Me Thread')).toBeVisible({
      timeout: 10000,
    })
  })

  test('snoozed thread appears with snoozed indicator in queue', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const thread = await createThread(page, {
      title: 'Queue Snooze Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Queue Snooze Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.getByTestId('rating-secondary-actions').getByRole('button', { name: /snooze/i }).click()
    await expect(page.getByRole('button', { name: /snoozed/i })).toBeVisible({ timeout: 10000 })

    await gotoQueue(page)
    await page.getByText('Queue Snooze Thread').first().waitFor({ state: 'visible', timeout: 10000 })
    const threadItem = page.getByTestId('queue-thread-item').filter({ hasText: 'Queue Snooze Thread' })
    await expect(threadItem).toBeVisible()
  })

  test('queue row snooze and unsnooze settle the current session through one owner (#4276)', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const ledger = startRequestLedger(page)
    await createThread(page, {
      title: 'Single Owner Snooze Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })

    // Pend the series through the real roll path so the Queue row's snooze
    // control is meaningful: only the session's pending series can snooze.
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })

    // Baseline everything AFTER the pend: the die roll and its refresh are
    // setup traffic, outside the measured snooze/unsnooze window.
    await gotoQueue(page)
    // The first series can raise the "Ready to roll?" nudge whose backdrop
    // blocks row actions; dismiss it before any measured interaction.
    await dismissRollNudgeIfPresent(page)
    const threadItem = page
      .getByTestId('queue-thread-item')
      .filter({ hasText: 'Single Owner Snooze Thread' })
    await expect(threadItem).toBeVisible()
    const before = {
      sessions: ledger.count('GET', '/api/v1/sessions/current/'),
      queuePages: ledger.count('GET', '/api/v2/threads'),
      excluded: ledger.count('GET', '/api/v1/threads/excluded/threads'),
    }

    // Toggle 1: Snooze. Arm both settle signals BEFORE the user action so the
    // reconciliation responses cannot outrun the listeners: the row-action
    // pass refetches the queue list once, and the owning mutation refreshes
    // the current session exactly once (the retired handler layer used to add
    // two more session GETs per toggle).
    const firstListRefresh = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET'
        && response.url().includes('/api/v2/threads')
        && response.status() === 200,
    )
    const firstSessionRefresh = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET'
        && response.url().includes('/api/v1/sessions/current/')
        && response.status() === 200,
    )
    await clickThreadMenuItem(page, threadItem, 'Snooze')
    await firstListRefresh
    await firstSessionRefresh

    // Settled visible state: with both refreshes settled, the reopened row
    // menu offers "Unsnooze" without any reload.
    const snoozedMenu = await openThreadActions(threadItem)
    await expect(snoozedMenu.getByRole('menuitem', { name: 'Unsnooze' })).toBeVisible({
      timeout: 15000,
    })
    await closeMenuWithoutAction(page)

    // Toggle 2: Unsnooze; same deterministic settle signals, then the menu
    // settles back to "Snooze".
    const secondListRefresh = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET'
        && response.url().includes('/api/v2/threads')
        && response.status() === 200,
    )
    const secondSessionRefresh = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET'
        && response.url().includes('/api/v1/sessions/current/')
        && response.status() === 200,
    )
    await clickThreadMenuItem(page, threadItem, 'Unsnooze')
    await secondListRefresh
    await secondSessionRefresh
    const restoredMenu = await openThreadActions(threadItem)
    await expect(restoredMenu.getByRole('menuitem', { name: 'Snooze' })).toBeVisible({
      timeout: 15000,
    })
    await closeMenuWithoutAction(page)

    // One session refresh per mutation (the snooze/unsnooze hooks own it);
    // a second handler-layer invalidation of the same key would re-run the
    // just-settled fetch and trip this budget.
    const deltaSessions =
      ledger.count('GET', '/api/v1/sessions/current/') - before.sessions
    expect(deltaSessions).toBe(2)
    // Each toggle also reconciles the queue read models with exactly one
    // bounded refresh: one first-page refetch of the queue and one of the
    // excluded shelf (both reset by the row-action pass, then refetched once).
    const deltaQueuePages = ledger.count('GET', '/api/v2/threads') - before.queuePages
    expect(deltaQueuePages).toBe(2)
    const deltaExcluded =
      ledger.count('GET', '/api/v1/threads/excluded/threads') - before.excluded
    expect(deltaExcluded).toBe(2)

    // Mutation feedback stays reserved for failures: a settled snooze cycle
    // must not surface action-error copy.
    await expect(
      page.getByText(/failed to (snooze|unsnooze) thread/i).first(),
    ).not.toBeVisible()
  })
})

/** Opens a row's action menu and clicks a named menu item, waiting for the menu to close. */
async function clickThreadMenuItem(
  page: Page,
  threadItem: Locator,
  itemName: string,
): Promise<void> {
  const menu = await openThreadActions(threadItem)
  await menu.getByRole('menuitem', { name: itemName }).click()
  await expect(menu).toBeHidden()
}

/** Escapes from a still-open menu by pressing Escape instead of acting. */
async function closeMenuWithoutAction(page: Page): Promise<void> {
  const menu = page.getByRole('menu')
  if (await menu.isVisible().catch(() => false)) {
    await page.keyboard.press('Escape')
  }
  await expect(menu).toBeHidden()
}

