/**
 * Issue #1941 regression, updated for Night Shift (#5980): the sidebar footer
 * controls that remain (identity, bug report, logout) stay inside the rendered
 * sidebar boundary at the narrowest desktop width. The former appearance
 * selector is gone, so the mobile tray guards that no theme control returned.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'

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

test.describe('Sidebar footer containment (#1941, #5980)', () => {
  test('keeps the username and Log Out control inside the sidebar footer', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(NARROW_DESKTOP_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toBeVisible()

    const toggle = desktopNav.getByRole('button', { name: 'Expand navigation' })
    await expect(toggle).toBeVisible()
    await toggle.click()
    await expect(desktopNav.getByRole('button', { name: 'Collapse navigation' })).toBeVisible()
    // The rail animates from 4rem to 18rem; measure only after the width settles.
    await expect.poll(async () => (await desktopNav.boundingBox())?.width).toBe(288)

    const navBox = await desktopNav.boundingBox()
    expect(navBox, 'desktop navigation must have a rendered bounding box').not.toBeNull()

    const logout = desktopNav.getByRole('button', { name: 'Log out' })
    await expect(logout).toBeVisible()
    const logoutBox = await logout.boundingBox()
    expect(
      // SAFETY: the assertions above prove both bounding boxes rendered before this check
      containedBy(logoutBox as Box, navBox as Box, 1),
      'Log Out control must remain inside the sidebar footer',
    ).toBe(true)

    const username = desktopNav.getByText(/^auth_/, { exact: false }).first()
    await expect(username).toBeVisible()
    const usernameBox = await username.boundingBox()
    expect(
      // SAFETY: the assertions above prove both bounding boxes rendered before this check
      containedBy(usernameBox as Box, navBox as Box, 1),
      'username must remain inside the sidebar footer',
    ).toBe(true)

    await expect(desktopNav.getByRole('group', { name: /appearance/i })).toHaveCount(0)
    await expect(desktopNav.locator('[data-theme]')).toHaveCount(0)
  })

  test('mobile navigation exposes no theme control', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })
    await expect(mobileNav).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Desktop navigation' })).toBeHidden()

    await mobileNav.getByRole('button', { name: /more pages/i }).click()
    const tray = page.getByRole('navigation', { name: /more pages/i })
    await expect(tray.locator('[data-theme]')).toHaveCount(0)
    await expect(tray.getByText(/appearance/i)).toHaveCount(0)
  })
})
