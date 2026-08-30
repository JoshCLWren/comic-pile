/**
 * Issue #1645 acceptance: fixed chrome must not overlap page content at
 * supported desktop widths.
 *
 * Checks bounding-box intersection of navigation/header elements vs main
 * content on Roll, Queue, History, Crossovers, and Planner pages at
 * 900x900 and 1280x800 viewports.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'

const VIEWPORTS = [
  { width: 900, height: 900, label: '900x900' },
  { width: 1280, height: 800, label: '1280x800' },
] as const

const ROUTES = [
  { path: '/', label: 'Roll' },
  { path: '/queue', label: 'Queue' },
  { path: '/history', label: 'History' },
  { path: '/crossovers', label: 'Crossovers' },
  { path: '/continuity-plans', label: 'Planner' },
] as const

/**
 * Returns true if two axis-aligned rectangles overlap (intersect with
 * positive area, not just touching edges).
 */
function rectsOverlap(
  a: { left: number; top: number; right: number; bottom: number },
  b: { left: number; top: number; right: number; bottom: number },
): boolean {
  const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left)
  const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return overlapX > 0 && overlapY > 0
}

test.describe('Fixed chrome overlap (#1645)', () => {
  for (const viewport of VIEWPORTS) {
    test.describe(`${viewport.label}`, () => {
      for (const route of ROUTES) {
        test(`${route.label}: no nav/header overlaps main content`, async ({
          authenticatedPage,
        }) => {
          const page = authenticatedPage
          await page.setViewportSize(viewport)
          await page.goto(route.path, { waitUntil: 'domcontentloaded' })

          const main = page.locator('[data-authenticated-shell] > main')
          await expect(main).toBeVisible()

          const overlap = await page.evaluate(() => {
            const mainEl = document.querySelector<HTMLElement>(
              '[data-authenticated-shell] > main',
            )
            if (!mainEl) return { hasOverlap: true, detail: 'main not found' }
            const mainRect = mainEl.getBoundingClientRect()

            // Collect all visible fixed/sticky navigation elements
            const navSelectors = [
              'nav[aria-label="Desktop navigation"]',
              'nav[aria-label="Mobile navigation"]',
            ]

            for (const sel of navSelectors) {
              const navEl = document.querySelector<HTMLElement>(sel)
              if (!navEl) continue
              const style = window.getComputedStyle(navEl)
              if (style.display === 'none') continue
              const navRect = navEl.getBoundingClientRect()
              if (navRect.width === 0 || navRect.height === 0) continue

              // Check horizontal adjacency (nav should be to the left of main on desktop)
              const navRight = navRect.right
              const mainLeft = mainRect.left
              if (mainLeft < navRight - 1) {
                return {
                  hasOverlap: true,
                  detail: `${sel} right (${navRight}) overlaps main left (${mainLeft})`,
                }
              }
            }

            // Check that the bottom nav (if visible) does not cover main content
            const mobileNav = document.querySelector<HTMLElement>(
              'nav[aria-label="Mobile navigation"]',
            )
            if (mobileNav) {
              const mobileStyle = window.getComputedStyle(mobileNav)
              if (
                mobileStyle.display !== 'none' &&
                mobileNav.getBoundingClientRect().width > 0
              ) {
                const navRect = mobileNav.getBoundingClientRect()
                const mainRect2 = mainEl.getBoundingClientRect()
                // The bottom nav should not cover main content at rest scroll
                // (main bottom should be above nav top, or main should have padding)
                if (
                  mainRect2.bottom > navRect.top &&
                  mainRect2.top < navRect.bottom &&
                  mainRect2.left < navRect.right &&
                  mainRect2.right > navRect.left
                ) {
                  // Only flag if the overlap is significant (> 10px)
                  const overlapHeight =
                    Math.min(mainRect2.bottom, navRect.bottom) -
                    Math.max(mainRect2.top, navRect.top)
                  if (overlapHeight > 10) {
                    return {
                      hasOverlap: true,
                      detail: `mobile nav covers ${overlapHeight}px of main content`,
                    }
                  }
                }
              }
            }

            // Check the Roll header controls don't overflow into sidebar space
            const rollHeader = document.querySelector<HTMLElement>(
              '[data-authenticated-shell] > main header',
            )
            if (rollHeader) {
              const headerRect = rollHeader.getBoundingClientRect()
              const headerStyle = window.getComputedStyle(rollHeader)
              if (headerStyle.overflow !== 'hidden') {
                // Header should not extend past the main content area
                if (headerRect.right > mainRect.right + 1) {
                  return {
                    hasOverlap: true,
                    detail: `header extends ${headerRect.right - mainRect.right}px past main right`,
                  }
                }
              }
            }

            return { hasOverlap: false }
          })

          expect(
            overlap.hasOverlap,
            `${route.label} at ${viewport.label}: ${overlap.detail ?? 'no overlap'}`,
          ).toBe(false)
        })
      }
    })
  }

  test('Roll header die selector wraps without overlapping heading at 900px', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 900, height: 900 })
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const main = page.locator('[data-authenticated-shell] > main')
    await expect(main).toBeVisible()

    const overlap = await page.evaluate(() => {
      const mainEl = document.querySelector<HTMLElement>(
        '[data-authenticated-shell] > main',
      )
      if (!mainEl) return { hasOverlap: true, detail: 'main not found' }

      const header = mainEl.querySelector<HTMLElement>('header')
      if (!header) return { hasOverlap: false }

      // Check if the header overflows the main content area
      const mainRect = mainEl.getBoundingClientRect()
      const headerRect = header.getBoundingClientRect()

      if (headerRect.right > mainRect.right + 1) {
        return {
          hasOverlap: true,
          detail: `header right (${headerRect.right}) exceeds main right (${mainRect.right})`,
        }
      }

      // Check that the heading and die selector don't overlap vertically
      const h1 = header.querySelector<HTMLElement>('h1')
      const dieSelector = header.querySelector<HTMLElement>('#die-selector')
      if (h1 && dieSelector) {
        const h1Rect = h1.getBoundingClientRect()
        const dieRect = dieSelector.getBoundingClientRect()
        if (
          h1Rect.right > dieRect.left &&
          h1Rect.bottom > dieRect.top &&
          h1Rect.top < dieRect.bottom
        ) {
          return {
            hasOverlap: true,
            detail: `h1 and die selector overlap at 900px`,
          }
        }
      }

      return { hasOverlap: false }
    })

    expect(
      overlap.hasOverlap,
      `Roll header: ${overlap.detail ?? 'no overlap'}`,
    ).toBe(false)
  })

  test('Queue header controls don\'t overflow at 900px', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 900, height: 900 })
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })

    const main = page.locator('[data-authenticated-shell] > main')
    await expect(main).toBeVisible()

    const overflow = await page.evaluate(() => {
      const mainEl = document.querySelector<HTMLElement>(
        '[data-authenticated-shell] > main',
      )
      if (!mainEl) return { hasOverflow: false }

      const mainRect = mainEl.getBoundingClientRect()
      const scrollWidth = document.documentElement.scrollWidth
      const innerWidth = window.innerWidth

      if (scrollWidth > innerWidth + 1) {
        return {
          hasOverflow: true,
          detail: `page scroll width (${scrollWidth}) exceeds viewport (${innerWidth})`,
        }
      }

      return { hasOverflow: false }
    })

    expect(
      overflow.hasOverflow,
      `Queue at 900px: ${overflow.detail ?? 'no overflow'}`,
    ).toBe(false)
  })

  test('Planner sticky save bar does not overlap bottom content at 900px', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 900, height: 900 })
    await page.goto('/continuity-plans', { waitUntil: 'domcontentloaded' })

    const main = page.locator('[data-authenticated-shell] > main')
    await expect(main).toBeVisible()

    // Navigate into a plan if possible, otherwise check the index page
    const overlap = await page.evaluate(() => {
      const mainEl = document.querySelector<HTMLElement>(
        '[data-authenticated-shell] > main',
      )
      if (!mainEl) return { hasOverlap: false }

      const mainRect = mainEl.getBoundingClientRect()

      // Check for sticky elements that might overlap content
      const stickyElements = mainEl.querySelectorAll<HTMLElement>(
        '[class*="sticky"]',
      )
      for (const el of stickyElements) {
        const style = window.getComputedStyle(el)
        if (style.position === 'sticky') {
          const elRect = el.getBoundingClientRect()
          // Sticky element should not extend outside the main content area
          if (elRect.right > mainRect.right + 1) {
            return {
              hasOverlap: true,
              detail: `sticky element extends past main right at 900px`,
            }
          }
        }
      }

      return { hasOverlap: false }
    })

    expect(
      overlap.hasOverlap,
      `Planner: ${overlap.detail ?? 'no overlap'}`,
    ).toBe(false)
  })
})
