import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  expect(response.ok()).toBeTruthy()
  // SAFETY: the test reads only csrf_token from the response body
  const data = (await response.json()) as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function authHeaders(page: Page) {
  const token = await getAuthToken(page)
  expect(token).toBeTruthy()
  const csrf = await getCsrf(page, token)
  return {
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
    Authorization: `Bearer ${token}`,
  }
}

async function getFirstIssueId(page: Page, threadId: number): Promise<number> {
  const headers = await authHeaders(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers,
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the test reads only the response fields listed in this type
  const data = (await response.json()) as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues[0].id
}

test.describe('CBL browser catalog folders', () => {
  test('browses nested folders including unsorted and previews a shared source with no owned comics', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)
    const suffix = `${Date.now()}`
    const rootFolder = `Issue4010Nested${suffix}`
    const sourceName = `Nested Shared Order ${suffix}`
    const sourcePath = `${rootFolder}/unsorted/${sourceName}.cbl`
    const comicvineIssueId = `4000-issue4010-${suffix}`

    // No threads or issues are created for this account: the shared catalog
    // preview must not depend on reader-owned comics.
    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `issue-4010-${suffix}`,
        revision_sha: `issue-4010-revision-${suffix}`,
        repository: 'JoshCLWren/CBL-ReadingLists',
        entries: [
          {
            position: 1,
            series_name: 'Nested Shared Series',
            issue_number: '1',
            comicvine_issue_id: comicvineIssueId,
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'CBL Sources' })).toBeVisible()

    // Folders and sources appear immediately; no search submission is needed.
    await page.getByRole('button', { name: new RegExp(rootFolder) }).click()
    await expect(page).toHaveURL(/folder=/)
    await page.getByRole('button', { name: /^unsorted/ }).click()
    await expect(page).toHaveURL(/unsorted/)
    const sourceRow = page.getByRole('button', { name: new RegExp(sourceName) })
    await expect(sourceRow).toBeVisible()

    // Source-only preview: ordered positions plus the exact Comic Vine issue ID.
    await sourceRow.click()
    const detail = page.getByTestId('cbl-source-detail')
    await expect(detail).toBeVisible()
    await expect(detail).toContainText('Nested Shared Series #1')
    await expect(detail).toContainText(comicvineIssueId)
    await expect(page).toHaveURL(/list=/)

    // Back returns to the same nested folder with the folder path preserved.
    await page.getByRole('link', { name: 'Back to results' }).click()
    await expect(page.getByRole('button', { name: new RegExp(sourceName) })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'CBL folder path' })).toContainText(
      'unsorted',
    )
    expect(page.url()).toContain('folder=')
    expect(page.url()).not.toContain('list=')
  })
})

test.describe('CBL browser one-decision adoption', () => {
  test('browse → preview → Add this reading order creates and opens the plan', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const owned = await createThread(page, {
      title: 'Browser Owned Series',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)
    const fixtureSuffix = `${owned.id}-${Date.now()}`
    const sourceName = `Browser One Decision ${fixtureSuffix}`
    const sourcePath = `Fixtures/Browser One Decision ${fixtureSuffix}.cbl`

    // Seed a fully resolved CBL: one existing issue, one safely creatable missing issue.
    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `browser-decision-${fixtureSuffix}`,
        revision_sha: `browser-decision-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Browser Owned Series',
            issue_number: '1',
            issue_id: ownedIssueId,
          },
          {
            position: 2,
            series_name: 'Browser Missing Series',
            issue_number: '1',
            volume_year: 2005,
            comicvine_issue_id: `4000-browser-decision-missing-${fixtureSuffix}`,
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    // Browse to the standalone CBL browser from the Reading Plans index.
    await page.goto('/continuity-plans', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Reading Plans' })).toBeVisible()
    await page.getByRole('button', { name: 'Browse CBL sources' }).click()
    await expect(page).toHaveURL(/\/cbl-sources/)
    await expect(page.getByRole('heading', { name: 'CBL Sources' })).toBeVisible()

    // Search and select the source.
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page
      .getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
      .click()

    // Compact consequence summary: no per-entry decisions required.
    await expect(
      page.getByText('2 entries · 1 already in ComicPile · 1 will be added'),
    ).toBeVisible()
    await expect(page.getByText('/mnt/')).toHaveCount(0)

    // #3939: the default view shows the reader-friendly title, never the raw .cbl path.
    const sourceRow = page.getByRole('button', {
      name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
    })
    await expect(sourceRow).not.toContainText(sourcePath)
    await expect(page.getByRole('heading', { name: sourceName })).toBeVisible()

    // Preview caused no mutation: no Reading Plan exists for this source yet.
    const plansBefore = await page.request.get('/api/v1/continuity-plans/', { headers })
    expect(plansBefore.ok(), await plansBefore.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const plansBeforeJson = (await plansBefore.json()) as Array<{ name: string }>
    expect(plansBeforeJson.some((plan) => plan.name === sourceName)).toBe(false)

    // One decision: Add this reading order, then confirm.
    await expect(page.getByRole('button', { name: 'Add this reading order' })).toBeEnabled()
    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await page.getByRole('button', { name: 'Add reading order' }).click()

    // The resulting Reading Plan opens directly.
    await expect(page).toHaveURL(/\/continuity-plans\/\d+/, { timeout: 60000 })
    const planId = Number(page.url().match(/\/continuity-plans\/(\d+)/)?.[1])
    expect(planId).toBeGreaterThan(0)

    // The plan carries the source name and both entries with CBL provenance.
    const planResponse = await page.request.get(`/api/v1/continuity-plans/${planId}`, {
      headers,
    })
    expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const plan = (await planResponse.json()) as {
      name: string
      nodes: Array<{
        ref_id: number
        label?: string | null
        source_cbl_placements?: Array<{ source_path: string }>
      }>
    }
    expect(plan.name).toBe(sourceName)
    expect(plan.nodes.length).toBe(2)
    expect(plan.nodes[0]?.ref_id).toBe(ownedIssueId)
    expect(plan.nodes.every((node) => (node.label ?? '') && !node.label?.includes('[deleted series]'))).toBe(
      true,
    )
    expect(plan.nodes[0]?.label).toBe('Browser Owned Series #1')
    expect(plan.nodes[1]?.label).toMatch(/Browser Missing Series #1/)
    expect(
      plan.nodes.flatMap((node) =>
        (node.source_cbl_placements ?? []).map((placement) => placement.source_path),
      ),
    ).toEqual([sourcePath, sourcePath])

    // Reload preserves membership and provenance.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText(sourcePath)).toBeVisible()
  })

  test('customize disclosure allows excluding a series before the one-decision add', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const owned = await createThread(page, {
      title: 'Browser Customize Owned',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)
    const fixtureSuffix = `${owned.id}-${Date.now()}`
    const sourceName = `Browser Customize ${fixtureSuffix}`
    const sourcePath = `Fixtures/Browser Customize ${fixtureSuffix}.cbl`

    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `browser-customize-${fixtureSuffix}`,
        revision_sha: `browser-customize-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Browser Customize Owned',
            issue_number: '1',
            issue_id: ownedIssueId,
          },
          {
            position: 2,
            series_name: 'Browser Customize Missing',
            issue_number: '1',
            volume_year: 2006,
            comicvine_issue_id: `4000-browser-customize-missing-${fixtureSuffix}`,
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page
      .getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
      .click()
    await expect(
      page.getByText('2 entries · 1 already in ComicPile · 1 will be added'),
    ).toBeVisible()

    // Progressive disclosure: exclude the missing series, then add.
    await page.getByRole('button', { name: 'Customize', exact: true }).click()
    const missingSeriesChoice = page.getByRole('group', {
      name: 'Browser Customize Missing series choice',
    })
    await missingSeriesChoice.getByRole('button', { name: 'Exclude' }).click()
    await expect(
      page.getByText('2 entries · 1 already in ComicPile · 0 will be added'),
    ).toBeVisible()

    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await page.getByRole('button', { name: 'Add reading order' }).click()
    await expect(page).toHaveURL(/\/continuity-plans\/\d+/, { timeout: 60000 })
    const planId = Number(page.url().match(/\/continuity-plans\/(\d+)/)?.[1])
    expect(planId).toBeGreaterThan(0)

    const planResponse = await page.request.get(`/api/v1/continuity-plans/${planId}`, {
      headers,
    })
    expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const plan = (await planResponse.json()) as { nodes: Array<{ ref_id: number }> }
    expect(plan.nodes.length).toBe(1)
    expect(plan.nodes[0]?.ref_id).toBe(ownedIssueId)
  })

  test('owned issues can be excluded individually without leaving ComicPile', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const owned = await createThread(page, {
      title: 'Browser Owned Exclude',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)
    const fixtureSuffix = `${owned.id}-${Date.now()}`
    const sourceName = `Browser Owned Exclude ${fixtureSuffix}`
    const sourcePath = `Fixtures/Browser Owned Exclude ${fixtureSuffix}.cbl`

    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `browser-owned-exclude-${fixtureSuffix}`,
        revision_sha: `browser-owned-exclude-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Browser Owned Exclude',
            issue_number: '1',
            issue_id: ownedIssueId,
          },
          {
            position: 2,
            series_name: 'Browser Missing Keep',
            issue_number: '1',
            volume_year: 2007,
            comicvine_issue_id: `4000-browser-owned-exclude-missing-${fixtureSuffix}`,
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page
      .getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
      .click()
    await page.getByRole('button', { name: 'Customize', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Include Browser Owned Exclude #1' }).uncheck()
    await expect(
      page.getByText('2 entries · 0 already in ComicPile · 1 will be added'),
    ).toBeVisible()

    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await page.getByRole('button', { name: 'Add reading order' }).click()
    await expect(page).toHaveURL(/\/continuity-plans\/\d+/, { timeout: 60000 })
    const planId = Number(page.url().match(/\/continuity-plans\/(\d+)/)?.[1])
    expect(planId).toBeGreaterThan(0)

    const planResponse = await page.request.get(`/api/v1/continuity-plans/${planId}`, {
      headers,
    })
    expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const plan = (await planResponse.json()) as { nodes: Array<{ ref_id: number }> }
    expect(plan.nodes.map((node) => node.ref_id)).not.toContain(ownedIssueId)
    expect(plan.nodes.length).toBe(1)

    const ownedIssue = await page.request.get(`/api/v1/threads/${owned.id}/issues`, { headers })
    expect(ownedIssue.ok(), await ownedIssue.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const ownedJson = (await ownedIssue.json()) as { issues: Array<{ id: number }> }
    expect(ownedJson.issues.some((issue) => issue.id === ownedIssueId)).toBe(true)
  })

  test('cancel on the confirm step creates no Reading Plan', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const owned = await createThread(page, {
      title: 'Browser Abort Owned',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)
    const fixtureSuffix = `${owned.id}-${Date.now()}`
    const sourceName = `Browser Abort ${fixtureSuffix}`
    const sourcePath = `Fixtures/Browser Abort ${fixtureSuffix}.cbl`

    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `browser-abort-${fixtureSuffix}`,
        revision_sha: `browser-abort-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Browser Abort Owned',
            issue_number: '1',
            issue_id: ownedIssueId,
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page
      .getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
      .click()
    await expect(page.getByText(/1 entry · 1 already in ComicPile/)).toBeVisible()

    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
    await expect(page).toHaveURL(/\/cbl-sources/)

    const plansAfter = await page.request.get('/api/v1/continuity-plans/', { headers })
    expect(plansAfter.ok(), await plansAfter.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const plansAfterJson = (await plansAfter.json()) as Array<{ name: string }>
    expect(plansAfterJson.some((plan) => plan.name === sourceName)).toBe(false)
  })
})
