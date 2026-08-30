import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import {
  captureRenderedAudit,
  type AuditPageResult,
  type AuditReport,
  type AuditViewport,
  writeAuditReport,
} from './ui-audit/harness'

const OUTPUT_DIRECTORY = join(process.cwd(), 'test-results', 'ui-audit')
const SCREENSHOT_DIRECTORY = join(OUTPUT_DIRECTORY, 'screenshots')

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

async function waitForApplicationState(page: Page): Promise<void> {
  await page.locator('[data-app-shell-ready]').waitFor({ state: 'visible' })
  await expect(page.getByText('Loading page...', { exact: true })).toBeHidden()
  await expect(page.locator('main')).toBeVisible()
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
      await page.getByTestId('save-and-continue').click()
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
    name: 'manual-picker-dialog',
    route: '/',
    checkBlankRegions: false,
    prepare: openManualPicker,
    afterCapture: async (page) => {
      await page.getByRole('dialog', { name: 'Pick manually' }).getByRole('button', { name: 'Close modal' }).click()
      await expect(page.getByRole('dialog', { name: 'Pick manually' })).toBeHidden()
    },
  },
]

test('cross-page visual and geometry audit (#2043)', async ({ authenticatedWithThreadsPage }) => {
  const page = authenticatedWithThreadsPage
  const results: AuditPageResult[] = []

  await mkdir(SCREENSHOT_DIRECTORY, { recursive: true })
  await page.addInitScript({
    content: `(() => {
      const fixedNow = Date.parse('2026-08-30T12:00:00Z');
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

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })

    for (const scenario of SCENARIOS) {
      await page.goto(scenario.route, { waitUntil: 'domcontentloaded' })
      await waitForApplicationState(page)
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

      const fileStem = `${scenario.name}-${viewport.name}-${viewport.width}x${viewport.height}`
      const screenshotRelativePath = `screenshots/${fileStem}.png`
      const captured = await captureRenderedAudit(page, {
        scenario: scenario.name,
        route: scenario.route,
        viewport,
        checkBlankRegions: scenario.checkBlankRegions,
      })
      await page.screenshot({
        path: join(OUTPUT_DIRECTORY, screenshotRelativePath),
        fullPage: true,
        animations: 'disabled',
        caret: 'hide',
      })
      results.push({ ...captured, screenshot: screenshotRelativePath })

      await scenario.afterCapture?.(page)
    }
  }

  const report: AuditReport = {
    schemaVersion: 1,
    generatedAt: '2026-08-30T12:00:00.000Z',
    fixture: 'authenticatedWithThreadsPage: isolated user, three deterministic ten-issue threads',
    results,
  }
  await writeAuditReport(report, OUTPUT_DIRECTORY)

  expect(results).toHaveLength(VIEWPORTS.length * SCENARIOS.length)
  expect(results.every((result) => result.styleInventory.length > 0)).toBe(true)
})
