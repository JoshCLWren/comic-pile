/**
 * ROLL-001: User can roll a comic and see the result.
 *
 * Verifies that the dice roll mechanism works end-to-end: the die is visible,
 * clicking it triggers a roll, rolled threads appear in the pool, and clicking
 * a thread enters the rating view.
 *
 * Inventory IDs: ROLL-001
 *
 * #4276 addendum (zero-mock request ledger over these real flows): a Roll
 * move-front/shuffle click settles the retained bootstrap with exactly one
 * authoritative refresh — the move/shuffle mutation's queue-movement
 * invalidation — instead of an invalidation refetch followed by an explicit
 * duplicate `refetchBootstrap()`. Delta counts around the user action make
 * that duplicate fail, and the settled pool state (new order / closed dialog)
 * is the visible acceptance.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import {
  createThread,
  gotoRollPage,
  startRequestLedger,
  waitForRollPageReady,
} from './helpers'

test.describe('ROLL-001: Roll selection', () => {
  test('die is visible and clickable on the home page', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Roll Die Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const die = page.locator('#main-die-3d')
    await expect(die).toBeVisible()
  })

  test('clicking the die triggers a roll and shows rolled threads', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Rolled Thread',
      format: 'Issue',
      issues_remaining: 5,
      total_issues: 5,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()

    const pool = page.locator('[data-roll-pool]')
    await expect(pool).toBeVisible({ timeout: 15000 })
    await expect(pool.getByText('Rolled Thread')).toBeVisible()
  })

  test('clicking a rolled thread enters the rating view', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Rating Target Thread',
      format: 'Comic',
      issues_remaining: 4,
      total_issues: 4,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })

    await page.getByText('Rating Target Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
  })

  test('die selector allows choosing different die sizes', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Die Selector Thread',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const dieSelector = page.locator('#die-selector')
    await expect(dieSelector).toBeVisible()

    const d20Button = page.getByRole('button', { name: 'd20', exact: true })
    if (await d20Button.isVisible()) {
      await d20Button.click()
      await expect(page.locator('#header-die-label')).toHaveText('d20')
    }
  })

  test('empty queue shows appropriate state instead of crashing', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const emptyState = page.getByText(/no comics|empty|nothing/i)
    const die = page.locator('#main-die-3d')
    const pool = page.locator('[data-roll-pool]')

    const hasEmpty = await emptyState.isVisible().catch(() => false)
    const hasDie = await die.isVisible().catch(() => false)
    const hasPool = await pool.isVisible().catch(() => false)

    expect(hasEmpty || hasDie || hasPool).toBe(true)
  })

  test('move to front settles the roll pool with one bootstrap refresh (#4276)', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const ledger = startRequestLedger(page)
    await createThread(page, {
      title: 'Move To Front Alpha',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    const beta = await createThread(page, {
      title: 'Move To Front Beta',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })

    await gotoRollPage(page)
    const poolRows = page.locator('[data-roll-pool] > div[role="button"]')
    await expect(poolRows).toHaveCount(2)

    // Baselines before the user action, so the cold-load and any die warm-up
    // traffic stay outside the measured window completely.
    const before = {
      bootstrap: ledger.count('GET', '/api/v2/roll/bootstrap'),
      movePatch: ledger.count('PATCH', `/api/v2/queue-entries/${beta.id}`),
      sessionPost: ledger.count('POST', '/api/v2/reading-sessions'),
    }

    // Real move action: the second pool row moves to the front through the
    // action sheet; the settled pool order is the visible acceptance.
    await poolRows.nth(1).click()
    const sheet = page.getByRole('dialog')
    await expect(sheet).toBeVisible()
    await sheet.getByRole('button', { name: /Move to Front/ }).click()
    await expect(poolRows.first()).toContainText('Move To Front Beta', { timeout: 15000 })
    await expect(sheet).toBeHidden()
    await expect(page.getByText(/the roll pool did not refresh/i)).not.toBeVisible()
    await expect(
      page.getByText(/failed to move series to front/i),
    ).not.toBeVisible()

    // Exactly one bootstrap refresh per move — owned by the move mutation's
    // queue-movement invalidation. The session was already resolved by the
    // cold Roll load, so the refresh is the read-only GET alone (#4276): the
    // retired explicit `refetchBootstrap()` used to append one more POST
    // /v2/reading-sessions and one more GET /v2/roll/bootstrap per move.
    expect(ledger.count('GET', '/api/v2/roll/bootstrap') - before.bootstrap).toBe(1)
    expect(ledger.count('POST', '/api/v2/reading-sessions') - before.sessionPost).toBe(0)
    expect(ledger.count('PATCH', `/api/v2/queue-entries/${beta.id}`) - before.movePatch).toBe(1)
  })

  test('shuffle confirmation settles once and refreshes the pool once (#4276)', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const ledger = startRequestLedger(page)
    await createThread(page, {
      title: 'Shuffle Pool Alpha',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await createThread(page, {
      title: 'Shuffle Pool Beta',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })

    await gotoRollPage(page)
    const poolRows = page.locator('[data-roll-pool] > div[role="button"]')
    await expect(poolRows).toHaveCount(2)

    const before = {
      bootstrap: ledger.count('GET', '/api/v2/roll/bootstrap'),
      orders: ledger.count('POST', '/api/v2/queue-orders'),
      sessionPost: ledger.count('POST', '/api/v2/reading-sessions'),
    }

    // The pool header's whole-queue shuffle trigger, addressed by its unique
    // description reference so the confirm button inside the dialog (same
    // case-insensitive label) can never be picked up as the trigger.
    await page
      .locator('button[aria-describedby="shuffle-queue-description"]')
      .click()
    const confirmDialog = page.getByTestId('shuffle-queue-dialog')
    await expect(confirmDialog).toBeVisible()

    // Real confirmation; the settled acceptance is the closed dialog over a
    // repopulated pool (the reorder itself is deliberately order-agnostic).
    await confirmDialog.getByTestId('confirm-shuffle-queue').click()
    await expect(confirmDialog).toBeHidden({ timeout: 15000 })
    await expect(poolRows).toHaveCount(2)
    await expect(page.getByTestId('shuffle-queue-error')).not.toBeVisible()

    // One whole-queue shuffle POST and one authoritative bootstrap refresh —
    // a refresh of the already-resolved session, so the read-only GET alone
    // (#4276). The retired explicit `refetchBootstrap()` after the mutation
    // used to spend a second refresh (POST /v2/reading-sessions + GET
    // /v2/roll/bootstrap).
    expect(ledger.count('POST', '/api/v2/queue-orders') - before.orders).toBe(1)
    expect(ledger.count('GET', '/api/v2/roll/bootstrap') - before.bootstrap).toBe(1)
    expect(ledger.count('POST', '/api/v2/reading-sessions') - before.sessionPost).toBe(0)
  })
})
