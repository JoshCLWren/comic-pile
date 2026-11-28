/**
 * Issue #5980 browser acceptance: Night Shift is the only visual identity.
 *
 * Captures desktop and mobile evidence for the main authenticated surfaces and
 * a representative dialog, asserts the approved palette resolves from the
 * central semantic variables, and proves that obsolete stored appearance
 * values and a stale `data-theme` attribute cannot change rendering.
 */
import { mkdir, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, test } from './fixtures'

const DESKTOP_VIEWPORT = { width: 1280, height: 900 }
const MOBILE_VIEWPORT = { width: 390, height: 844 }
const OUTPUT_DIRECTORY = join(process.cwd(), 'test-results', 'night-shift-audit')
const SCREENSHOT_DIRECTORY = join(OUTPUT_DIRECTORY, 'screenshots')

const PALETTE_TOKENS = [
  '--theme-bg-page',
  '--theme-bg-panel',
  '--theme-text-primary',
  '--theme-text-muted',
  '--theme-comic-accent',
  '--theme-continuity-accent',
  '--theme-border',
  '--theme-primary-action',
  '--theme-primary-action-text',
  '--die-light',
  '--die-dark',
] as const

type Palette = Record<(typeof PALETTE_TOKENS)[number], string>

const EXPECTED_PALETTE: Palette = {
  '--theme-bg-page': '#20242d',
  '--theme-bg-panel': '#303644',
  '--theme-text-primary': '#eef1f4',
  '--theme-text-muted': '#b2bdcb',
  '--theme-comic-accent': '#9cdbe9',
  '--theme-continuity-accent': '#c1a7f5',
  '--theme-border': '#4d5767',
  '--theme-primary-action': '#9cdbe9',
  '--theme-primary-action-text': '#111111',
  '--die-light': '#c2e9f1',
  '--die-dark': '#658e97',
}

async function readPalette(page: import('@playwright/test').Page): Promise<Palette> {
  const values = await page.evaluate((names) => {
    const styles = getComputedStyle(document.documentElement)
    return names.map((name) => {
      const value = styles.getPropertyValue(name).trim().toLowerCase()
      // CSSOM serializes #111111 as #111; normalize for the contract comparison.
      return /^#[0-9a-f]{3}$/.test(value)
        ? `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}`
        : value
    })
  }, PALETTE_TOKENS)
  // SAFETY: PALETTE_TOKENS and values are parallel arrays.
  return Object.fromEntries(PALETTE_TOKENS.map((name, index) => [name, values[index]])) as Palette
}

async function settle(page: import('@playwright/test').Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  })
}

test.describe('Night Shift single visual identity (#5980)', () => {
  test.beforeAll(async () => {
    await rm(OUTPUT_DIRECTORY, { recursive: true, force: true })
    await mkdir(SCREENSHOT_DIRECTORY, { recursive: true })
  })

  test('authenticated surfaces render the approved palette at desktop and mobile', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    const routes = [
      ['roll', '/'],
      ['queue', '/queue'],
      ['reading-lists', '/reading-lists'],
      ['history', '/history'],
    ] as const

    for (const [viewportName, viewport] of [
      ['desktop', DESKTOP_VIEWPORT],
      ['mobile', MOBILE_VIEWPORT],
    ] as const) {
      await page.setViewportSize(viewport)
      for (const [label, route] of routes) {
        await page.goto(route, { waitUntil: 'domcontentloaded' })
        await page.locator('main').waitFor({ state: 'visible' })
        await settle(page)

        expect(await readPalette(page), `${label} palette at ${viewportName}`).toEqual(EXPECTED_PALETTE)
        expect(
          await page.evaluate(() => document.documentElement.getAttribute('data-theme')),
        ).toBeNull()

        await page.screenshot({
          path: join(SCREENSHOT_DIRECTORY, `${label}-${viewportName}.png`),
          fullPage: true,
          animations: 'disabled',
          caret: 'hide',
        })
      }
    }
  })

  test('a representative modal and the shell use Night Shift surfaces', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.locator('main').waitFor({ state: 'visible' })

    await page.getByRole('button', { name: 'Send feedback' }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await settle(page)
    expect(await readPalette(page)).toEqual(EXPECTED_PALETTE)
    await dialog.screenshot({
      path: join(SCREENSHOT_DIRECTORY, 'feedback-dialog-desktop.png'),
      animations: 'disabled',
    })
  })

  test('obsolete saved preferences and a stale data-theme attribute cannot change rendering', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    await page.addInitScript(() => {
      localStorage.setItem('comic-pile-theme', 'ink-gold')
    })
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.locator('main').waitFor({ state: 'visible' })
    await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'command-center'))
    await settle(page)

    expect(await readPalette(page)).toEqual(EXPECTED_PALETTE)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('main').waitFor({ state: 'visible' })
    await settle(page)
    expect(await readPalette(page)).toEqual(EXPECTED_PALETTE)
  })

  test('no appearance selector is exposed on desktop or in the mobile More tray', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    const sidebar = page.getByRole('navigation', { name: 'Desktop navigation' })
    await expect(sidebar).toBeVisible()
    await expect(sidebar.getByRole('group', { name: /appearance/i })).toHaveCount(0)
    await expect(sidebar.locator('[data-theme]')).toHaveCount(0)
    await expect(sidebar.getByRole('button', { name: /classic|ink.gold|command.center/i })).toHaveCount(0)
    await sidebar.screenshot({
      path: join(SCREENSHOT_DIRECTORY, 'settings-shell-desktop.png'),
      animations: 'disabled',
    })

    await page.setViewportSize(MOBILE_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.getByRole('navigation', { name: 'Mobile navigation' }).getByRole('button', { name: 'More pages' }).click()
    const tray = page.getByRole('navigation', { name: 'More pages' })
    await expect(tray).toBeVisible()
    await expect(tray.locator('[data-theme]')).toHaveCount(0)
    await expect(tray.getByText(/appearance/i)).toHaveCount(0)
    await tray.screenshot({
      path: join(SCREENSHOT_DIRECTORY, 'settings-tray-mobile.png'),
      animations: 'disabled',
    })
  })

  test('unauthenticated shell and mobile modal use Night Shift', async ({ page }) => {
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.locator('main').waitFor({ state: 'visible' })
    await settle(page)
    expect(await readPalette(page)).toEqual(EXPECTED_PALETTE)
    await page.screenshot({
      path: join(SCREENSHOT_DIRECTORY, 'login-desktop.png'),
      fullPage: true,
      animations: 'disabled',
    })

    await page.setViewportSize(MOBILE_VIEWPORT)
    await page.getByRole('button', { name: 'Send feedback' }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await settle(page)
    expect(await readPalette(page)).toEqual(EXPECTED_PALETTE)
    await dialog.screenshot({
      path: join(SCREENSHOT_DIRECTORY, 'feedback-dialog-mobile.png'),
      animations: 'disabled',
    })
  })

  test('queue loading, error, and keyboard focus states remain visible and semantic', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    await page.setViewportSize(DESKTOP_VIEWPORT)

    let releaseThreads: (() => void) | undefined
    const threadsGate = new Promise<void>((resolve) => {
      releaseThreads = resolve
    })
    await page.route('**/api/v2/threads*', async (route) => {
      await threadsGate
      await route.continue()
    })
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await page.locator('main').waitFor({ state: 'visible' })
    await settle(page)
    expect(await readPalette(page)).toEqual(EXPECTED_PALETTE)
    await page.screenshot({
      path: join(SCREENSHOT_DIRECTORY, 'queue-loading-desktop.png'),
      fullPage: true,
      animations: 'disabled',
    })
    releaseThreads?.()

    await page.unroute('**/api/v2/threads*')
    await page.route('**/api/v2/threads*', (route) =>
      route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } }),
    )
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('alert').filter({ hasText: /couldn.t load/i })).toBeVisible()
    await settle(page)
    expect(await readPalette(page)).toEqual(EXPECTED_PALETTE)
    await page.screenshot({
      path: join(SCREENSHOT_DIRECTORY, 'queue-error-desktop.png'),
      fullPage: true,
      animations: 'disabled',
    })

    await page.unroute('**/api/v2/threads*')
    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    const search = page.getByRole('textbox', { name: 'Search series' })
    await search.focus()
    await expect(search).toBeFocused()
    await settle(page)
    await page.screenshot({
      path: join(SCREENSHOT_DIRECTORY, 'queue-focus-desktop.png'),
      fullPage: true,
      animations: 'disabled',
    })
  })

  test('the actual Night Shift die is captured at desktop and mobile sizes', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    for (const [viewportName, viewport] of [
      ['desktop', DESKTOP_VIEWPORT],
      ['mobile', MOBILE_VIEWPORT],
    ] as const) {
      await page.setViewportSize(viewport)
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      const die = page.getByTestId('main-die-3d')
      await expect(die).toBeVisible()
      await settle(page)
      expect(await readPalette(page)).toEqual(EXPECTED_PALETTE)
      await die.screenshot({
        path: join(SCREENSHOT_DIRECTORY, `die-${viewportName}.png`),
        animations: 'disabled',
      })
    }
  })
})
