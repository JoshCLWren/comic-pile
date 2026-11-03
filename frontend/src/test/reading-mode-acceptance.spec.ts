/**
 * Reading-mode acceptance: the Roll header's reading-mode status (issue #1734).
 *
 * The session-mode mutation was retired in #4354. The Rust v2 bootstrap
 * remains the read authority, and the header presents its mode as a static
 * status chip. The reading-mode quiz has separate coverage in
 * `reading-mode-quiz.spec.ts`.
 */
import { expect, test, type Page } from '@playwright/test'
import { gotoRollPage, waitForRollPageReady } from './helpers'

type SessionMode = {
  active_bandwidth: string | null
  active_intent: string | null
}

const MODE_LABELS = {
  balanced: 'Balanced',
  deep: 'Deep',
  explore: 'Explore',
  familiar: 'Familiar',
  light: 'Light',
  momentum: 'Momentum',
  random: 'Random',
} as const satisfies Readonly<Record<string, string>>

async function getAuthToken(page: Page): Promise<string> {
  return page.evaluate(() => {
    // SAFETY: the api client reads this global token slot, which the test sets and clears directly
    const win = window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }
    return localStorage.getItem('auth_token') ?? win.__COMIC_PILE_ACCESS_TOKEN ?? ''
  })
}

async function getSessionMode(page: Page): Promise<SessionMode> {
  const token = await getAuthToken(page)
  // Use the browser transport so this request sees the same deterministic Rust
  // v2 contract response as the page's query.
  const response = await page.evaluate(async (accessToken) => {
    const result = await fetch('/api/v2/roll/bootstrap', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    return { ok: result.ok, body: await result.json() }
  })
  expect(response.ok).toBeTruthy()
  // SAFETY: the test reads only the two session-mode fields it asserts
  const body = response.body as { session_mode: SessionMode }
  return body.session_mode
}

async function mockRustRollReadApi(page: Page): Promise<void> {
  const sessionMode: SessionMode = {
    active_bandwidth: 'balanced',
    active_intent: 'explore',
  }

  await page.addInitScript(() => localStorage.setItem('auth_token', 'test-access-token'))
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const endpoint = path.split('/').at(-1)
    if (endpoint === 'me') {
      return route.fulfill({ json: {
        id: 1,
        username: 'reader',
        email: 'reader@example.test',
        preferences: { theme: 'classic' },
      } })
    }
    if (endpoint === 'refresh') {
      return route.fulfill({ json: { access_token: 'test-access-token' } })
    }
    if (endpoint === 'csrf') {
      return route.fulfill({ json: { csrf_token: 'test-csrf' } })
    }
    if (path === '/api/v2/reading-sessions') {
      return route.fulfill({ json: { session_id: 1, created: false } })
    }
    if (path === '/api/v2/roll/bootstrap') {
      return route.fulfill({ json: {
      session_id: 1,
      user_id: 1,
      current_die: 6,
      manual_die: null,
      pending_thread_id: null,
      last_rolled_result: null,
      session_mode: {
        ...sessionMode,
        predicted_bandwidth: null,
        bandwidth_confidence: null,
        bandwidth_source: null,
        bandwidth_version: null,
        predicted_intent: null,
        intent_confidence: null,
        intent_source: null,
        intent_version: null,
        session_mode_correction_guidance: null,
      },
      active_thread: null,
      bandwidth: {
        predicted_bandwidth: null,
        active_bandwidth: sessionMode.active_bandwidth,
        confidence: null,
        source: null,
        mode_version: null,
      },
      pool_reason: 'no_series',
      rollable: [],
      snoozed_threads: [],
      snoozed_count: 0,
      skipped_thread_ids: [],
      skipped_threads: [],
      last_read: null,
      } })
    }
    if (path === '/api/v2/threads') {
      return route.fulfill({ json: { threads: [], next_page_token: null, active_count: 0 } })
    }
    return route.fulfill({ json: [] })
  })
}

function isModeLabel(value: string): value is keyof typeof MODE_LABELS {
  return Object.hasOwn(MODE_LABELS, value)
}

function modeLabel(value: string | null): string {
  if (!value) return ''
  const normalized = value.trim().toLowerCase()
  if (isModeLabel(normalized)) return MODE_LABELS[normalized]
  return value.trim()
}

function expectedModeLabel(mode: SessionMode): string {
  return [mode.active_bandwidth, mode.active_intent]
    .flatMap((value) => {
      const label = modeLabel(value)
      return label ? [label] : []
    })
    .join(' · ')
}

async function expectModeChipMatchesBootstrap(page: Page, mode: SessionMode): Promise<void> {
  const label = expectedModeLabel(mode)
  const chip = page.getByTestId('reading-mode-control')

  if (!label) {
    await expect(chip).toHaveCount(0)
    return
  }

  await expect(chip).toBeVisible()
  await expect(chip).toHaveText(label)
  await expect(chip).toHaveAttribute('title', `Reading mode: ${label}`)
}

test.describe('reading-mode acceptance (issue #1734)', () => {
  test('roll header displays the canonical mode returned by Rust v2 bootstrap', async ({
    page,
  }) => {
    await mockRustRollReadApi(page)
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const mode = await getSessionMode(page)
    await expectModeChipMatchesBootstrap(page, mode)
  })

  test('the mode status has no selector or retired session-mode write path', async ({
    page,
  }) => {
    await mockRustRollReadApi(page)
    const retiredWrites: string[] = []
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.pathname === '/api/v1/roll/session-mode') retiredWrites.push(request.method())
    })

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const chip = page.getByTestId('reading-mode-control')
    if (await chip.count()) {
      await expect(chip).not.toHaveAttribute('aria-haspopup', 'dialog')
      expect(
        await chip.evaluate((element) => element.tagName.toLowerCase()),
      ).toBe('span')
    }
    await expect(page.getByTestId('mode-selector-sheet')).toHaveCount(0)
    expect(retiredWrites).toEqual([])
  })

  test('refresh restores the same read-only mode state from bootstrap', async ({
    page,
  }) => {
    await mockRustRollReadApi(page)
    await gotoRollPage(page)
    await waitForRollPageReady(page)
    const before = await getSessionMode(page)
    await expectModeChipMatchesBootstrap(page, before)

    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForRollPageReady(page)

    const after = await getSessionMode(page)
    expect(after).toEqual(before)
    await expectModeChipMatchesBootstrap(page, after)
  })
})
