import { mkdir, rm } from 'node:fs/promises'
import { join } from 'node:path'
import type { Page, Route } from '@playwright/test'
import { expect, test } from './fixtures'
import {
  captureRenderedAudit,
  type AuditPageResult,
  type AuditReport,
  type AuditViewport,
  writeAuditReport,
} from './ui-audit/harness'
import {
  AUDIT_FIXED_NOW,
  AUDIT_FIXED_USERNAME,
  stabilizeAuditApiPayload,
} from './ui-audit/stabilize'

const OUTPUT_DIRECTORY = join(process.cwd(), 'test-results', 'ui-audit')
const SCREENSHOT_DIRECTORY = join(OUTPUT_DIRECTORY, 'screenshots')
const results: AuditPageResult[] = []

const VIEWPORTS: AuditViewport[] = [
  { name: 'phone', width: 390, height: 844 },
  { name: 'tablet', width: 820, height: 1180 },
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'wide-desktop', width: 1920, height: 1080 },
]

type Scenario = {
  name: string
  route: string
  checkBlankRegions: boolean
  prepare?: (page: Page) => Promise<void>
  afterCapture?: (page: Page) => Promise<void>
}

async function stabilizeApiRoute(route: Route): Promise<void> {
  const response = await route.fetch()
  const contentType = response.headers()['content-type'] ?? ''
  if (!contentType.includes('application/json')) {
    await route.fulfill({ response })
    return
  }

  const pathname = new URL(route.request().url()).pathname
  const payload = await response.json()
  await route.fulfill({
    response,
    json: stabilizeAuditApiPayload(pathname, payload),
  })
}

async function installStableAuditResponses(page: Page): Promise<void> {
  await page.route('**/api/v1/auth/me', stabilizeApiRoute)
  await page.route(/\/api\/v1\/sessions\/(?:current\/)?(?:\?.*)?$/, stabilizeApiRoute)
}

async function waitForApplicationState(page: Page, viewport: AuditViewport): Promise<void> {
  await page.locator('[data-app-shell-ready]').waitFor({ state: 'visible' })
  await expect(page.getByText('Loading page...', { exact: true })).toBeHidden()
  await expect(page.locator('main')).toBeVisible()
  if (viewport.width >= 768) {
    await expect(page.getByText(AUDIT_FIXED_USERNAME, { exact: true })).toBeVisible()
  }
  await page.evaluate(async () => {
    await document.fonts.ready
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  })
}

async function openManualPicker(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Pick manually' }).click()
  await expect(page.getByRole('dialog', { name: 'Pick manually' })).toBeVisible()
}

async function enterDeterministicRatingState(page: Page): Promise<void> {
  await openManualPicker(page)
  const dialog = page.getByRole('dialog', { name: 'Pick manually' })
  const threadSelect = dialog.locator('select')
  await expect.poll(async () => threadSelect.locator('option').count()).toBeGreaterThan(1)
  await threadSelect.selectOption({ index: 1 })
  await dialog.getByRole('button', { name: 'Pick this thread' }).click()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible()
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  await page.locator('#rating-input').fill('4')
}

const SCENARIOS: Scenario[] = [
  {
    name: 'roll',
    route: '/',
    checkBlankRegions: true,
    prepare: async (page) => {
      await expect(page.getByRole('button', { name: 'Roll the dice' })).toBeVisible()
    },
  },
  {
    name: 'roll-rating',
    route: '/',
    checkBlankRegions: true,
    prepare: enterDeterministicRatingState,
    afterCapture: async (page) => {
      const rateResponse = page.waitForResponse(
        (response) => response.url().includes('/api/v1/rate/') && response.request().method() === 'POST',
      )
      await page.getByTestId('save-and-continue').click()
      expect((await rateResponse).ok()).toBe(true)
      await expect(page.getByTestId('rating-pillars-grid')).toBeHidden()
    },
  },
  {
    name: 'queue',
    route: '/queue',
    checkBlankRegions: true,
  },
  {
    name: 'history',
    route: '/history',
    checkBlankRegions: true,
  },
  {
    name: 'crossovers',
    route: '/crossovers',
    checkBlankRegions: false,
  },
  {
    name: 'continuity-plans',
    route: '/continuity-plans',
    checkBlankRegions: false,
  },
  {
    name: 'continuity-planner',
    route: '/continuity-plans/new',
    checkBlankRegions: true,
    prepare: async (page) => {
      await expect(page.getByRole('heading', { name: 'Sequential planner' })).toBeVisible()
    },
  },
  {
    name: 'manual-picker-dialog',
    route: '/',
    checkBlankRegions: false,
    prepare: openManualPicker,
    afterCapture: async (page) => {
      const dialog = page.getByRole('dialog', { name: 'Pick manually' })
      await dialog.getByRole('button', { name: 'Close modal' }).click()
      await expect(dialog).toBeHidden()
    },
  },
]

test.describe('cross-page visual and geometry audit (#2043)', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async () => {
    await rm(OUTPUT_DIRECTORY, { recursive: true, force: true })
    await mkdir(SCREENSHOT_DIRECTORY, { recursive: true })
  })

  for (const viewport of VIEWPORTS) {
    test(`${viewport.name} ${viewport.width}x${viewport.height}`, async ({ authenticatedWithThreadsPage }) => {
      const page = authenticatedWithThreadsPage
      const viewportResults: AuditPageResult[] = []

      await installStableAuditResponses(page)
      await page.addInitScript({
        content: `(() => {
          const fixedNow = Date.parse(${JSON.stringify(AUDIT_FIXED_NOW)});
          const RealDate = Date;
          class FixedDate extends RealDate {
            constructor(...args) {
              super(...(args.length ? args : [fixedNow]));
            }
            static now() { return fixedNow; }
          }
          window.Date = FixedDate;
        })();`,
      })
      await page.setViewportSize({ width: viewport.width, height: viewport.height })

      for (const scenario of SCENARIOS) {
        await page.goto(scenario.route, { waitUntil: 'domcontentloaded' })
        await waitForApplicationState(page, viewport)
        await page.addStyleTag({
          content: `
            *, *::before, *::after {
              animation-duration: 0s !important;
              animation-delay: 0s !important;
              transition-duration: 0s !important;
              transition-delay: 0s !important;
              caret-color: transparent !important;
            }
          `,
        })
        await scenario.prepare?.(page)
        await page.evaluate(async () => {
          await document.fonts.ready
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
        })

        const fileStem = `${scenario.name}-${viewport.name}-${viewport.width}x${viewport.height}`
        const screenshotRelativePath = `screenshots/${fileStem}.png`
        const captured = await captureRenderedAudit(page, {
          scenario: scenario.name,
          route: scenario.route,
          viewport,
          checkBlankRegions: scenario.checkBlankRegions,
        })
        const diceCanvas = page.locator('#main-die-3d canvas')
        const screenshotMask = (await diceCanvas.count()) > 0 ? [diceCanvas] : []
        await page.screenshot({
          path: join(OUTPUT_DIRECTORY, screenshotRelativePath),
          fullPage: true,
          animations: 'disabled',
          caret: 'hide',
          mask: screenshotMask,
          maskColor: '#1c1917',
        })
        const result = { ...captured, screenshot: screenshotRelativePath }
        results.push(result)
        viewportResults.push(result)

        await scenario.afterCapture?.(page)
      }

      expect(viewportResults).toHaveLength(SCENARIOS.length)
      expect(viewportResults.every((result) => result.styleInventory.length > 0)).toBe(true)
    })
  }

  test.afterAll(async () => {
    const report: AuditReport = {
      schemaVersion: 1,
      generatedAt: AUDIT_FIXED_NOW,
      fixture: 'fresh authenticatedWithThreadsPage user per viewport; three deterministic ten-issue threads; volatile username/session timestamps normalized',
      results,
    }
    await writeAuditReport(report, OUTPUT_DIRECTORY)
  })
})
