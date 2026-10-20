/**
 * SCRATCH probe for issue #3607 (not for commit).
 */
import { expect, test } from './fixtures'
import type { APIRequestContext, Page } from '@playwright/test'

async function csrf(request: APIRequestContext, token: string): Promise<string> {
  const res = await request.get('/api/auth/csrf', { headers: { Authorization: `Bearer ${token}` } })
  const body = await res.json()
  return body.csrf_token as string
}

async function makeSeries(
  request: APIRequestContext,
  token: string,
  csrfToken: string,
  title: string,
  issueCount: number,
): Promise<number> {
  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrfToken,
  }
  const res = await request.post('/api/threads/', {
    headers,
    data: { title, format: 'issue', issues_remaining: issueCount, total_issues: issueCount },
  })
  expect(res.ok()).toBeTruthy()
  const thread = await res.json()
  if (issueCount > 0) {
    const issueRes = await request.post(`/api/v1/threads/${thread.id}/issues`, {
      headers,
      data: { issue_range: `1-${issueCount}` },
    })
    expect(issueRes.ok()).toBeTruthy()
  }
  return thread.id
}

async function dump(page: Page, tag: string) {
  const state = await page.evaluate(() => {
    const selects = Array.from(document.querySelectorAll('select'))
    const target = selects.find((s) => s.closest('label')?.textContent?.trim().toLowerCase().startsWith('issue'))
    const addIssue = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Add issue',
    ) as HTMLButtonElement | undefined
    return {
      found: !!target,
      disabled: target ? (target as HTMLSelectElement).disabled : null,
      ariaBusy: target?.getAttribute('aria-busy'),
      optionCount: target?.options.length ?? 0,
      optionDisabled: target ? Array.from(target.options).map((o) => o.disabled) : [],
      optionLabels: target ? Array.from(target.options).map((o) => o.textContent) : [],
      addIssueDisabled: addIssue ? addIssue.disabled : null,
      statusText: document.querySelector('[role="status"]')?.textContent ?? null,
    }
  })
  console.log(`\n### ${tag}\n` + JSON.stringify(state))
  return state
}

test('scratch #3607 probe: empty-issue series, slow load, dirty plan, zero-lane plan', async ({
  page,
  request,
}) => {
  const counter = Date.now()
  const username = `scratch3607c_${counter}`
  const password = 'TestPass123!'
  await request.post('/api/auth/register', {
    data: { username, email: `${username}@example.com`, password },
  })
  const login = await request.post('/api/auth/login', { data: { username, password } })
  const { access_token: accessToken } = await login.json()
  const csrfToken = await csrf(request, accessToken)

  await makeSeries(request, accessToken, csrfToken, 'Series With Issues', 4)
  await makeSeries(request, accessToken, csrfToken, 'Series No Issues', 1)

  // Plan with zero lanes
  const planRes = await request.post('/api/v1/continuity-plans/', {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    data: { name: 'Zero lane plan', ordering_mode: 'informational', lanes: [], nodes: [] },
  })
  console.log('zero-lane plan create status:', planRes.status(), (await planRes.text()).slice(0, 300))
  const plan = await planRes.ok() ? await planRes.json() : { id: 0 }

  await page.addInitScript((token: string) => {
    localStorage.setItem('auth_token', token)
    ;(window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN = token
  }, accessToken)

  // ---- 1. zero-lane plan ----
  if (plan.id) {
    await page.goto(`/continuity-plans/${plan.id}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: /Edit/ })).toBeVisible({ timeout: 20000 })
    const search = page.getByRole('searchbox', { name: 'Comic series' })
    await search.fill('Series With Issues')
    await page.getByRole('option', { name: /Series With Issues/ }).click()
    await page.waitForTimeout(1500)
    await dump(page, 'ZERO-LANE PLAN, series with issues')
  }

  // ---- 2. series with no issues ----
  await page.goto('/continuity-plans/new', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'New Reading Plan' })).toBeVisible({ timeout: 20000 })
  const search2 = page.getByRole('searchbox', { name: 'Comic series' })
  await search2.fill('Series No Issues')
  await page.getByRole('option', { name: /Series No Issues/ }).click()
  await page.waitForTimeout(1500)
  await dump(page, 'SERIES WITH NO ISSUES')

  // ---- 3. slow load race: intercept the issues API and delay it ----
  await page.route('**/api/v1/threads/*/issues*', async (route) => {
    await new Promise((r) => setTimeout(r, 4000))
    await route.continue()
  })
  const search3 = page.getByRole('searchbox', { name: 'Comic series' })
  await search3.fill('Series With Issues')
  await page.getByRole('option', { name: /Series With Issues/ }).click()
  await page.waitForTimeout(800)
  await dump(page, 'DURING SLOW LOAD (800ms in)')
  await page.waitForTimeout(5000)
  await dump(page, 'AFTER SLOW LOAD')

  // ---- 4. keyboard selection of an issue ----
  const issueSelect = page.getByRole('combobox', { name: 'Issue' })
  await issueSelect.focus()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(300)
  await dump(page, 'AFTER KEYBOARD PICK')

  // ---- 5. dirty plan ----
  await page.getByRole('button', { name: 'Add issue' }).click()
  await page.waitForTimeout(300)
  await dump(page, 'AFTER ADD ISSUE (dirty plan)')
})
