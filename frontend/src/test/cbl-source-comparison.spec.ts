import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

/**
 * Browser evidence for #4012: Find CBLs from a comic and a Reading List,
 * ranked by exact Comic Vine identity coverage and source order.
 */

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

async function threadIssueIds(page: Page, headers: Record<string, string>, threadId: number) {
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, { headers })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the test reads only the issue ids listed in this type
  const data = (await response.json()) as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues.map((issue) => issue.id)
}

/**
 * Confirm the deterministic synthetic Comic Vine identity used by the
 * test-only issue-identity helper.
 */
function confirmedComicvineIssueId(issueId: number): string {
  return `4000-${900_000_000 + issueId}`
}

interface SeedEntry {
  series_name: string
  issue_number: string
  comicvine_issue_id: string
}

async function seedSource(
  page: Page,
  headers: Record<string, string>,
  name: string,
  entries: SeedEntry[],
): Promise<{ id: number }> {
  const suffix = `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
  const response = await page.request.post('/api/test/cbl-source', {
    headers,
    data: {
      name,
      source_path: `Fixtures/${name}.cbl`,
      content_hash: `hash-${suffix}`,
      revision_sha: `revision-${suffix}`,
      repository: `JoshCLWren/CBL-ReadingLists-fixture-${suffix}`,
      entries: entries.map((entry, index) => ({ position: index + 1, ...entry })),
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: successful source seeding returns the numeric list id read here
  return (await response.json()) as { id: number }
}

async function createReadingPlan(
  page: Page,
  headers: Record<string, string>,
  name: string,
): Promise<{ id: number }> {
  const response = await page.request.post('/api/v1/continuity-plans/', {
    headers,
    data: { name, lanes: [{ id: 'main', name: 'Main', order: 0 }], nodes: [] },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: successful plan creation returns the numeric plan id read here
  return (await response.json()) as { id: number }
}

test.describe('Find CBLs from a comic', () => {
  test('opens ranked source detail and returns to the series', async ({
    authenticatedPage: page,
  }) => {
    const headers = await authHeaders(page)
    const suffix = `${Date.now()}`
    const thread = await createThread(page, {
      title: `CBL Comic Series ${suffix}`,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const [issueId] = await threadIssueIds(page, headers, thread.id)
    const comicvineIssueId = confirmedComicvineIssueId(issueId)

    // The comic's own confirmed identity comes from the test helper, not from
    // any CBL membership.
    const identity = await page.request.post('/api/test/issue-identity', {
      headers,
      data: { issue_id: issueId, series_name: `CBL Comic Series ${suffix}` },
    })
    expect(identity.ok(), await identity.text()).toBeTruthy()

    const first = await seedSource(page, headers, `Comic Source One ${suffix}`, [
      {
        series_name: `CBL Comic Series ${suffix}`,
        issue_number: '1',
        comicvine_issue_id: comicvineIssueId,
      },
    ])
    const second = await seedSource(page, headers, `Comic Source Two ${suffix}`, [
      {
        series_name: 'Unrelated Crossover',
        issue_number: '1',
        comicvine_issue_id: `4000-unrelated-${suffix}`,
      },
      {
        series_name: `CBL Comic Series ${suffix}`,
        issue_number: '1',
        comicvine_issue_id: comicvineIssueId,
      },
    ])

    await page.goto(`/thread/${thread.id}`, { waitUntil: 'domcontentloaded' })
    // Each issue row carries its own "Find CBLs" action, so the series issue
    // list has to be expanded before the comic action exists.
    await page.getByRole('button', { name: 'Expand', exact: true }).click()
    const open = page.getByTestId(`cbl-comic-${issueId}-open`)
    await expect(open).toBeVisible()
    await open.click()

    await expect(page.getByRole('heading', { name: `CBLs containing CBL Comic Series ${suffix} #1` })).toBeVisible()
    const firstCandidate = page.getByTestId(`cbl-comic-${issueId}-${first.id}`)
    const secondCandidate = page.getByTestId(`cbl-comic-${issueId}-${second.id}`)
    await expect(firstCandidate).toContainText('Score 100 of 100')
    await expect(firstCandidate).toContainText('Coverage: 1 of 1 comics (100%)')
    // A single input comic cannot form an order pair, so the server reports
    // the order as not comparable rather than claiming a matching order.
    await expect(firstCandidate).toContainText('Order not comparable')
    // The second source holds two distinct comics and matches only one, so
    // source coverage is 1 of 2 (50%) and the score is 55 + 12.5 + 20.
    await expect(secondCandidate).toContainText('Score 88 of 100')
    await expect(secondCandidate).toContainText(
      '1 source comic is not in this list',
    )

    await firstCandidate.getByRole('link', { name: /View source list/ }).click()
    await expect(page).toHaveURL(new RegExp(`/cbl-sources\\?list=${first.id}`))
    const detail = page.getByTestId('cbl-source-detail')
    await expect(detail).toContainText(`Comic Source One ${suffix}`)
    await expect(detail).toContainText(`CBL Comic Series ${suffix} #1`)
    await expect(detail).toContainText(comicvineIssueId)

    await detail.getByRole('link', { name: 'Back to Series' }).click()
    await expect(page).toHaveURL(new RegExp(`/thread/${thread.id}`))
  })
})

test.describe('Find CBLs from a Reading List', () => {
  test('scores distinct coverage and order without owning the compared sources', async ({
    authenticatedPage: page,
  }) => {
    const headers = await authHeaders(page)
    const suffix = `${Date.now()}`
    const seriesNames = [
      `CBL List Alpha ${suffix}`,
      `CBL List Beta ${suffix}`,
      `CBL List Gamma ${suffix}`,
    ]
    const issueIds: number[] = []
    for (const title of seriesNames) {
      const thread = await createThread(page, {
        title,
        format: 'Comics',
        issues_remaining: 1,
        total_issues: 1,
      })
      const [issueId] = await threadIssueIds(page, headers, thread.id)
      issueIds.push(issueId)
      const identity = await page.request.post('/api/test/issue-identity', {
        headers,
        data: { issue_id: issueId, series_name: title },
      })
      expect(identity.ok(), await identity.text()).toBeTruthy()
    }

    // A fourth entry deliberately has no confirmed Comic Vine identity so the
    // UI must report the identity gap instead of an empty "no CBL" claim.
    const gapThread = await createThread(page, {
      title: `CBL List Unconfirmed ${suffix}`,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const [gapIssueId] = await threadIssueIds(page, headers, gapThread.id)

    const [alpha, beta, gamma] = issueIds.map(confirmedComicvineIssueId)
    const alphaTitle = seriesNames[0]
    const betaTitle = seriesNames[1]
    const gammaTitle = seriesNames[2]

    const same = await seedSource(page, headers, `Source Same Order ${suffix}`, [
      { series_name: alphaTitle, issue_number: '1', comicvine_issue_id: alpha },
      { series_name: betaTitle, issue_number: '1', comicvine_issue_id: beta },
      { series_name: gammaTitle, issue_number: '1', comicvine_issue_id: gamma },
    ])
    const duplicate = await seedSource(page, headers, `Source Duplicate ${suffix}`, [
      { series_name: alphaTitle, issue_number: '1', comicvine_issue_id: alpha },
      { series_name: alphaTitle, issue_number: '1', comicvine_issue_id: alpha },
      { series_name: betaTitle, issue_number: '1', comicvine_issue_id: beta },
    ])
    const reordered = await seedSource(page, headers, `Source Reordered ${suffix}`, [
      { series_name: gammaTitle, issue_number: '1', comicvine_issue_id: gamma },
      { series_name: alphaTitle, issue_number: '1', comicvine_issue_id: alpha },
      { series_name: betaTitle, issue_number: '1', comicvine_issue_id: beta },
    ])
    // Same title and issue number as the first comic, different volume: exact
    // Comic Vine identity only, so this source must never be a candidate.
    const otherVolume = await seedSource(page, headers, `Source Other Volume ${suffix}`, [
      {
        series_name: alphaTitle,
        issue_number: '1',
        comicvine_issue_id: `4000-other-volume-${suffix}`,
      },
    ])

    const createdList = await page.request.post('/api/v1/custom-cbls', {
      headers,
      data: {
        name: `CBL Finder Reading List ${suffix}`,
        mode: 'loose',
        issue_ids: [...issueIds, gapIssueId],
      },
    })
    expect(createdList.ok(), await createdList.text()).toBeTruthy()
    // SAFETY: successful list creation returns the numeric list id read here
    const list = (await createdList.json()) as { id: number }
    const plan = await createReadingPlan(page, headers, `CBL Finder Plan ${suffix}`)

    await page.goto(`/continuity-plans/${plan.id}/edit`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Create or edit custom CBL', exact: true }).click()
    await page.getByRole('combobox', { name: 'Custom CBL', exact: true }).selectOption(String(list.id))
    await page.getByRole('button', { name: 'Read this list', exact: true }).click()

    const listReader = page.getByRole('region', { name: `Read CBL Finder Reading List ${suffix}` })
    const finder = page.getByTestId('cbl-reading-list-open')
    await expect(finder).toBeVisible()
    await finder.click()

    await expect(page.getByTestId('cbl-reading-list-gap-summary')).toHaveText(
      'Coverage uses the 3 confirmed Comic Vine issues. 1 entry has no confirmed ID and 0 entries have conflicting IDs.',
    )

    const sameRow = page.getByTestId(`cbl-reading-list-${same.id}`)
    const duplicateRow = page.getByTestId(`cbl-reading-list-${duplicate.id}`)
    const reorderedRow = page.getByTestId(`cbl-reading-list-${reordered.id}`)
    await expect(sameRow).toContainText('Score 100 of 100')
    await expect(sameRow).toContainText('Coverage: 3 of 3 comics (100%)')
    await expect(sameRow).toContainText('Same relative order')
    await expect(duplicateRow).toContainText('Score 82 of 100')
    await expect(duplicateRow).toContainText('Coverage: 2 of 3 comics (67%)')
    await expect(duplicateRow).toContainText('Source coverage: 100% of this source\'s 2 comics')
    await expect(duplicateRow).toContainText('Same relative order')
    await expect(duplicateRow).toContainText('1 duplicate source position counts once')
    await expect(reorderedRow).toContainText('Score 87 of 100')
    await expect(reorderedRow).toContainText('Reordered: 2 of 3 comic pairs differ')
    await expect(page.getByTestId(`cbl-reading-list-${otherVolume.id}`)).toHaveCount(0)
    await expect(listReader).not.toContainText(`Source Other Volume ${suffix}`)

    // Ranking places the exact same-order source first, then the reordered
    // source, then the duplicate source.
    const rankedNames = await page
      .locator('[data-testid^="cbl-reading-list-"] h5')
      .allTextContents()
    expect(rankedNames.slice(0, 3)).toEqual([
      `Source Same Order ${suffix}`,
      `Source Reordered ${suffix}`,
      `Source Duplicate ${suffix}`,
    ])

    await reorderedRow.getByRole('link', { name: /View source list/ }).click()
    await expect(page).toHaveURL(new RegExp(`/cbl-sources\\?list=${reordered.id}`))
    const detail = page.getByTestId('cbl-source-detail')
    await expect(detail).toContainText(`Source Reordered ${suffix}`)
    await expect(detail).toContainText(`${gammaTitle} #1`)
    await expect(detail).toContainText('Back to Reading Plans')
    await detail.getByRole('link', { name: 'Back to Reading Plans' }).click()
    await expect(page).toHaveURL(new RegExp(`/continuity-plans/${plan.id}`))
  })
})
