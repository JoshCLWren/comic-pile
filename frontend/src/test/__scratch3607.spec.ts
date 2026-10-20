/**
 * SCRATCH reproduction for issue #3607 (not for commit).
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
  readCount: number,
): Promise<number> {
  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrfToken,
  }
  const res = await request.post('/api/threads/', {
    headers,
    data: {
      title,
      format: 'issue',
      issues_remaining: issueCount - readCount,
      total_issues: issueCount,
    },
  })
  expect(res.ok(), `thread create ${title}: ${await res.text()}`).toBeTruthy()
  const thread = await res.json()
  const issueRes = await request.post(`/api/v1/threads/${thread.id}/issues`, {
    headers,
    data: { issue_range: `1-${issueCount}` },
  })
  expect(issueRes.ok(), `issue create ${title}`).toBeTruthy()

  // Mark the first `readCount` issues as read.
  const list = await request.get(`/api/v1/threads/${thread.id}/issues`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const listBody = await list.json()
  for (const issue of (listBody.issues as Array<{ id: number }>).slice(0, readCount)) {
    const mark = await request.post(`/api/v1/issues/${issue.id}:markRead`, {
      headers: { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrfToken },
    })
    expect(mark.ok(), `markRead ${issue.id}`).toBeTruthy()
  }
  return thread.id
}

async function dumpIssueSelect(page: Page, tag: string) {
  const state = await page.evaluate(() => {
    const selects = Array.from(document.querySelectorAll('select'))
    const target = selects.find((s) => {
      const label = s.closest('label')
      return label?.textContent?.trim().toLowerCase().startsWith('issue')
    })
    if (!target) return { found: false }
    return {
      found: true,
      disabled: (target as HTMLSelectElement).disabled,
      ariaBusy: target.getAttribute('aria-busy'),
      optionCount: target.options.length,
      optionLabels: Array.from(target.options).map((o) => o.textContent),
      optionDisabled: Array.from(target.options).map((o) => o.disabled),
      outer: target.outerHTML.slice(0, 700),
    }
  })
  console.log(`\n### ${tag}\n` + JSON.stringify(state, null, 2))
  return state
}

test('scratch #3607 editor repro with partially-read series', async ({ page, request }) => {
  const counter = Date.now()
  const username = `scratch3607b_${counter}`
  const password = 'TestPass123!'
  const reg = await request.post('/api/auth/register', {
    data: { username, email: `${username}@example.com`, password },
  })
  expect(reg.ok()).toBeTruthy()
  const login = await request.post('/api/auth/login', { data: { username, password } })
  expect(login.ok()).toBeTruthy()
  const { access_token: accessToken } = await login.json()
  const csrfToken = await csrf(request, accessToken)

  // Beta: 3 total, 2 read -> "1 remaining · 3 total"
  await makeSeries(request, accessToken, csrfToken, 'Order Test Beta', 3, 2)
  // Alpha: 6 total, 2 read -> "4 remaining · 6 total"
  await makeSeries(request, accessToken, csrfToken, 'Order Test Alpha', 6, 2)

  const planRes = await request.post('/api/v1/continuity-plans/', {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    data: {
      name: 'Scratch plan',
      ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [],
    },
  })
  expect(planRes.ok(), `plan create: ${await planRes.text()}`).toBeTruthy()
  const plan = await planRes.json()

  await page.addInitScript((token: string) => {
    localStorage.setItem('auth_token', token)
    ;(window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN = token
  }, accessToken)

  await page.goto(`/continuity-plans/${plan.id}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: /Edit/ })).toBeVisible({ timeout: 20000 })

  const search = page.getByRole('searchbox', { name: 'Comic series' })
  await search.fill('Order Test Beta')
  await page.getByRole('option', { name: /Order Test Beta/ }).click()
  await page.waitForTimeout(1500)
  await dumpIssueSelect(page, 'EDIT after Beta (1 remaining / 3 total)')
  console.log('Selected series readout:', await page.getByTestId('selected-thread-title').textContent())

  const issueSelect = page.getByRole('combobox', { name: 'Issue' })
  const addIssueButton = page.getByRole('button', { name: 'Add issue' })
  console.log('Add issue disabled (before pick):', await addIssueButton.isDisabled())

  // Real mouse-driven selection: click the select and pick an option.
  try {
    await issueSelect.selectOption({ index: 1 })
    console.log('selectOption(index 1) OK')
  } catch (e) {
    console.log('selectOption FAILED:', String(e).slice(0, 300))
  }
  await page.waitForTimeout(500)
  await dumpIssueSelect(page, 'EDIT after picking an issue')
  console.log('Add issue disabled (after pick):', await addIssueButton.isDisabled())

  if (!(await addIssueButton.isDisabled())) {
    await addIssueButton.click()
    await page.waitForTimeout(500)
    console.log('lane content:', await page.getByTestId('lane-main').textContent())
  }

  // Switch series
  await search.fill('Order Test Alpha')
  await page.getByRole('option', { name: /Order Test Alpha/ }).click()
  await page.waitForTimeout(1500)
  await dumpIssueSelect(page, 'EDIT after Alpha (4 remaining / 6 total)')
  console.log('Selected series readout:', await page.getByTestId('selected-thread-title').textContent())
  console.log('Add issue disabled (after Alpha):', await addIssueButton.isDisabled())
})
