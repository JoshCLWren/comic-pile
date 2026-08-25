/**
 * Issue #1885 acceptance: Roll-screen pointer targets.
 *
 * The 2026-08-23 dogfood pass measured undersized rendered hit areas in the
 * Roll workflow: die selector buttons at roughly 30x25px, dependency/context
 * chips at roughly 106x12px, and `Show all` toggles at roughly 49x23px.
 *
 * These browser-level checks assert rendered bounding boxes (not class names)
 * so a future styling change cannot quietly shrink the effective target again:
 * - every ordinary interactive control measured here meets the WCAG 2.2 AA
 *   24x24 CSS px minimum;
 * - primary die-selector controls keep their enlarged ~44px platform target;
 * - keyboard operation of the die selector is unchanged and focus stays
 *   visible;
 * - the enlarged desktop header still fits without horizontal overflow, and
 *   the rating view keeps its #1650 no-page-scroll contract at 1920x926.
 *
 * Crossover membership chips need seeded crossover data and are covered by the
 * rendered-typography unit suite plus shared classes with the edge endpoints
 * measured below; `Show all` toggles live inside ComicVine identity panels fed
 * by an external API and follow the same shared compact-toggle classes.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken } from './helpers'

const WCAG_MIN_TARGET = 24
const PRIMARY_TARGET_MIN_HEIGHT = 42

type TargetBox = {
  label: string
  width: number
  height: number
}

async function measureVisibleBoxes(page: Page, selector: string): Promise<TargetBox[]> {
  return page.locator(selector).evaluateAll((elements) =>
    elements
      .map((element) => {
        const rect = element.getBoundingClientRect()
        return {
          label:
            element.getAttribute('aria-label')
            ?? element.textContent?.trim().slice(0, 40)
            ?? element.tagName.toLowerCase(),
          width: rect.width,
          height: rect.height,
        }
      })
      .filter((box) => box.width > 0 && box.height > 0),
  )
}

function expectMinimumTargets(boxes: TargetBox[], minHeight: number): void {
  expect(boxes.length, 'expected at least one measurable control').toBeGreaterThan(0)
  for (const box of boxes) {
    expect(
      box.width,
      `${box.label} must be at least ${WCAG_MIN_TARGET}px wide`,
    ).toBeGreaterThanOrEqual(WCAG_MIN_TARGET)
    expect(
      box.height,
      `${box.label} must be at least ${minHeight}px tall`,
    ).toBeGreaterThanOrEqual(minHeight)
  }
}

async function getCsrfToken(page: Page, token: string | null): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok()).toBeTruthy()
  const data = (await response.json()) as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = await getAuthToken(page)
  const csrf = await getCsrfToken(page, token)
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  }
}

async function openRatingView(page: Page, threadId: number): Promise<void> {
  const pending = await page.request.post(`/api/threads/${threadId}/set-pending`, {
    headers: { Authorization: `Bearer ${await getAuthToken(page)}` },
  })
  expect(pending.ok(), `set-pending failed: ${pending.status()}`).toBeTruthy()
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#rating-input')).toBeVisible()
}

test.describe('Roll pointer target sizes (#1885)', () => {
  test('die selector renders ~44px primary targets with visible keyboard focus', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, { title: 'Target Die Thread', format: 'Issue', issues_remaining: 3, total_issues: 3 })

    await page.setViewportSize({ width: 1920, height: 926 })
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('#die-selector')).toBeVisible()

    const dieBoxes = await measureVisibleBoxes(page, '#die-selector button')
    expect(dieBoxes).toHaveLength(10)
    expectMinimumTargets(dieBoxes, PRIMARY_TARGET_MIN_HEIGHT)

    // Keyboard operation is unchanged: tabbing reaches the ladder and Enter
    // still selects a die.
    const dieButton = page.getByRole('button', { name: 'd20', exact: true })
    await expect(dieButton).toBeVisible()
    let focusedLabel = ''
    for (let i = 0; i < 40; i += 1) {
      focusedLabel = await page.evaluate(() => document.activeElement?.textContent?.trim() ?? '')
      if (focusedLabel === 'd20') break
      await page.keyboard.press('Tab')
    }
    expect(focusedLabel).toBe('d20')

    const focusIndicator = await page.evaluate(() => {
      const style = window.getComputedStyle(document.activeElement as Element)
      return {
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
        boxShadow: style.boxShadow,
      }
    })
    const focusIsSuppressed =
      focusIndicator.outlineStyle === 'none'
      && focusIndicator.outlineWidth === '0px'
      && focusIndicator.boxShadow === 'none'
    expect(focusIsSuppressed, 'keyboard focus indicator must stay visible').toBe(false)

    await page.keyboard.press('Enter')
    await expect(page.locator('#header-die-label')).toHaveText('d20')

    // The enlarged ladder must not push the desktop header into horizontal
    // overflow (#1650 viewport-fit contract).
    const fit = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(fit.scrollWidth).toBeLessThanOrEqual(fit.innerWidth)
  })

  test('header compact controls meet the 24px minimum', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await createThread(page, { title: 'Compact Header Thread A', format: 'Issue', issues_remaining: 2, total_issues: 2 })
    await createThread(page, { title: 'Compact Header Thread B', format: 'Issue', issues_remaining: 2, total_issues: 2 })

    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('#die-selector')).toBeVisible()

    expectMinimumTargets(await measureVisibleBoxes(page, '#die-selector button'), PRIMARY_TARGET_MIN_HEIGHT)
    expectMinimumTargets(
      await measureVisibleBoxes(page, 'header button:has-text("Pick manually")'),
      WCAG_MIN_TARGET,
    )
    expectMinimumTargets(
      await measureVisibleBoxes(page, 'button:has-text("Shuffle queue")'),
      WCAG_MIN_TARGET,
    )

    const fit = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(fit.scrollWidth).toBeLessThanOrEqual(fit.innerWidth)
  })

  test('dependency edge endpoints and rating-view toggles meet the 24px minimum', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const blocking = await createThread(page, { title: 'Blocking Alpha', format: 'Issue', issues_remaining: 2, total_issues: 2 })
    const blocked = await createThread(page, { title: 'Blocked Beta', format: 'Issue', issues_remaining: 2, total_issues: 2 })

    // Reader-context edges are built from issue-level dependencies.
    const firstIssueId = async (threadId: number): Promise<number> => {
      const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
        headers: { Authorization: `Bearer ${await getAuthToken(page)}` },
      })
      expect(response.ok(), `issue list failed: ${response.status()}`).toBeTruthy()
      const data = (await response.json()) as { issues: Array<{ id: number }> }
      expect(data.issues.length).toBeGreaterThan(0)
      return data.issues[0]!.id
    }
    const created = await page.request.post('/api/v1/dependencies/', {
      headers: await authHeaders(page),
      data: {
        source_type: 'issue',
        source_id: await firstIssueId(blocking.id),
        target_type: 'issue',
        target_id: await firstIssueId(blocked.id),
      },
    })
    expect(created.ok(), `dependency create failed: ${await created.text()}`).toBeTruthy()

    await page.setViewportSize({ width: 1920, height: 926 })
    await openRatingView(page, blocked.id)

    // Edge endpoint buttons previously rendered as bare ~12px text strips.
    expectMinimumTargets(
      await measureVisibleBoxes(page, 'button[aria-label^="Open thread for"]'),
      WCAG_MIN_TARGET,
    )

    // Compact rating-flow controls keep comfortable targets...
    expectMinimumTargets(
      await measureVisibleBoxes(page, '[data-testid="rating-actions"] button'),
      WCAG_MIN_TARGET,
    )
    const whyToggle = page.getByRole('button', { name: /why this\?/i })
    if (await whyToggle.isVisible()) {
      const box = await whyToggle.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.height).toBeGreaterThanOrEqual(WCAG_MIN_TARGET)
    }

    // ...and the #1650 desktop no-page-scroll contract still holds at the
    // original reproduction viewport.
    const layoutFit = await page.evaluate(() => ({
      scrollHeight: document.documentElement.scrollHeight,
      scrollWidth: document.documentElement.scrollWidth,
      innerHeight: window.innerHeight,
      innerWidth: window.innerWidth,
    }))
    expect(layoutFit.scrollWidth).toBeLessThanOrEqual(layoutFit.innerWidth)
    expect(layoutFit.scrollHeight).toBeLessThanOrEqual(layoutFit.innerHeight + 8)

    // Snoozing returns to the roll view where the unsnooze control is a real
    // 28x28 target instead of a tiny strip.
    await page.getByRole('button', { name: /^Snooze/ }).click()
    const snoozedToggle = page.getByRole('button', { name: /Snoozed \(1\)/ })
    await expect(snoozedToggle).toBeVisible()
    await snoozedToggle.click()
    expectMinimumTargets(
      await measureVisibleBoxes(page, 'button[aria-label="Unsnooze this comic"]'),
      WCAG_MIN_TARGET,
    )
  })
})
