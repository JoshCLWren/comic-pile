/**
 * Issue #2296: Fix Issue Number modal geometry on tablet portrait.
 *
 * The Fix Issue Number dialog used to render inline inside the comic pillar,
 * where tablet-portrait layout left it left-clipped and painted behind the
 * comic cover. It now uses the shared portal-based Modal (dialog overlay layer
 * above the page), so these rendered-browser checks pin the actual geometry:
 * the dialog bounding box must stay inside the viewport, its header, input,
 * and actions must be reachable, and the topmost element at the dialog's
 * center must belong to the dialog — proving it paints above the cover
 * instead of hiding behind it.
 *
 * Assertions cover the reported 800x1094 viewport plus the secondary tablet
 * sizes, with phone and desktop checked for regressions.
 *
 * Regression anchors:
 * - #2296: left-clipped, cover-occluded Fix Issue modal at 800x1094.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken } from './helpers'

const TABLET_PORTRAIT = { width: 800, height: 1094 }
const TABLET_PORTRAIT_ALT = { width: 820, height: 1180 }
const TABLET_LANDSCAPE = { width: 1180, height: 820 }
const PHONE = { width: 390, height: 844 }
const DESKTOP = { width: 1920, height: 1080 }

const VIEWPORTS = [
  { label: 'tablet portrait 800x1094', viewport: TABLET_PORTRAIT },
  { label: 'tablet portrait 820x1180', viewport: TABLET_PORTRAIT_ALT },
  { label: 'tablet landscape 1180x820', viewport: TABLET_LANDSCAPE },
  { label: 'phone 390x844', viewport: PHONE },
  { label: 'desktop 1920x1080', viewport: DESKTOP },
]

/** Small tolerance for subpixel rounding; real clipping is dozens of px. */
const TOLERANCE_PX = 1

type Rect = {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
}

type ModalGeometry = {
  viewport: { width: number; height: number }
  dialog: Rect | null
  heading: Rect | null
  input: Rect | null
  cancel: Rect | null
  confirm: Rect | null
  cover: Rect | null
  portaledToBody: boolean
  topmostAtCenterInDialog: boolean
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

async function seedCoverIdentity(
  page: Page,
  threadId: number,
  seriesName: string,
  seriesId: number,
): Promise<void> {
  const token = await getAuthToken(page)
  const csrfResponse = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(csrfResponse.ok()).toBeTruthy()
  const data = (await csrfResponse.json()) as { csrf_token?: string }
  const seedHeaders: Record<string, string> = {};
  seedHeaders['Content-Type'] = 'application/json';
  if (token) {
    seedHeaders.Authorization = `Bearer ${token}`
  }
  if (data.csrf_token) {
    seedHeaders['X-CSRF-Token'] = data.csrf_token
  }
  const response = await page.request.post('/api/test/issue-identity', {
    headers: seedHeaders,
    data: { thread_id: threadId, series_name: seriesName, series_id: seriesId },
  })
  expect(response.ok(), `identity seed failed: ${await response.text()}`).toBeTruthy()
}

async function openRatingView(page: Page, threadId: number): Promise<void> {
  const token = await getAuthToken(page)
  const response = await page.request.post(`/api/threads/${threadId}/set-pending`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok(), `set-pending failed: ${response.status()} ${await response.text()}`).toBeTruthy()
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible()
  await expect(page.getByTestId('comic-cover')).toBeVisible({ timeout: 15000 })
  await page.evaluate(() => document.fonts.ready)
  // Let React settle once the issue-intelligence response lands.
  await page.waitForTimeout(300)
}

async function openFixIssueModal(page: Page) {
  await page.getByRole('button', { name: 'Fix issue number' }).click()
  const dialog = page.getByTestId('issue-correction-dialog')
  await expect(dialog).toBeVisible({ timeout: 15000 })
  await expect(page.locator('#issue-number')).toBeVisible({ timeout: 15000 })
  await expect(page.getByRole('button', { name: /^Update$/ })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
  await page.waitForTimeout(200)
  return dialog
}

async function readModalGeometry(page: Page): Promise<ModalGeometry> {
  return page.evaluate(() => {
    const rectOf = (element: Element | null | undefined): Rect | null => {
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

    const dialog = document.querySelector('[data-testid="issue-correction-dialog"]')
    const overlayRoot = document.getElementById('comic-pile-overlay-root-dialog')
    const cover = document.querySelector('[data-testid="comic-cover"]')

    let topmostAtCenterInDialog = false
    if (dialog) {
      const r = dialog.getBoundingClientRect()
      const centerX = r.left + r.width / 2
      const centerY = r.top + r.height / 2
      const topmost = document.elementFromPoint(centerX, centerY)
      topmostAtCenterInDialog = topmost !== null && (topmost === dialog || dialog.contains(topmost))
    }

    const cancel = dialog
      ? Array.from(dialog.querySelectorAll('button')).find((button) => button.textContent?.trim() === 'Cancel')
      : null
    const confirm = dialog
      ? Array.from(dialog.querySelectorAll('button')).find((button) => {
          const text = button.textContent?.trim()
          return text === 'Update' || text === 'Updating...'
        })
      : null

    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      dialog: rectOf(dialog),
      heading: rectOf(dialog?.querySelector('h2')),
      input: rectOf(document.getElementById('issue-number')),
      cancel: rectOf(cancel),
      confirm: rectOf(confirm),
      cover: rectOf(cover),
      portaledToBody: !!dialog && !!overlayRoot && overlayRoot.contains(dialog),
      topmostAtCenterInDialog,
    }
  })
}

function assertRectWithinViewport(label: string, rect: Rect | null, viewport: { width: number; height: number }): void {
  expect(rect, `${label} must be present`).not.toBeNull()
  expect(rect!.left, `${label} must not be clipped on the left`).toBeGreaterThanOrEqual(-TOLERANCE_PX)
  expect(rect!.right, `${label} must not escape the right edge of the viewport`).toBeLessThanOrEqual(viewport.width + TOLERANCE_PX)
  expect(rect!.top, `${label} must not be cut off at the top`).toBeGreaterThanOrEqual(-TOLERANCE_PX)
  expect(rect!.bottom, `${label} must not escape the bottom edge of the viewport`).toBeLessThanOrEqual(viewport.height + TOLERANCE_PX)
}

function assertRectInsideDialog(label: string, rect: Rect | null, dialog: Rect): void {
  expect(rect, `${label} must be present inside the dialog`).not.toBeNull()
  expect(rect!.left, `${label} must start inside the dialog`).toBeGreaterThanOrEqual(dialog.left - TOLERANCE_PX)
  expect(rect!.right, `${label} must end inside the dialog`).toBeLessThanOrEqual(dialog.right + TOLERANCE_PX)
}

test.describe('Fix Issue Number modal geometry (#2296)', () => {
  for (const { label, viewport } of VIEWPORTS) {
    test(`${label}: modal is fully on-screen, above the cover, and reachable`, async ({
      authenticatedPage,
    }) => {
      test.setTimeout(60000)
      const page = authenticatedPage
      await page.setViewportSize(viewport)

      const thread = await createThread(page, {
        title: 'Fix Issue Modal Comic',
        format: 'Issue',
        issues_remaining: 3,
        total_issues: 3,
      })
      const issues = await listIssues(page, thread.id)
      expect(issues.length).toBe(3)
      await seedCoverIdentity(page, thread.id, 'Fixmodalverse', 700100)

      await openRatingView(page, thread.id)
      await openFixIssueModal(page)

      const geometry = await readModalGeometry(page)
      const { dialog, viewport: renderedViewport } = geometry

      expect(viewport.width, 'rendered width must match the test viewport').toBe(renderedViewport.width)
      expect(viewport.height, 'rendered height must match the test viewport').toBe(renderedViewport.height)
      expect(dialog, 'the dialog must be present').not.toBeNull()

      // The dialog is portaled to the body-level dialog overlay layer, which
      // lives outside the comic pillar stacking context entirely.
      expect(geometry.portaledToBody, 'the dialog must render in the body-level dialog overlay').toBeTruthy()

      assertRectWithinViewport('dialog', dialog!, renderedViewport)
      assertRectWithinViewport('heading', geometry.heading, renderedViewport)
      assertRectWithinViewport('issue input', geometry.input, renderedViewport)
      assertRectWithinViewport('cancel action', geometry.cancel, renderedViewport)
      assertRectWithinViewport('confirm action', geometry.confirm, renderedViewport)

      assertRectInsideDialog('heading', geometry.heading, dialog!)
      assertRectInsideDialog('issue input', geometry.input, dialog!)
      assertRectInsideDialog('cancel action', geometry.cancel, dialog!)
      assertRectInsideDialog('confirm action', geometry.confirm, dialog!)

      // Correct z-order: the topmost element at the dialog's center belongs to
      // the dialog, so the cover and other page layers cannot be hiding it.
      expect(
        geometry.topmostAtCenterInDialog,
        'the dialog must paint above the comic cover and other page layers',
      ).toBeTruthy()

      expect(geometry.cover, 'the cover must be rendered for the stacking check').not.toBeNull()
    })
  }
})