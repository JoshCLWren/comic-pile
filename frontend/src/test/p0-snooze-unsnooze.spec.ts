/**
 * SNOOZE-001: User can snooze or unsnooze a comic and it appears
 * appropriately in the queue.
 *
 * Verifies: snooze from rating view goes through the native reroll offer
 * (replacement rolled, snoozed id kept in the browser snooze cookie) and the
 * snoozed series stays listed in the queue.
 *
 * Inventory IDs: SNOOZE-001
 *
 * #4276 addendum (zero-mock request ledger over these real flows): a Queue
 * row snooze (the native reroll offer since the v1 snooze/unsnooze routes
 * were retired, #4338/#4349) refreshes each read model exactly once. Delta
 * counts around the user action make a duplicate fetch fail instead of being
 * hidden by a total.
 */
import { expect, type Locator, type Page } from '@playwright/test'
import { test } from './fixtures'
import {
  createThread,
  dismissRollNudgeIfPresent,
  getAuthToken,
  gotoQueue,
  gotoRollPage,
  openThreadActions,
  startRequestLedger,
  waitForRollPageReady,
} from './helpers'
import { hasProperty, isNumber, isObject } from '../utils/runtimeChecks'

test.describe('SNOOZE-001: Snooze and unsnooze', () => {
  // The v1 snooze/unsnooze routes are retired (#4338/#4349). Rating-view
  // snooze is the native reroll offer: it records the snooze, rolls a
  // replacement in the same transaction (#4589), and keeps the snoozed series
  // out of today's pool through the browser snooze cookie.
  test('snooze from rating view rolls a replacement and records the cookie snooze', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const primary = await createThread(page, {
      title: 'Snooze Me Thread',
      issues_remaining: 3,
      total_issues: 3,
    })
    const replacement = await createThread(page, {
      title: 'Snooze Replacement Thread',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    // The die can pick either fixture. Wait for the actual initial offer
    // instead of clicking a pool row while the die animation is in flight.
    const initial = await offerFromClick(page, page.locator('#main-die-3d'))
    expect(initial.snoozed_thread_id).toBeNull()
    expect([primary.id, replacement.id]).toContain(initial.thread_id)
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    const body = await offerFromClick(page, page.getByTestId('reroll-offer'))
    expect(body.snoozed_thread_id).toBe(initial.thread_id)
    expect(body.thread_id).toBe(
      initial.thread_id === primary.id ? replacement.id : primary.id,
    )

    await expect.poll(() => cookieSnoozes(page)).toContain(initial.thread_id)
    // The replacement is pending, so the rating view stays up for it.
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
  })

  test('snoozed thread stays listed in the queue', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const primary = await createThread(page, {
      title: 'Queue Snooze Thread',
      issues_remaining: 3,
      total_issues: 3,
    })
    const replacement = await createThread(page, {
      title: 'Queue Snooze Replacement',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const initial = await offerFromClick(page, page.locator('#main-die-3d'))
    expect(initial.snoozed_thread_id).toBeNull()
    expect([primary.id, replacement.id]).toContain(initial.thread_id)
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    const body = await offerFromClick(page, page.getByTestId('reroll-offer'))
    expect(body.snoozed_thread_id).toBe(initial.thread_id)
    expect(body.thread_id).toBe(
      initial.thread_id === primary.id ? replacement.id : primary.id,
    )
    await expect.poll(() => cookieSnoozes(page)).toContain(initial.thread_id)

    const snoozedTitle = initial.thread_id === primary.id
      ? 'Queue Snooze Thread'
      : 'Queue Snooze Replacement'
    await gotoQueue(page)
    const threadItem = page.getByTestId('queue-thread-item').filter({ hasText: snoozedTitle })
    await expect(threadItem).toBeVisible({ timeout: 10000 })
  })

  test('queue row snooze settles the current session through one owner (#4276)', async ({
    authenticatedPage,
  }) => {
    // The v1 snooze/unsnooze routes are retired (#4338/#4349): Queue snooze is
    // the native reroll offer and Queue unsnooze is client-only (browser snooze
    // cookie, no server write). The surviving #4276 contract is that the
    // native snooze still refreshes each read model exactly once.
    const page = authenticatedPage
    const ledger = startRequestLedger(page)
    const primary = await createThread(page, {
      title: 'Single Owner Snooze Thread',
      issues_remaining: 3,
      total_issues: 3,
    })
    const replacement = await createThread(page, {
      title: 'Replacement Offer Thread',
      issues_remaining: 3,
      total_issues: 3,
    })

    // Pend a series through the real roll path so the Queue row's snooze
    // control is meaningful: only the session's pending series can snooze.
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })

    // Queue row snooze commits the pending comic and immediately offers a
    // replacement, so the fixture must have another eligible comic. Read the
    // server's authoritative pending ID to target whichever one the die chose.
    const token = await getAuthToken(page)
    if (!token) throw new Error('Authenticated fixture token was unavailable')
    const rollBootstrapResponse = await page.request.get('/api/v2/roll/bootstrap', {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(rollBootstrapResponse.ok()).toBe(true)
    const sessionData: unknown = await rollBootstrapResponse.json()
    if (
      !isObject(sessionData) ||
      !hasProperty(sessionData, 'pending_thread_id') ||
      !isNumber(sessionData.pending_thread_id)
    ) {
      throw new Error('Roll bootstrap response did not include a pending thread ID')
    }
    const threadNameById = new Map([
      [primary.id, 'Single Owner Snooze Thread'],
      [replacement.id, 'Replacement Offer Thread'],
    ])
    const pendingThreadName = threadNameById.get(sessionData.pending_thread_id)
    if (!pendingThreadName) throw new Error('Roll offered a thread outside the test fixture')

    // Baseline everything AFTER the pend: the die roll and its refresh are
    // setup traffic, outside the measured snooze window.
    await gotoQueue(page)
    await dismissRollNudgeIfPresent(page)
    const threadItem = page
      .getByTestId('queue-thread-item')
      .filter({ hasText: pendingThreadName })
    await expect(threadItem).toBeVisible()
    const before = {
      queuePages: ledger.count('GET', '/api/v2/threads'),
      excluded: ledger.count('GET', '/api/v1/threads/excluded/threads'),
    }

    // Arm the settle signal BEFORE the user action so the reconciliation
    // response cannot outrun the listener.
    const listRefresh = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET'
        && response.url().includes('/api/v2/threads')
        && response.status() === 200,
    )
    await clickThreadMenuItem(page, threadItem!, 'Snooze')
    await listRefresh

    // The retired v1 endpoint must never be called by the Queue snooze path.
    expect(ledger.count('POST', '/api/v1/snooze/')).toBe(0)
    // One bounded refresh of each read model per snooze; a second
    // handler-layer invalidation of the same key would trip these budgets.
    // The retired current-session read is never requested (#4343).
    expect(ledger.count('GET', '/api/v1/sessions/current/')).toBe(0)
    expect(ledger.count('GET', '/api/v2/threads') - before.queuePages).toBe(1)
    expect(
      ledger.count('GET', '/api/v1/threads/excluded/threads') - before.excluded,
    ).toBe(1)

    // Mutation feedback stays reserved for failures.
    await expect(page.getByText(/failed to snooze thread/i).first()).not.toBeVisible()
  })
})

/**
 * Observe the request started by this click, not a response from a previous
 * offer that may still be in flight. Assert the HTTP status separately so a
 * failed mutation cannot be hidden by waiting for a later successful one.
 */
async function offerFromClick(page: Page, button: Locator): Promise<{
  thread_id: number
  snoozed_thread_id: number | null
}> {
  const pending = page.waitForRequest((request) =>
    request.method() === 'POST'
    && new URL(request.url()).pathname === '/api/v2/roll/offer',
  )
  await button.click()
  const response = await (await pending).response()
  if (!response) throw new Error('Roll offer did not receive an HTTP response')
  expect(response.status()).toBe(200)
  const body: unknown = await response.json()
  if (
    !isObject(body)
    || !hasProperty(body, 'thread_id')
    || !isNumber(body.thread_id)
    || !hasProperty(body, 'snoozed_thread_id')
    || (body.snoozed_thread_id !== null && !isNumber(body.snoozed_thread_id))
  ) {
    throw new Error('Roll offer returned an unexpected response')
  }
  return { thread_id: body.thread_id, snoozed_thread_id: body.snoozed_thread_id }
}

/** Thread ids held in the browser snooze cookie (client-only snoozes). */
async function cookieSnoozes(page: Page): Promise<number[]> {
  const cookie = (await page.context().cookies()).find(
    (entry) => entry.name === 'comicpile_roll_snoozes',
  )
  if (!cookie) return []
  try {
    const parsed: unknown = JSON.parse(decodeURIComponent(cookie.value))
    return Array.isArray(parsed) ? parsed.filter((id): id is number => Number.isSafeInteger(id)) : []
  } catch {
    return []
  }
}

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

