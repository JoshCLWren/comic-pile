/**
 * Issue #2285 acceptance: authenticated navigation collapses and reclaims
 * content width on tablets.
 *
 * The sidebar used to be permanently expanded at the `md` breakpoint, forcing
 * a 288px (`w-72`) column on an 800px tablet viewport. These browser-level
 * checks assert rendered shell geometry at tablet portrait and wide desktop:
 * the default nav width, the main-content reflow on expand/collapse through
 * normal layout flow (never overlay), state survival across authenticated route
 * changes, compact-mode accessibility, and phone-navigation non-regression.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'

const TABLET_PORTRAIT = { width: 800, height: 1094 } as const
const TABLET_PORTRAIT_820 = { width: 820, height: 1180 } as const
const WIDE_DESKTOP = { width: 1440, height: 900 } as const
const PHONE = { width: 390, height: 844 } as const

const EXPECTED_COLLAPSED_RIGHT = 66 // 64px rail + 1px right border
const EXPECTED_EXPANDED_RIGHT = 289 // 288px sidebar + 1px right border
const TOLERANCE = 3

function approx(value: number, target: number, tolerance = TOLERANCE): boolean {
  return Math.abs(value - target) <= tolerance
}

async function shellGeometry(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const nav = document.querySelector<HTMLElement>('nav[aria-label="Desktop navigation"]')
    const main = document.querySelector<HTMLElement>('[data-authenticated-shell] > main')
    const navRect = nav?.getBoundingClientRect()
    const mainRect = main?.getBoundingClientRect()
    const mainStyle = main ? window.getComputedStyle(main) : null
    return {
      navWidth: navRect?.width ?? 0,
      navRight: navRect?.right ?? 0,
      navPosition: nav ? window.getComputedStyle(nav).position : '',
      mainLeft: mainRect?.left ?? 0,
      mainWidth: mainRect?.width ?? 0,
      mainPosition: mainStyle?.position ?? '',
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }
  })
}

test.describe('Authenticated navigation collapse (#2285)', () => {
  test('tablet portrait starts collapsed instead of forcing the 288px sidebar', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    for (const viewport of [TABLET_PORTRAIT, TABLET_PORTRAIT_820]) {
      await page.setViewportSize(viewport)
      await page.goto('/', { waitUntil: 'domcontentloaded' })

      const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
      await expect(desktopNav).toBeVisible()
      await expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')

      const geometry = await shellGeometry(page)
      expect(
        geometry.navWidth,
        `sidebar must not force the full 288px at ${viewport.width}x${viewport.height}`,
      ).toBeLessThanOrEqual(EXPECTED_COLLAPSED_RIGHT + TOLERANCE)
      expect(
        geometry.navWidth,
        `sidebar should render as a compact rail at ${viewport.width}x${viewport.height}`,
      ).toBeGreaterThan(0)
      expect(
        geometry.mainLeft,
        `main content must clear the collapsed rail at ${viewport.width}x${viewport.height}`,
      ).toBeGreaterThanOrEqual(geometry.navRight - 1)
      expect(
        geometry.mainWidth,
        `main content must reclaim tablet width at ${viewport.width}x${viewport.height}`,
      ).toBeGreaterThan(viewport.width / 2)
      expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.innerWidth)
    }
  })

  test('expanding and collapsing reflows main width through normal layout flow', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(TABLET_PORTRAIT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toBeVisible()

    const collapsedGeometry = await shellGeometry(page)
    expect(collapsedGeometry.navPosition).toBe('sticky')
    expect(collapsedGeometry.mainPosition).toBe('static')

    const expand = desktopNav.getByRole('button', { name: 'Expand navigation' })
    await expand.click()

    await expect
      .poll(async () => (await shellGeometry(page)).mainWidth)
      .toBeGreaterThan(collapsedGeometry.mainWidth)

    const expandedGeometry = await shellGeometry(page)
    expect(approx(expandedGeometry.navWidth, EXPECTED_EXPANDED_RIGHT)).toBe(true)
    expect(
      expandedGeometry.mainLeft,
      'main must sit beside the expanded nav in layout flow, not under an overlay',
    ).toBeGreaterThanOrEqual(expandedGeometry.navRight - 1)
    expect(expandedGeometry.navPosition).toBe('sticky')
    expect(expandedGeometry.mainPosition).toBe('static')

    const collapse = desktopNav.getByRole('button', { name: 'Collapse navigation' })
    await collapse.click()

    await expect
      .poll(async () => (await shellGeometry(page)).mainWidth)
      .toBeLessThan(expandedGeometry.mainWidth)

    const collapsedAgain = await shellGeometry(page)
    expect(approx(collapsedAgain.navWidth, EXPECTED_COLLAPSED_RIGHT)).toBe(true)
    expect(collapsedAgain.mainLeft).toBeGreaterThanOrEqual(collapsedAgain.navRight - 1)
    expect(collapsedAgain.scrollWidth).toBeLessThanOrEqual(collapsedAgain.innerWidth)
  })

  test('wide desktop keeps an expanded default and can still collapse', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(WIDE_DESKTOP)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toBeVisible()
    await expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'false')

    const expandedGeometry = await shellGeometry(page)
    expect(approx(expandedGeometry.navWidth, EXPECTED_EXPANDED_RIGHT)).toBe(true)
    await expect(desktopNav.getByRole('link', { name: /roll page/i })).toBeVisible()
    await expect(desktopNav.getByRole('link', { name: /queue page/i })).toBeVisible()
    await expect(desktopNav.getByRole('group', { name: 'Appearance' })).toBeVisible()

    await desktopNav.getByRole('button', { name: 'Collapse navigation' }).click()

    await expect
      .poll(async () => (await shellGeometry(page)).navWidth)
      .toBeLessThanOrEqual(EXPECTED_COLLAPSED_RIGHT + TOLERANCE)
    const collapsedGeometry = await shellGeometry(page)
    expect(collapsedGeometry.mainWidth).toBeGreaterThan(expandedGeometry.mainWidth)
    expect(collapsedGeometry.scrollWidth).toBeLessThanOrEqual(collapsedGeometry.innerWidth)
  })

  test('collapse state survives authenticated route changes', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(TABLET_PORTRAIT)
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toBeVisible()
    await expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')

    await page.goto('/history', { waitUntil: 'domcontentloaded' })
    await expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')

    await page.goto('/crossovers', { waitUntil: 'domcontentloaded' })
    await expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')

    await page.goto('/continuity-plans', { waitUntil: 'domcontentloaded' })
    await expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')
  })

  test('compact rail keeps themes, identity, and logout reachable and keyboard operable', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(TABLET_PORTRAIT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'true')

    await expect(desktopNav.getByRole('group', { name: 'Appearance' })).toBeVisible()
    for (const name of ['Classic theme', 'Ink-gold theme', 'Command center theme']) {
      await expect(desktopNav.getByRole('button', { name })).toBeVisible()
    }
    await expect(desktopNav.getByRole('button', { name: 'Log out' })).toBeVisible()

    const inkGold = desktopNav.getByRole('button', { name: 'Ink-gold theme' })
    await inkGold.click()
    expect(await page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe(
      'ink-gold',
    )

    const toggle = desktopNav.getByRole('button', { name: 'Expand navigation' })
    await toggle.focus()
    await page.keyboard.press('Enter')
    await expect(desktopNav.getByRole('button', { name: 'Collapse navigation' }))
      .toBeVisible()
    await expect(desktopNav).toHaveAttribute('data-nav-collapsed', 'false')
  })

  test('phone navigation is unchanged', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(PHONE)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })
    await expect(mobileNav).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Desktop navigation' })).toBeHidden()

    const geometry = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.innerWidth)
  })
})