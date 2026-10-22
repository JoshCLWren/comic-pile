import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'
import {
  MISTER_MIRACLE_OVERLAP,
  SECOND_MISTER_MIRACLE_OVERLAP,
  afterContinuingChoice,
  readingGraphPreview,
  withSavedChoice,
  withoutOverlap,
} from '../unit/readingGraphFixture'
import type { ReadingGraphOverlapChoiceId } from '../services/api-reading-graph'

/**
 * Browser acceptance for #4020: the reader resolves the #1615 Mister
 * Miracle/JLI overlap one exact Comic Vine volume at a time, sees the graph
 * update before saving, and gets the saved decision back when the source is
 * reopened.
 *
 * The reading-graph preview endpoint belongs to #4019 (still open), so these
 * tests intercept that one request with the server-shaped fixtures from the
 * component suite. Every other request — source search, adoption preview,
 * commit, and plan reload — hits the real backend, so the production page and
 * its commit path are exercised end to end.
 */

interface SeedEntry {
  position: number
  series_name: string
  issue_number: string
  issue_id?: number
  volume_year?: number
  comicvine_issue_id?: string
}

interface SeedSource {
  id: number
  name: string
}

/** The saved overlap answer the fake server must remember between page loads. */
interface SavedOverlapAnswer {
  saved: ReadingGraphOverlapChoiceId | null
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

async function authHeaders(page: Page) {
  const token = await getAuthToken(page)
  expect(token).toBeTruthy()
  const csrfResponse = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  expect(csrfResponse.ok()).toBeTruthy()
  // SAFETY: only csrf_token is read from the response.
  const csrf = (await csrfResponse.json()) as { csrf_token?: string }
  expect(csrf.csrf_token).toBeDefined()
  return {
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf.csrf_token!,
    Authorization: `Bearer ${token}`,
  }
}

async function getFirstIssueId(page: Page, threadId: number): Promise<number> {
  const headers = await authHeaders(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, { headers })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: only issue IDs are read from the response.
  const data = (await response.json()) as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues[0].id
}

async function seedSource(
  page: Page,
  headers: Record<string, string>,
  name: string,
  entries: SeedEntry[],
): Promise<SeedSource> {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const response = await page.request.post('/api/test/cbl-source', {
    headers,
    data: {
      name,
      source_path: `Fixtures/${name}.cbl`,
      content_hash: `overlap-browser-${suffix}`,
      revision_sha: `overlap-browser-revision-${suffix}`,
      repository: `JoshCLWren/CBL-ReadingLists-fixture-${suffix}`,
      entries,
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the fixture endpoint returns the persisted source identity.
  return (await response.json()) as SeedSource
}

async function searchAndSelect(page: Page, name: string): Promise<void> {
  await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'CBL Sources' })).toBeVisible()
  await page.getByLabel('Search source lists').fill(name)
  await page.getByRole('button', { name: 'Search' }).click()
  await page.getByRole('button', { name: new RegExp(escapeRegExp(name)) }).first().click()
}

test.describe('#4020 reading-graph overlap decisions', () => {
  test('resolves the Mister Miracle/JLI overlap and restores it on reopen', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)
    const owned = await createThread(page, {
      title: 'Overlap Browser Owned',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)
    const sourceName = `Overlap Browser ${owned.id}-${Date.now()}`
    const source = await seedSource(page, headers, sourceName, [
      {
        position: 1,
        series_name: 'Overlap Browser Owned',
        issue_number: '1',
        issue_id: ownedIssueId,
      },
      {
        position: 2,
        series_name: 'Overlap Browser Missing',
        issue_number: '1',
        volume_year: 2005,
        comicvine_issue_id: `4000-overlap-browser-missing-${owned.id}-${Date.now()}`,
      },
    ])

    // The server remembers the reader's answer only once the commit succeeds,
    // and returns that saved decision the next time the source is opened. The
    // preview mock stays read-only so a commit that drops `overlap_decisions`
    // cannot still pass this test.
    const state: SavedOverlapAnswer = { saved: null }
    await page.route('**/v1/issue-identity/cbl/*/reading-graph-preview', async (route) => {
      // SAFETY: the page always posts the typed preview request.
      const request = (route.request().postDataJSON() ?? {}) as {
        overlap_choices?: Array<{ choice: ReadingGraphOverlapChoiceId }>
      }
      const answered =
        request.overlap_choices?.some((entry) => entry.choice === 'continue_series') ?? false
      const payload = answered
        ? afterContinuingChoice()
        : state.saved
          ? withSavedChoice(state.saved)
          : readingGraphPreview()
      await route.fulfill({ json: { ...payload, source_list_id: source.id } })
    })
    await page.route('**/v1/cbl/*/adoption-commit', async (route) => {
      // SAFETY: the page always posts the typed commit payload.
      const request = (route.request().postDataJSON() ?? {}) as {
        overlap_decisions?: Array<{
          overlap_id: string
          choice: ReadingGraphOverlapChoiceId
        }>
      }
      const response = await route.fetch()
      const committed =
        response.ok() &&
        (request.overlap_decisions ?? []).some(
          (decision) =>
            decision.overlap_id === MISTER_MIRACLE_OVERLAP.overlap_id &&
            decision.choice === 'continue_series',
        )
      if (committed) state.saved = 'continue_series'
      await route.fulfill({ response })
    })

    await searchAndSelect(page, sourceName)

    // Before the answer: the graph names the waiting volume and the held comic.
    const summary = page.getByTestId('reading-graph-summary')
    await expect(summary).toBeVisible()
    await expect(summary).toContainText('3 series · 1 rollable · 4 waiting')
    await expect(summary).toContainText('Mister Miracle (1989)')
    await expect(summary).toContainText('Waits for Fourth World #2')
    await expect(summary).toContainText('Needs a decision before saving')

    // Adding routes through the series questionnaire instead of the confirm dialog.
    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await expect(
      page.getByRole('heading', { name: 'Resolve overlapping series' }),
    ).toBeVisible()
    await expect(
      page.getByTestId('reading-graph-overlap-dialog').getByText('Overlap 1 of 1'),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', {
        name: 'Should Justice League International (1987) continue while Mister Miracle (1989) waits?',
      }),
    ).toBeVisible()

    const continuing = page.getByRole('radio', {
      name: /Mister Miracle waits; JLI continues/,
    })
    await expect(continuing).toContainText('Keeps rolling: Justice League International #2')
    await expect(continuing).toContainText(
      'Still waits: Mister Miracle #1, Mister Miracle #2, Justice League International #3',
    )
    await continuing.click()

    // After the answer: the server-shaped graph reports the new per-volume state.
    await expect(summary).toContainText('Mister Miracle waits; JLI continues')
    await expect(summary).toContainText('3 series · 2 rollable · 3 waiting')

    await page.getByRole('button', { name: 'Use these choices' }).click()
    await expect(
      page.getByRole('heading', { name: 'Add this reading order?' }),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Resolve overlapping series' }),
    ).toHaveCount(0)

    await page.getByRole('button', { name: 'Add reading order' }).click()
    await expect(page).toHaveURL(/\/continuity-plans\/\d+/, { timeout: 60000 })

    // Reopen the same source in a fresh document: the decision does not ask again.
    await searchAndSelect(page, sourceName)
    const reopened = page.getByTestId('reading-graph-summary')
    await expect(reopened).toBeVisible()
    await expect(reopened).toContainText('Mister Miracle waits; JLI continues')
    await expect(reopened).not.toContainText('Needs a decision before saving')
    await expect(
      page.getByRole('button', { name: 'Review series decisions' }),
    ).toBeVisible()

    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await expect(
      page.getByRole('heading', { name: 'Add this reading order?' }),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Resolve overlapping series' }),
    ).toHaveCount(0)
  })

  test('asks about same-named volumes separately, never one whole-CBL choice', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)
    const owned = await createThread(page, {
      title: 'Overlap Volume Scope Owned',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)
    const sourceName = `Overlap Volume Scope ${owned.id}-${Date.now()}`
    const source = await seedSource(page, headers, sourceName, [
      {
        position: 1,
        series_name: 'Overlap Volume Scope Owned',
        issue_number: '1',
        issue_id: ownedIssueId,
      },
      {
        position: 2,
        series_name: 'Overlap Volume Scope Missing',
        issue_number: '1',
        volume_year: 2007,
        comicvine_issue_id: `4000-overlap-volume-missing-${owned.id}-${Date.now()}`,
      },
    ])

    await page.route('**/v1/issue-identity/cbl/*/reading-graph-preview', (route) =>
      route.fulfill({
        json: {
          ...readingGraphPreview({
            overlaps: [MISTER_MIRACLE_OVERLAP, SECOND_MISTER_MIRACLE_OVERLAP],
          }),
          source_list_id: source.id,
        },
      }),
    )

    await searchAndSelect(page, sourceName)
    await page.getByRole('button', { name: 'Add this reading order' }).click()

    await expect(
      page.getByRole('heading', { name: 'Resolve overlapping series' }),
    ).toBeVisible()
    await expect(
      page.getByTestId('reading-graph-overlap-dialog').getByText('Overlap 1 of 2'),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', {
        name: 'Should Justice League International (1987) continue while Mister Miracle (1989) waits?',
      }),
    ).toBeVisible()

    await page.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ }).click()
    await page.getByRole('button', { name: 'Next series' }).click()

    await expect(
      page.getByTestId('reading-graph-overlap-dialog').getByText('Overlap 2 of 2'),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', {
        name: 'Should Justice League International (1987) continue while Mister Miracle (2019) waits?',
      }),
    ).toBeVisible()
    // The 1989 volume's answer did not silently answer the 2019 volume.
    await expect(
      page.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ }),
    ).not.toHaveAttribute('aria-checked', 'true')
  })

  test('skips the questionnaire entirely when the source has no real overlap', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)
    const owned = await createThread(page, {
      title: 'Overlap Skip Owned',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)
    const sourceName = `Overlap Skip ${owned.id}-${Date.now()}`
    const source = await seedSource(page, headers, sourceName, [
      {
        position: 1,
        series_name: 'Overlap Skip Owned',
        issue_number: '1',
        issue_id: ownedIssueId,
      },
      {
        position: 2,
        series_name: 'Overlap Skip Missing',
        issue_number: '1',
        volume_year: 2008,
        comicvine_issue_id: `4000-overlap-skip-missing-${owned.id}-${Date.now()}`,
      },
    ])

    await page.route('**/v1/issue-identity/cbl/*/reading-graph-preview', (route) =>
      route.fulfill({
        json: { ...withoutOverlap(), source_list_id: source.id },
      }),
    )

    await searchAndSelect(page, sourceName)
    await expect(page.getByRole('button', { name: 'Add this reading order' })).toBeEnabled()
    await expect(page.getByTestId('reading-graph-summary')).toHaveCount(0)

    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await expect(
      page.getByRole('heading', { name: 'Add this reading order?' }),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Resolve overlapping series' }),
    ).toHaveCount(0)
  })
})
