/**
 * Issue #1887 acceptance: intentional desktop navigation.
 *
 * The 2026-08 dogfood audit found the sole global navigation at desktop
 * viewports was still the mobile emoji tab bar stretched across a wide canvas:
 * OS-rendered emoji glyphs, ~9px labels, and a fixed bottom bar that also
 * feeds the #1645 content-occlusion problem.
 *
 * These browser-level checks assert rendered behavior (not class names) at a
 * representative 1920x1080 desktop viewport so a future styling change cannot
 * quietly regress the contract again:
 * - desktop navigation is an intentional pointer-first sidebar, not the
 *   mobile bottom bar;
 * - every existing destination stays directly reachable from it;
 * - icons are consistent inline SVGs, never OS-rendered emoji glyphs;
 * - destination labels keep a comfortably readable rendered size;
 * - the mobile compact bottom-tab pattern survives on its own breakpoint;
 * - the fixed sidebar cannot cover page content (#1645 coordination) and the
 *   page keeps no horizontal overflow at 1920px.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'

const DESKTOP_VIEWPORT = { width: 1920, height: 1080 }

const DESTINATIONS = [
   'Roll page',
   'Queue page',
   'History page',
   'Crossovers page',
   'Continuity Planner page',
   "What's New page",
   'Help page',
 ]

async function openAuthenticatedDesktop(page: Page): Promise<void> {
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
}

test.describe('Desktop navigation redesign (#1887)', () => {
  test('renders an intentional icon-based desktop sidebar with readable labels', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await openAuthenticatedDesktop(page)

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toBeVisible()

    // Every current destination remains directly reachable from the sidebar.
    for (const name of DESTINATIONS) {
      await expect(desktopNav.getByRole('link', { name })).toBeVisible()
    }

    // Iconography is consistent inline SVG, never OS-rendered emoji glyphs.
    const linkIcons = await desktopNav.locator('a').evaluateAll((links) =>
      links.map((link) => ({
        svgCount: link.querySelectorAll('svg').length,
        text: link.textContent ?? '',
      })),
    )
    expect(linkIcons.length).toBeGreaterThanOrEqual(DESTINATIONS.length)
    for (const icon of linkIcons) {
      expect(icon.svgCount, `${icon.text} must render a consistent SVG icon`).toBeGreaterThan(0)
      expect(
        /\p{Extended_Pictographic}/u.test(icon.text),
        `${icon.text} must not rely on an emoji glyph`,
      ).toBe(false)
    }

    // Destination labels stay comfortably readable at 100% zoom.
    const labelFontSizes = await desktopNav.locator('a span').evaluateAll((spans) =>
      spans.map((span) => Number.parseFloat(window.getComputedStyle(span).fontSize)),
    )
    expect(labelFontSizes.length).toBeGreaterThan(0)
    for (const fontSize of labelFontSizes) {
      expect(fontSize).toBeGreaterThanOrEqual(12)
    }

    // Account controls move into the sidebar footer instead of floating
    // chrome, so theme switching and logout stay reachable on desktop.
    await expect(desktopNav.getByRole('group', { name: 'Appearance' })).toBeVisible()
    await expect(desktopNav.getByRole('button', { name: 'Log out' })).toBeVisible()
  })

  test('keeps the compact mobile tab bar off the desktop breakpoint and vice versa', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await openAuthenticatedDesktop(page)

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })

    await expect(desktopNav).toBeVisible()
    await expect(mobileNav).toBeHidden()

    // The mobile pattern may retain a compact bottom-tab bar where
    // appropriate; it must come back below the md breakpoint.
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(mobileNav).toBeVisible()
    await expect(desktopNav).toBeHidden()
  })

  test('desktop sidebar destinations navigate directly without covering content', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await openAuthenticatedDesktop(page)

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toBeVisible()

    await desktopNav.getByRole('link', { name: 'Help page' }).click()
    await expect(page).toHaveURL(/\/help$/)
    await desktopNav.getByRole('link', { name: 'Queue page' }).click()
    await expect(page).toHaveURL(/\/queue$/)

    // #1645 coordination: the fixed sidebar must not overlap page content and
    // the desktop layout keeps no horizontal overflow at 1920px.
    const layout = await page.evaluate(() => {
      const navRect = document
        .querySelector<HTMLElement>('nav[aria-label="Desktop navigation"]')
        ?.getBoundingClientRect()
      const mainRect = document.querySelector<HTMLElement>('main')?.getBoundingClientRect()
      return {
        navWidth: navRect?.width ?? 0,
        navRight: navRect?.right ?? Number.NEGATIVE_INFINITY,
        mainLeft: mainRect?.left ?? Number.POSITIVE_INFINITY,
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }
    })
    expect(layout.navWidth).toBeGreaterThan(0)
    expect(layout.mainLeft).toBeGreaterThanOrEqual(layout.navRight)
    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.innerWidth)
  })
})
