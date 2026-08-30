/**
 * Issue #2023 acceptance: the authenticated shell owns the space consumed by
 * persistent navigation instead of letting individual pages guess an offset.
 *
 * The original regression was introduced when the desktop sidebar grew from
 * 14rem to 18rem while the authenticated main content kept its old 14rem left
 * margin. PR #2002 later reintroduced that stale offset after #2025 fixed it.
 * These checks exercise rendered geometry across the supported viewport matrix
 * and verify that changing the rendered navigation width automatically reflows
 * the main column without a second matching offset.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'

const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 900, height: 900 },
  { width: 1024, height: 768 },
  { width: 1141, height: 926 },
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1792, height: 896 },
  { width: 1920, height: 1080 },
] as const

const ROUTES = [
  { path: '/', label: 'Roll' },
  { path: '/queue', label: 'Queue' },
  { path: '/history', label: 'History' },
  { path: '/crossovers', label: 'Crossovers' },
  { path: '/continuity-plans', label: 'Planner' },
  { path: '/whats-new', label: 'New' },
  { path: '/glossary', label: 'Glossary' },
] as const

test.describe('Responsive authenticated app shell (#2023)', () => {
  for (const route of ROUTES) {
    test(`${route.label} stays inside the usable viewport beside persistent navigation`, async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage
      await page.goto(route.path, { waitUntil: 'domcontentloaded' })

      const shell = page.locator('[data-authenticated-shell]')
      const main = page.locator('[data-authenticated-shell] > main')
      const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
      const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })

      await expect(shell).toBeVisible()
      await expect(main).toBeVisible()

      for (const viewport of VIEWPORTS) {
        await page.setViewportSize(viewport)

        const geometry = await page.evaluate(() => {
          const mainRect = document
            .querySelector<HTMLElement>('[data-authenticated-shell] > main')
            ?.getBoundingClientRect()
          const navRect = document
            .querySelector<HTMLElement>('nav[aria-label="Desktop navigation"]')
            ?.getBoundingClientRect()
          const navVisible = navRect !== undefined
            && navRect.width > 0
            && navRect.height > 0
            && window.getComputedStyle(
              document.querySelector<HTMLElement>('nav[aria-label="Desktop navigation"]')!,
            ).display !== 'none'

          return {
            mainLeft: mainRect?.left ?? Number.NEGATIVE_INFINITY,
            mainRight: mainRect?.right ?? Number.POSITIVE_INFINITY,
            navRight: navRect?.right ?? Number.NEGATIVE_INFINITY,
            navVisible,
            scrollWidth: document.documentElement.scrollWidth,
            innerWidth: window.innerWidth,
          }
        })

        expect(
          geometry.mainLeft,
          `${route.label} main content must remain inside ${viewport.width}x${viewport.height}`,
        ).toBeGreaterThanOrEqual(0)
        expect(
          geometry.mainRight,
          `${route.label} main content must not extend past ${viewport.width}x${viewport.height}`,
        ).toBeLessThanOrEqual(geometry.innerWidth + 1)
        expect(
          geometry.scrollWidth,
          `${route.label} must not introduce page-level horizontal overflow at ${viewport.width}x${viewport.height}`,
        ).toBeLessThanOrEqual(geometry.innerWidth)

        if (viewport.width >= 768) {
          await expect(desktopNav).toBeVisible()
          await expect(mobileNav).toBeHidden()
          expect(
            geometry.mainLeft,
            `${route.label} main content must clear the desktop sidebar at ${viewport.width}x${viewport.height}`,
          ).toBeGreaterThanOrEqual(geometry.navRight)
        } else {
          await expect(desktopNav).toBeHidden()
          await expect(mobileNav).toBeVisible()
          expect(geometry.navVisible).toBe(false)
        }
      }
    })
  }

  test('main reflows from the rendered desktop navigation width', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const shell = page.locator('[data-authenticated-shell]')
    const main = page.locator('[data-authenticated-shell] > main')
    const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })

    await expect(shell).toBeVisible()
    await expect(main).toBeVisible()
    await expect(desktopNav).toBeVisible()

    const initialMainLeft = await main.evaluate(
      (element) => element.getBoundingClientRect().left,
    )

    await desktopNav.evaluate((nav) => {
      nav.style.width = '20rem'
    })

    await expect.poll(async () => {
      return page.evaluate((initialLeft) => {
        const mainRect = document
          .querySelector<HTMLElement>('[data-authenticated-shell] > main')
          ?.getBoundingClientRect()
        const navRect = document
          .querySelector<HTMLElement>('nav[aria-label="Desktop navigation"]')
          ?.getBoundingClientRect()
        const mainLeft = mainRect?.left ?? Number.NEGATIVE_INFINITY
        const navRight = navRect?.right ?? Number.POSITIVE_INFINITY
        return Math.abs(mainLeft - navRight) <= 1 && mainLeft > initialLeft
      }, initialMainLeft)
    }).toBe(true)

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.innerWidth)
  })
})
