/**
 * Reading-mode acceptance: the Roll header reads the canonical scoped resource.
 * No Bootstrap or reading-session initialization request is permitted.
 */
import { expect, test, type Page } from '@playwright/test'
import { gotoRollPage, waitForRollPageReady } from './helpers'

type ReadingMode = {
  bandwidth: string | null
  intent: string | null
  source: string | null
  suggested: boolean
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

async function getReadingMode(page: Page): Promise<ReadingMode> {
  return page.evaluate(async () => {
    const token = localStorage.getItem('auth_token') ?? ''
    const response = await fetch('/api/v2/reading-mode', {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) throw new Error(`Reading mode failed: ${response.status}`)
    return response.json() as Promise<ReadingMode>
  })
}

async function mockScopedRollReadApi(page: Page): Promise<void> {
  await page.addInitScript(() => localStorage.setItem('auth_token', 'test-access-token'))
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/v2/auth/me') {
      return route.fulfill({ json: {
        id: 1,
        username: 'reader',
        email: 'reader@example.test',
        preferences: { theme: 'classic' },
      } })
    }
    if (path === '/api/v2/auth/refresh') {
      return route.fulfill({ json: { access_token: 'test-access-token' } })
    }
    if (path === '/api/v2/auth/csrf') {
      return route.fulfill({ json: { csrf_token: 'test-csrf' } })
    }
    if (path === '/api/v2/reading-mode') {
      return route.fulfill({ json: {
        bandwidth: 'balanced',
        intent: 'explore',
        source: 'manual',
        suggested: false,
      } })
    }
    if (path === '/api/v2/roll/die-state') {
      return route.fulfill({ json: {
        die: 6,
        ladder: [2, 4, 6, 8, 10, 12, 20],
        default_die: 6,
        last_roll: null,
      } })
    }
    if (path === '/api/v2/roll/eligible-issue-ids') {
      return route.fulfill({ json: { die: 6, issue_ids: [], thread_ids: [], pool_reason: 'no_series' } })
    }
    if (path === '/api/v2/roll/last-read') return route.fulfill({ json: null })
    if (path === '/api/v2/threads') {
      return route.fulfill({ json: { threads: [], next_page_token: null, active_count: 0 } })
    }
    if (path === '/api/v2/reading-graph') {
      return route.fulfill({ json: { status: 'ok', cycles: [], invalid_edges: [] } })
    }
    return route.fulfill({ json: [] })
  })
}

function modeLabel(value: string | null): string {
  if (!value) return ''
  const normalized = value.trim().toLowerCase()
  return Object.hasOwn(MODE_LABELS, normalized)
    ? MODE_LABELS[normalized as keyof typeof MODE_LABELS]
    : value.trim()
}

async function expectModeChip(page: Page, mode: ReadingMode): Promise<void> {
  const label = [modeLabel(mode.bandwidth), modeLabel(mode.intent)].filter(Boolean).join(' · ')
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
  test('roll header displays the canonical scoped mode without retired requests', async ({ page }) => {
    const retired: string[] = []
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname
      if (path === '/api/v2/roll/bootstrap' || path === '/api/v2/readingSessions') {
        retired.push(`${request.method()} ${path}`)
      }
    })
    await mockScopedRollReadApi(page)
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await expectModeChip(page, await getReadingMode(page))
    expect(retired).toEqual([])
  })

  test('the mode status has no selector or retired session-mode write path', async ({ page }) => {
    await mockScopedRollReadApi(page)
    const retiredWrites: string[] = []
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.pathname === '/api/v1/roll/session-mode') retiredWrites.push(request.method())
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const chip = page.getByTestId('reading-mode-control')
    await expect(chip).not.toHaveAttribute('aria-haspopup', 'dialog')
    expect(await chip.evaluate((element) => element.tagName.toLowerCase())).toBe('span')
    await expect(page.getByTestId('mode-selector-sheet')).toHaveCount(0)
    expect(retiredWrites).toEqual([])
  })

  test('refresh restores the same read-only mode from the scoped resource', async ({ page }) => {
    await mockScopedRollReadApi(page)
    await gotoRollPage(page)
    await waitForRollPageReady(page)
    const before = await getReadingMode(page)
    await expectModeChip(page, before)

    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForRollPageReady(page)
    expect(await getReadingMode(page)).toEqual(before)
    await expectModeChip(page, before)
  })
})
