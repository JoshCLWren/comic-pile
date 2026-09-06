/**
 * Issue #2304 acceptance: the mobile Pile Roller header must communicate a
 * single roll-mode grammar at phone widths.
 *
 * Regression context: on iPhone Safari the header row showed `d4 AUTO`
 * (accent text on a dark outlined control) next to a large solid-orange
 * `PICK MANUALLY` button whose fill read as the selected state even though
 * automatic mode was active. The fix introduces one convention:
 *   - the active roll-mode control gets the solid `--theme-primary-action`
 *     fill;
 *   - inactive/status mode controls stay neutral dark outlines with muted
 *     text;
 *   - `Pick manually` is an outlined action (never a solid selected state).
 *
 * These browser checks assert the *rendered* fill, not class names, and only
 * consider visible controls at a phone viewport so a future class reshuffle
 * cannot silently regress the state grammar.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken } from './helpers'

const PHONE_VIEWPORT = { width: 390, height: 844 }

async function headerControlSnapshot(page: Page): Promise<{
  primaryActionRgb: string
  solidCount: number
  solidLabel: string | null
  pickManually: { backgroundColor: string; hasDialog: boolean }
  dieControl: { label: string; hasDialog: boolean; backgroundColor: string }
  autoPressed: string | null
}> {
  return page.evaluate(() => {
    const probe = document.createElement('div')
    document.body.appendChild(probe)
    probe.style.backgroundColor = 'var(--theme-primary-action)'
    const primaryActionRgb = getComputedStyle(probe).backgroundColor
    probe.remove()

    const visible = (element: Element): boolean => {
      const rect = element.getBoundingClientRect()
      return rect.width > 0 && rect.height > 0
    }

    const headerButtons = Array.from(document.querySelectorAll('header button')).filter(visible)
    const solidButtons = headerButtons.filter(
      (button) => getComputedStyle(button).backgroundColor === primaryActionRgb,
    )

    const pickManually = document.querySelector('[data-roll-primary-action="pick-manually"]') as HTMLButtonElement | null
    const dieControl = Array.from(document.querySelectorAll('header button')).find(
      (button) => button.getAttribute('aria-label')?.startsWith('Current die d') ?? false,
    ) as HTMLButtonElement | null
    const auto = Array.from(document.querySelectorAll('header button')).find(
      (button) => button.textContent?.trim() === 'Auto',
    ) as HTMLButtonElement | null

    return {
      primaryActionRgb,
      solidCount: solidButtons.length,
      solidLabel: solidButtons[0]?.textContent?.trim() ?? null,
      pickManually: {
        backgroundColor: pickManually ? getComputedStyle(pickManually).backgroundColor : '',
        hasDialog: pickManually?.getAttribute('aria-haspopup') === 'dialog',
      },
      dieControl: {
        label: dieControl?.getAttribute('aria-label') ?? '',
        hasDialog: dieControl?.getAttribute('aria-haspopup') === 'dialog',
        backgroundColor: dieControl ? getComputedStyle(dieControl).backgroundColor : '',
      },
      autoPressed: auto?.getAttribute('aria-pressed') ?? null,
    }
  })
}

test.describe('Roll-mode control state grammar at phone width (#2304)', () => {
  test('exactly the active die control is solid-filled; Pick manually stays an outlined action', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, { title: 'Mode Grammar Thread', format: 'Issue', issues_remaining: 2, total_issues: 2 })

    await page.setViewportSize(PHONE_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('#die-selector')).toBeVisible()

    const snapshot = await headerControlSnapshot(page)

    expect(snapshot.primaryActionRgb).not.toBe('')
    // Exactly one visible header control uses the solid active fill.
    expect(snapshot.solidCount, `expected one solid active control, got ${snapshot.solidCount}`).toBe(1)
    // ... and it is the die control, not the manual-pick action.
    expect(snapshot.dieControl.label).toMatch(/automatic mode/)
    expect(snapshot.dieControl.backgroundColor).toBe(snapshot.primaryActionRgb)
    expect(snapshot.pickManually.backgroundColor).not.toBe(snapshot.primaryActionRgb)

    // The solid die control is a dialog trigger whose accessible name states
    // the actual active mode.
    expect(snapshot.dieControl.hasDialog).toBe(true)
    expect(snapshot.dieControl.label).toMatch(/^Current die d\d+, automatic mode$/)
  })

  test('Pick Manually opens the override dialog instead of being a selected mode', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, { title: 'Override Dialog Thread', format: 'Issue', issues_remaining: 2, total_issues: 2 })

    await page.setViewportSize(PHONE_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('[data-roll-primary-action="pick-manually"]')).toBeVisible()

    const snapshot = await headerControlSnapshot(page)
    expect(snapshot.pickManually.hasDialog).toBe(true)

    await page.locator('[data-roll-primary-action="pick-manually"]').click()
    await expect(page.getByRole('dialog', { name: 'Pick manually' })).toBeVisible()
  })

  test('the ladder Auto segment and pinned die report the truthful pressed states', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, { title: 'Auto State Thread', format: 'Issue', issues_remaining: 2, total_issues: 2 })

    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    const autoButton = page.getByRole('button', { name: 'Auto', exact: true })
    await expect(autoButton).toBeVisible()
    // Fresh session: automatic ladder mode is active.
    await expect(autoButton).toHaveAttribute('aria-pressed', 'true')

    // Pin die d8 on the server, mirroring the manual-pick dialog flow.
    const csrf = (await (await page.request.get('/api/auth/csrf', {
      headers: { Authorization: `Bearer ${await getAuthToken(page)}` },
    })).json()) as { csrf_token?: string }
    const token = await getAuthToken(page)
    const seeded = await page.request.post('/v1/roll/set-die?die=8', {
      headers: { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrf.csrf_token! },
    })
    expect(seeded.ok(), `set-die failed: ${seeded.status()}`).toBeTruthy()

    // Reload so bootstrap reflects the pinned manual die.
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(autoButton).toBeVisible()
    await expect(autoButton).toHaveAttribute('aria-pressed', 'false')
    await expect(page.getByRole('button', { name: 'd8', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(
      page.getByRole('button', { name: /^Current die d8, manual mode$/ }),
    ).toBeVisible()
  })
})