/**
 * Issue #1941 acceptance: desktop sidebar theme selector containment.
 *
 * The desktop sidebar theme selector previously let the longest option
 * ("Command Center") render outside the rounded theme-control boundary at
 * supported desktop widths. This browser-level regression asserts the rendered
 * geometry at the actual narrow desktop breakpoint (the md breakpoint where the
 * `w-72` sidebar is at its narrowest): every theme option's bounding box must
 * be contained by the theme selector's bounding box. A DOM-exists assertion is
 * intentionally insufficient here because the failure mode is geometry, not
 * presence.
 *
 * Acceptance criteria covered:
 * - every theme option stays inside the selector boundary;
 * - no theme label clips or overlaps the sidebar edge (implication of box containment);
 * - the selected theme stays visually obvious (check mark + highlighted row);
 * - all three themes remain keyboard and pointer accessible (native buttons);
 * - the username and Log Out control remain contained in the sidebar footer;
 * - mobile navigation/theme behavior is unchanged.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'

// The desktop sidebar is fixed at `w-72` (288px) and only renders at the `md`
// breakpoint (>= 768px). 768px is therefore the narrowest supported desktop
// width where containment must still hold.
const NARROW_DESKTOP_VIEWPORT = { width: 768, height: 1024 }
const MOBILE_VIEWPORT = { width: 390, height: 844 }

type Box = { x: number; y: number; width: number; height: number }

function containedBy(box: Box, container: Box, epsilon = 0.5): boolean {
  return (
    box.x >= container.x - epsilon &&
    box.y >= container.y - epsilon &&
    box.x + box.width <= container.x + container.width + epsilon &&
    box.y + box.height <= container.y + container.height + epsilon
  )
}

test.describe('Desktop sidebar theme selector containment (#1941)', () => {
  test('keeps every theme option inside the selector boundary at narrow desktop width', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(NARROW_DESKTOP_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toBeVisible()

    const group = desktopNav.getByRole('group', { name: 'Appearance' })
    await expect(group).toBeVisible()

    const groupBox = await group.boundingBox()
    expect(groupBox, 'theme selector must have a rendered bounding box').not.toBeNull()

    for (const label of ['Classic', 'Ink Gold', 'Command Center']) {
      const option = desktopNav.getByRole('button', { name: label, exact: true })
      await expect(option, `${label} must be visible`).toBeVisible()
      const box = await option.boundingBox()
      expect(box, `${label} must have a rendered bounding box`).not.toBeNull()
      expect(
        containedBy(box as Box, groupBox as Box),
        `${label} must stay inside the theme selector boundary`,
      ).toBe(true)
    }
  })

  test('keeps the username and Log Out control inside the sidebar footer', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(NARROW_DESKTOP_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toBeVisible()
    const navBox = await desktopNav.boundingBox()
    expect(navBox, 'desktop navigation must have a rendered bounding box').not.toBeNull()

    const logout = desktopNav.getByRole('button', { name: 'Log out' })
    await expect(logout).toBeVisible()
    const logoutBox = await logout.boundingBox()
    expect(
      containedBy(logoutBox as Box, navBox as Box, 1),
      'Log Out control must remain inside the sidebar footer',
    ).toBe(true)

    const username = desktopNav.getByText(/^auth_/, { exact: false }).first()
    await expect(username).toBeVisible()
    const usernameBox = await username.boundingBox()
    expect(
      containedBy(usernameBox as Box, navBox as Box, 1),
      'username must remain inside the sidebar footer',
    ).toBe(true)
  })

  test('preserves mobile theme behavior unchanged', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })
    await expect(mobileNav).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Desktop navigation' })).toBeHidden()

    await mobileNav.getByRole('button', { name: /more pages/i }).click()
    const tray = page.getByRole('navigation', { name: /more pages/i })
    await expect(tray.getByRole('button', { name: 'Classic theme' })).toBeVisible()
    await expect(tray.getByRole('button', { name: 'Ink-gold theme' })).toBeVisible()
    await expect(tray.getByRole('button', { name: 'Command center theme' })).toBeVisible()
  })
})
