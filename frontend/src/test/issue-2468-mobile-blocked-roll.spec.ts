/**
 * Issue #2468: the blocked Roll / continuity experience must stay usable on
 * narrow mobile screens.
 *
 * Reported on iPhone Safari production:
 * - the blocked "Series Progress" card was squeezed into a half-column,
 *   wrapping series titles one word per line;
 * - the "READ NOW" action overlapped the prerequisite comic title;
 * - the sticky bottom navigation crowded the lower continuity content;
 * - the Roll Result column left a large empty block while the important
 *   blocked content was compressed into the right column.
 *
 * These browser checks exercise the real rendered geometry on a 390x844
 * phone viewport: the Roll Result + Series Progress stats grid must collapse
 * to a single column, the blocked recovery card must span the full column,
 * the prerequisite title and Read now CTA must occupy separate layout regions
 * (no overlap), and the bottom navigation must not cover reachable continuity
 * content. Screenshots of the blocked roll state and the expanded continuity
 * panel are attached as regression evidence.
 */
import { expect, type Page, type TestInfo } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken } from './helpers'

const MOBILE_VIEWPORT = { width: 390, height: 844 }
const ESCAPE_TOLERANCE_PX = 2

type Rect = {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
}

type MobileBlockedGeometry = {
  viewport: { width: number; height: number }
  doc: { scrollWidth: number; scrollHeight: number }
  statsGrid: {
    columns: number
    left: number
    right: number
    width: number
  } | null
  blockedCard: Rect | null
  readNowRows: Array<{ label: Rect; cta: Rect }>
  readingContextBottom: number
  mobileNavTop: number | null
}

async function getCsrf(page: Page, token: string | null): Promise<string> {
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
  const csrf = await getCsrf(page, token)
  return {
    Authorization: `Bearer ${token ?? ''}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  }
}

async function listIssues(page: Page, threadId: number): Promise<number[]> {
  const token = await getAuthToken(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok(), `issue list failed: ${await response.text()}`).toBeTruthy()
  const data = (await response.json()) as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues.map((issue) => issue.id)
}

async function setPending(page: Page, threadId: number): Promise<void> {
  const token = await getAuthToken(page)
  const response = await page.request.post(`/api/threads/${threadId}/set-pending`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok(), `set-pending failed: ${response.status()} ${await response.text()}`).toBeTruthy()
}

async function seedDependency(
  page: Page,
  headers: Record<string, string>,
  sourceIssueId: number,
  targetIssueId: number,
): Promise<void> {
  const response = await page.request.post('/api/v1/dependencies/', {
    headers,
    data: {
      source_type: 'issue',
      source_id: sourceIssueId,
      target_type: 'issue',
      target_id: targetIssueId,
    },
  })
  expect(response.ok(), `dependency seed failed: ${await response.text()}`).toBeTruthy()
}

async function seedThreadIdentity(
  page: Page,
  headers: Record<string, string>,
  threadId: number,
  seriesName: string,
  seriesId: number,
): Promise<void> {
  const response = await page.request.post('/api/test/issue-identity', {
    headers,
    data: { thread_id: threadId, series_name: seriesName, series_id: seriesId },
  })
  expect(response.ok(), `identity seed failed: ${await response.text()}`).toBeTruthy()
}

async function readGeometry(page: Page): Promise<MobileBlockedGeometry> {
  return page.evaluate(() => {
    const rectOf = (element: Element | null): Rect | null => {
      if (!element) return null
      const r = element.getBoundingClientRect()
      return {
        left: r.left,
        right: r.right,
        top: r.top,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      }
    }

    const statsGridEl = document.querySelector('[data-testid="roll-stats-section"]')
    const gridRect = statsGridEl?.getBoundingClientRect()
    const columns = statsGridEl
      ? (window.getComputedStyle(statsGridEl).gridTemplateColumns.split(' ').length)
      : 0

    const card = document.querySelector('[aria-label="Blocked roll recovery"]')

    const readNowRows: Array<{ label: Rect; cta: Rect }> = []
    if (card) {
      for (const row of Array.from(
        card.querySelectorAll('button, [class*="rounded-xl"]:not(button)'),
      )) {
        const label = row.querySelector('span.text-sm.font-black')
        const cta = Array.from(row.querySelectorAll('span')).find(
          (span) => span.textContent?.trim() === 'Read now',
        )
        if (label && cta) {
          const labelRect = label.getBoundingClientRect()
          const ctaRect = cta.getBoundingClientRect()
          if (labelRect.width > 0 && ctaRect.width > 0) {
            readNowRows.push({ label: rectOf(label)!, cta: rectOf(cta)! })
          }
        }
      }
    }

    const mobileNav = document.querySelector<HTMLElement>(
      'nav[aria-label="Mobile navigation"]',
    )
    const mobileNavStyle = mobileNav ? window.getComputedStyle(mobileNav) : null
    const mobileNavTop =
      mobileNav && mobileNavStyle && mobileNavStyle.display !== 'none'
        ? mobileNav.getBoundingClientRect().top
        : null

    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      doc: {
        scrollWidth: document.documentElement.scrollWidth,
        scrollHeight: document.documentElement.scrollHeight,
      },
      statsGrid: gridRect
        ? {
            columns,
            left: gridRect.left,
            right: gridRect.right,
            width: gridRect.width,
          }
        : null,
      blockedCard: rectOf(card),
      readNowRows,
      readingContextBottom: rectOf(
        document.querySelector('[data-testid="rating-region-reading-context"]'),
      )?.bottom ?? 0,
      mobileNavTop,
    }
  })
}

test.describe('Mobile blocked Roll layout (#2468)', () => {
  test('blocked recovery card spans one full column with non-overlapping CTA and clear bottom nav', async ({
    authenticatedPage,
  }, testInfo: TestInfo) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)

    const blocked = await createThread(page, {
      title: 'Justice League Europe',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    const anchor = await createThread(page, {
      title: 'Martian Manhunter (1988)',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })

    const headers = await authHeaders(page)
    await seedDependency(page, headers, (await listIssues(page, anchor.id))[0]!, (await listIssues(page, blocked.id))[0]!)
    await seedThreadIdentity(page, headers, blocked.id, 'Justice League Europe', 2468_001)

    const contextLoaded = page
      .waitForResponse((response) => response.url().includes('/reader-context'), {
        timeout: 15000,
      })
      .catch(() => null)

    await setPending(page, blocked.id)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
    await expect(page.getByLabel('Blocked roll recovery')).toBeVisible({ timeout: 15000 })
    await expect(page.getByText('Where you are in Justice League Europe')).toBeVisible()
    await contextLoaded
    await page.evaluate(() => document.fonts.ready)
    await page.waitForTimeout(400)

    // 1. The stats grid must be a single column on a phone: full width for the
    //    actionable blocked card, no empty Roll Result half-column.
    const initial = await readGeometry(page)
    expect(initial.statsGrid).not.toBeNull()
    expect(initial.statsGrid!.columns).toBe(1)
    expect(
      initial.doc.scrollWidth,
      'the Roll page must not require horizontal scrolling on a phone',
    ).toBeLessThanOrEqual(initial.viewport.width + ESCAPE_TOLERANCE_PX)

    // 2. The blocked card spans the full stats column instead of half of it.
    expect(initial.blockedCard).not.toBeNull()
    expect(
      initial.blockedCard!.width,
      'the blocked recovery card must span the full mobile column',
    ).toBeGreaterThan(initial.statsGrid!.width * 0.75)

    // 3. The Read now CTA must live in a separate layout region below the
    //    prerequisite title, so the two can never overlap.
    expect(initial.readNowRows.length).toBeGreaterThan(0)
    for (const row of initial.readNowRows) {
      const overlapWidth = Math.min(row.label.right, row.cta.right) - Math.max(row.label.left, row.cta.left)
      const overlapHeight = Math.min(row.label.bottom, row.cta.bottom) - Math.max(row.label.top, row.cta.top)
      const overlapArea = Math.max(0, overlapWidth) * Math.max(0, overlapHeight)
      expect(
        overlapArea,
        'the Read now CTA must not overlap the prerequisite title',
      ).toBe(0)
    }

    await testInfo.attach('mobile-blocked-roll-card', {
      body: await page.screenshot(),
      contentType: 'image/png',
    })

    // 4. Expand the continuity panel (current issue context) and verify the
    //    bottom navigation never covers reachable continuity content.
    await page
      .getByRole('button', { name: /Show context for Justice League Europe issue 1/ })
      .click()
    await expect(page.getByText('You are here')).toBeVisible()
    await page.waitForTimeout(200)

    const expanded = await readGeometry(page)
    expect(
      expanded.doc.scrollWidth,
      'expanded continuity content must not introduce horizontal overflow',
    ).toBeLessThanOrEqual(expanded.viewport.width + ESCAPE_TOLERANCE_PX)
    expect(expanded.mobileNavTop).not.toBeNull()

    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    await page.waitForTimeout(300)

    const clearance = await page.evaluate((navTop: number) => {
      const documentElement = document.documentElement
      const main = document.querySelector<HTMLElement>('[data-authenticated-shell] > main')
      const centerX = main
        ? main.getBoundingClientRect().left + main.getBoundingClientRect().width / 2
        : window.innerWidth / 2
      const samples = [navTop - 4, navTop - 24, navTop - 44]
        .filter((y) => y > 0)
        .map((y) => {
          const element = document.elementFromPoint(centerX, y)
          const hitNav = element?.closest('nav[aria-label="Mobile navigation"]') !== null
          return { y, hitNav, hitMain: element?.closest('main') !== null }
        })
      return {
        samples,
        scrollHeight: documentElement.scrollHeight,
        navTop,
        innerHeight: window.innerHeight,
      }
    }, expanded.mobileNavTop!)

    expect(
      clearance.samples.length,
      'the points directly above the mobile nav must resolve inside the app shell',
    ).toBeGreaterThan(0)
    for (const sample of clearance.samples) {
      expect(sample.hitNav, `bottom nav must not cover content at y=${sample.y}`).toBe(false)
      expect(sample.hitMain, `content above the nav must stay reachable at y=${sample.y}`).toBe(true)
    }

    await testInfo.attach('mobile-expanded-continuity-panel', {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
  })
})