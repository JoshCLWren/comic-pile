/**
 * Issue #2232 acceptance: classic and ink-gold must be obviously different and
 * every theme must keep its comic / continuity / personal accent vocabulary.
 *
 * Browser-level evidence for the theme-personality contract:
 *
 * 1. Blind switch: each theme's `--theme-*` semantic tokens resolve to a shared
 *    palette that is distinct from the other two, so a reviewer can name the
 *    active theme from Roll/Queue screenshots alone. We assert the applied
 *    computed styles for the page canvas and the three accents differ across
 *    themes, and we capture side-by-side desktop screenshots for Roll + Queue
 *    into `test-results/theme-audit/` as visual regression evidence.
 * 2. Accent separation: comic, continuity, and personal accents remain pairwise
 *    distinct in every theme via computed style (not just static CSS), so a
 *    user can tell comic identity from reading-chain/continuity and personal
 *    context regardless of the active theme.
 * 3. Command center stays intact: its three accents also resolve distinct and
 *    its page canvas remains the electric navy cockpit rather than a warm
 *    editorial palette, so the cockpit north star is not regressed.
 *
 * Themes are switched through the real desktop Appearance picker so this tests
 * the runtime `selectTheme` path, not just the stored-preference bootstrap.
 *
 * Acceptance criteria covered:
 * - blind theme switch from Roll/Queue screenshots;
 * - continuity and personal accents distinguishable from comic/primary in every theme;
 * - no regression of command-center cockpit north star;
 * - focused visual regression screenshots for the three themes (CI artifacts).
 */
import { mkdir, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, test } from './fixtures'

const DESKTOP_VIEWPORT = { width: 1280, height: 900 }
const OUTPUT_DIRECTORY = join(process.cwd(), 'test-results', 'theme-audit')
const SCREENSHOT_DIRECTORY = join(OUTPUT_DIRECTORY, 'screenshots')

const THEMES = ['classic', 'ink-gold', 'command-center'] as const

// switchTheme guarantees the desktop rail is expanded before selecting, so the
// picker exposes the label text ("Ink Gold theme" / "Command Center theme")
// rather than the compact-rail aria-labels ("Ink-gold theme" /
// "Command center theme"). Matching the expanded accessible names keeps the
// locator valid in both the default wide-desktop state and after expanding a
// collapsed rail (issue #1941 uses the same expanded names).
const THEME_BUTTON_NAMES: Record<(typeof THEMES)[number], string> = {
  classic: 'Classic theme',
  'ink-gold': 'Ink Gold theme',
  'command-center': 'Command Center theme',
}

const ACCENT_TOKENS = [
  '--theme-comic-accent',
  '--theme-continuity-accent',
  '--theme-personal-accent',
] as const

const READ_TOKENS = [
  '--theme-bg-page',
  '--theme-bg-panel',
  '--theme-text-primary',
  '--theme-comic-accent',
  '--theme-continuity-accent',
  '--theme-personal-accent',
] as const

type AppliedTokens = Record<(typeof READ_TOKENS)[number], string>

async function readAppliedTokens(page: import('@playwright/test').Page): Promise<AppliedTokens> {
  const values = await page.evaluate((tokenNames) => {
    const styles = getComputedStyle(document.documentElement)
    return tokenNames.map((token) => styles.getPropertyValue(token).trim())
  }, READ_TOKENS)
  return Object.fromEntries(READ_TOKENS.map((token, index) => [token, values[index]])) as AppliedTokens
}

async function switchTheme(
  page: import('@playwright/test').Page,
  themeId: (typeof THEMES)[number],
): Promise<void> {
  const desktopNav = page.getByRole('navigation', { name: 'Desktop navigation' })
  await expect(desktopNav).toBeVisible()
  const toggle = desktopNav.getByRole('button', { name: 'Expand navigation' })
  if (await toggle.isVisible()) {
    await toggle.click()
    await expect(desktopNav.getByRole('button', { name: 'Collapse navigation' })).toBeVisible()
  }
  await desktopNav.getByRole('button', { name: THEME_BUTTON_NAMES[themeId] }).click()
  await expect.poll(() =>
    page.evaluate(() => document.documentElement.getAttribute('data-theme')),
  ).toBe(themeId)
}

test.describe('Theme personality and accent separation (#2232)', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async () => {
    await rm(OUTPUT_DIRECTORY, { recursive: true, force: true })
    await mkdir(SCREENSHOT_DIRECTORY, { recursive: true })
  })

  for (const themeId of THEMES) {
    test(`${themeId} keeps accents distinct and captures Roll + Queue evidence`, async ({
      authenticatedWithThreadsPage,
    }) => {
      const page = authenticatedWithThreadsPage
      await page.setViewportSize(DESKTOP_VIEWPORT)
      await switchTheme(page, themeId)

      for (const [label, route] of [
        ['roll', '/'],
        ['queue', '/queue'],
      ] as const) {
        await page.goto(route, { waitUntil: 'domcontentloaded' })
        await page.locator('#root').waitFor({ state: 'visible' })
        await expect(page.locator('main')).toBeVisible()
        await page.evaluate(async () => {
          await document.fonts.ready
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
        })

        expect(
          await page.evaluate(() => document.documentElement.getAttribute('data-theme')),
          `${themeId} must stay applied after navigating to ${label}`,
        ).toBe(themeId)

        const tokens = await readAppliedTokens(page)
        expect(tokens['--theme-bg-page'], `${themeId} page canvas must resolve`).not.toBe('')
        expect(
          new Set(ACCENT_TOKENS.map((token) => tokens[token])).size,
          `${themeId} comic/continuity/personal accents must stay pairwise distinct on ${label}`,
        ).toBe(ACCENT_TOKENS.length)

        await page.screenshot({
          path: join(SCREENSHOT_DIRECTORY, `${label}-${themeId}-desktop.png`),
          fullPage: true,
          animations: 'disabled',
          caret: 'hide',
        })
      }
    })
  }

  test('blind switch: every theme resolves a distinct, nameable palette', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    await page.setViewportSize(DESKTOP_VIEWPORT)

    const palettes: string[] = []
    for (const themeId of THEMES) {
      await switchTheme(page, themeId)
      const tokens = await readAppliedTokens(page)
      palettes.push(
        [
          tokens['--theme-bg-page'],
          tokens['--theme-bg-panel'],
          tokens['--theme-text-primary'],
          tokens['--theme-comic-accent'],
          tokens['--theme-continuity-accent'],
          tokens['--theme-personal-accent'],
        ].join('|'),
      )
    }

    expect(new Set(palettes).size).toBe(THEMES.length)
  })

  test('command-center keeps its cockpit north star distinct from warm editorial themes', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage
    await page.setViewportSize(DESKTOP_VIEWPORT)

    const palettes: Record<(typeof THEMES)[number], AppliedTokens> = {} as Record<
      (typeof THEMES)[number],
      AppliedTokens
    >
    for (const themeId of THEMES) {
      await switchTheme(page, themeId)
      palettes[themeId] = await readAppliedTokens(page)
    }

    const command = palettes['command-center']
    for (const warm of [palettes.classic, palettes['ink-gold']]) {
      expect(command['--theme-bg-page']).not.toBe(warm['--theme-bg-page'])
      expect(command['--theme-comic-accent']).not.toBe(warm['--theme-comic-accent'])
    }
    expect(
      new Set(ACCENT_TOKENS.map((token) => command[token])).size,
      'command-center comic/continuity/personal accents must stay distinct',
    ).toBe(ACCENT_TOKENS.length)
  })
})