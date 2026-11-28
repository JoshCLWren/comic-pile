/**
 * #4023 browser acceptance: a reviewed CBL source commits into the reader's
 * canonical, source-linked Reading List. The first Add creates the owned list;
 * reopening restores the committed customization from the server; a second
 * Update targets the same list ID with a list-version guard. Cancel never
 * writes. Backend transaction/persistence behavior belongs to #4022's real
 * Postgres suite; this spec proves the browser contract and wire shape.
 */
import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'

const SOURCE_ID = 42
const LIST_ID = 900
const CONTENT_HASH = 'hash-42'
const REVISION_SHA = 'rev-42'

type CommitPayload = {
  content_hash: string
  revision_sha: string
  entry_decisions: Record<string, string>
  series_overrides: Array<{ cbl_position: number; decision: string }>
  list_version?: number
  idempotency_key?: string
}

const source = {
  id: SOURCE_ID,
  name: 'Ultimate Universe',
  source_path: 'Marvel/Ultimate.cbl',
  source_repository: 'JoshCLWren/CBL-ReadingLists',
  declared_issue_count: 2,
  content_hash: CONTENT_HASH,
  revision_sha: REVISION_SHA,
}

const preview = {
  source: {
    source_list_id: SOURCE_ID,
    source_repository: source.source_repository,
    source_path: source.source_path,
    content_hash: CONTENT_HASH,
    revision_sha: REVISION_SHA,
  },
  total_positions: 2,
  entries: [
    {
      cbl_position: 1,
      cbl_entry_id: 101,
      series_name: 'Ultimate Spider-Man',
      issue_number: '1',
      series_group_id: 'provider-series:comicvine:4000',
      volume_year: null,
      publication_year: null,
      adoption_class: 'existing',
      adoption_decision: 'included_existing',
      adopted: true,
      comicvine_issue_id: '4000-1',
      comicvine_series_id: null,
      series_provider: 'comicvine',
      series_external_id: null,
      resolved_issue_id: 11,
      canonical_issue_id: 11,
      read_status: 'unread',
      read_at: null,
      resolution_status: 'resolved_via_comicvine_canonical',
      is_duplicate_identity: false,
      collection_excluded: false,
      collection_exclusion_reason: null,
      collection_exclusion_ids: [],
    },
    {
      cbl_position: 2,
      cbl_entry_id: 102,
      series_name: 'Ultimate Spider-Man',
      issue_number: '2',
      series_group_id: 'provider-series:comicvine:4000',
      volume_year: null,
      publication_year: null,
      adoption_class: 'existing',
      adoption_decision: 'included_existing',
      adopted: true,
      comicvine_issue_id: '4000-2',
      comicvine_series_id: null,
      series_provider: 'comicvine',
      series_external_id: null,
      resolved_issue_id: 12,
      canonical_issue_id: 12,
      read_status: 'read',
      read_at: '2026-11-20T00:00:00Z',
      resolution_status: 'resolved_via_comicvine_canonical',
      is_duplicate_identity: false,
      collection_excluded: false,
      collection_exclusion_reason: null,
      collection_exclusion_ids: [],
    },
  ],
  summary: {
    reused_existing_count: 2,
    missing_would_create_count: 0,
    excluded_count: 0,
    unresolved_count: 0,
    awaiting_opt_in_count: 0,
    final_adopted_count: 2,
    final_adopted_order: [1, 2],
    reused_existing_positions: [1, 2],
    missing_would_create_positions: [],
    excluded_positions: [],
    unresolved_positions: [],
    awaiting_opt_in_positions: [],
  },
}

async function installCblRoutes(page: Page, commits: CommitPayload[]): Promise<void> {
  await page.route(/\/api\/v1\/issue-identity\/cbl-sources\/browse(?:\?|$)/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        scope: 'folder',
        folder: '',
        query: null,
        breadcrumbs: [{ name: 'All CBLs', path: '' }],
        folders: [],
        items: [source],
        page: 1,
        page_size: 50,
        total: 1,
        catalog_total: 1,
        total_pages: 1,
        has_next: false,
        has_previous: false,
      }),
    }),
  )
  await page.route(/\/api\/v1\/issue-identity\/cbl-sources\/42(?:\?|$)/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...source,
        source_ref: 'JoshCLWren/CBL-ReadingLists:Marvel/Ultimate.cbl',
        entries_total: 2,
        entries_offset: 0,
        entries_limit: 200,
        entries: preview.entries.map((entry) => ({
          position: entry.cbl_position,
          series_name: entry.series_name,
          issue_number: entry.issue_number,
          volume_year: null,
          publication_year: null,
          comicvine_issue_id: entry.comicvine_issue_id,
          comicvine_volume_id: null,
        })),
      }),
    }),
  )
  await page.route(/\/api\/v1\/issue-identity\/cbl\/42\/adoption-preview(?:\?|$)/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(preview) }),
  )
  await page.route(/\/api\/v1\/issue-identity\/cbl\/42\/reading-graph-preview(?:\?|$)/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        source_list_id: SOURCE_ID,
        content_hash: CONTENT_HASH,
        revision_sha: REVISION_SHA,
        series: [],
        overlaps: [],
        issues: [],
        rollable_issue_ids: [],
        waiting_issue_ids: [],
        cycle_errors: [],
      }),
    }),
  )
  await page.route(/\/api\/v2\/reading-lists\/42\/adoption-commits(?:\?|$)/, async (route) => {
    // SAFETY: Playwright route body is the JSON sent by the app under test.
    const payload = route.request().postDataJSON() as CommitPayload
    commits.push(payload)
    const version = commits.length
    await route.fulfill({
      status: commits.length === 1 ? 201 : 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: LIST_ID,
        user_id: 1,
        name: source.name,
        ordering_mode: 'informational',
        lanes: {},
        nodes: {},
        created_at: '2026-11-28T00:00:00Z',
        updated_at: '2026-11-28T00:00:00Z',
        custom_cbl_list_id: LIST_ID,
        list_version: version,
        reused_positions: [],
        created_positions: [],
        excluded_positions: [],
        unresolved_positions: [],
        selections: {
          entry_decisions: payload.entry_decisions,
          series_overrides: Object.fromEntries(
            payload.series_overrides.map((override) => [
              String(override.cbl_position),
              override.decision,
            ]),
          ),
        },
        overlap_decisions: [],
      }),
    })
  })
  // The reopened list is authoritative for saved choices and version.
  await page.route(/\/api\/v2\/reading-lists\/900(?:\?|$)/, (route) => {
    const last = commits.at(-1)
    const selections = last
      ? {
          entry_decisions: last.entry_decisions,
          series_overrides: Object.fromEntries(
            last.series_overrides.map((override) => [
              String(override.cbl_position),
              override.decision,
            ]),
          ),
        }
      : null
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: LIST_ID,
        user_id: 1,
        name: source.name,
        description: null,
        mode: 'strict',
        issue_count: 2,
        entries: [],
        created_at: '2026-11-28T00:00:00Z',
        updated_at: '2026-11-28T00:00:00Z',
        list_version: last?.list_version ?? 1,
        source_content_hash: CONTENT_HASH,
        source_revision_sha: REVISION_SHA,
        selections,
        overlap_decisions: [],
      }),
    })
  })
}

test.describe('CBL add/update into an owned Reading List', () => {
  test('first add and second update keep one list ID, saved choices and no cancel writes', async ({
    authenticatedPage: page,
  }) => {
    const commits: CommitPayload[] = []
    await installCblRoutes(page, commits)

    await page.goto('/cbl-sources?list=42')
    await expect(page.getByRole('heading', { name: 'Ultimate Universe' })).toBeVisible()

    // Explicit confirmation boundary: cancel writes nothing.
    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await expect(page.getByRole('heading', { name: 'Add this reading order?' })).toBeVisible()
    await expect(
      page.getByText(/Add Ultimate Universe to a new Reading List you own/),
    ).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()
    expect(commits).toHaveLength(0)

    // Uncheck one issue so the committed selection is a real customization.
    await page.getByRole('button', { name: 'Customize' }).click()
    await page.getByRole('button', { name: 'Show issues for Ultimate Spider-Man' }).click()
    const firstIssue = page.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #1' })
    await firstIssue.uncheck()
    await expect(firstIssue).not.toBeChecked()

    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await page.getByRole('button', { name: 'Add reading order' }).click()
    await expect(page).toHaveURL(/\/reading-lists\/900$/)
    expect(commits).toHaveLength(1)
    expect(commits[0].content_hash).toBe(CONTENT_HASH)
    expect(commits[0].revision_sha).toBe(REVISION_SHA)
    expect(commits[0].entry_decisions).toEqual({ '101': 'exclude' })
    expect(commits[0].list_version).toBeUndefined()

    // Reopen the same CBL: the linked owned list ID and saved choice return.
    await page.goto('/cbl-sources?list=42')
    await expect(page.getByTestId('cbl-owned-list')).toContainText(
      'Previously added. Linked to Reading List #900',
    )
    await page.getByRole('button', { name: 'Customize' }).click()
    await page.getByRole('button', { name: 'Show issues for Ultimate Spider-Man' }).click()
    const restored = page.getByRole('checkbox', { name: 'Include Ultimate Spider-Man #1' })
    await expect(restored).not.toBeChecked()
    // The read/rating history shown for the second issue is unchanged.
    await expect(page.getByText('Already in ComicPile · read')).toBeVisible()

    // A second update targets the same canonical list with a version guard.
    await page.getByRole('button', { name: 'Update this Reading List' }).click()
    await expect(page.getByRole('heading', { name: 'Update this Reading List?' })).toBeVisible()
    await expect(page.getByText(/Reading List #900/)).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()
    expect(commits).toHaveLength(1)

    await page.getByRole('button', { name: 'Update this Reading List' }).click()
    await page.getByRole('button', { name: 'Update Reading List' }).click()
    await expect(page).toHaveURL(/\/reading-lists\/900$/)
    expect(commits).toHaveLength(2)
    expect(commits[1].list_version).toBe(1)
    expect(commits[1].idempotency_key).toBeTruthy()
    expect(commits[1].entry_decisions).toEqual(commits[0].entry_decisions)
  })

  test('reopen shows stale-preview explanation and preserves per-series graph decisions', async ({
    authenticatedPage: page,
  }) => {
    const commits: CommitPayload[] = []
    const overlap = {
      overlap_id: 'provider-series:comicvine:4000|provider-series:comicvine:5000',
      continuing_series: {
        comicvine_volume_id: '4000',
        series_name: 'Ultimate Spider-Man',
        year: 2000,
      },
      waiting_series: {
        comicvine_volume_id: '5000',
        series_name: 'Ultimates',
        year: 2002,
      },
      question: 'Should Ultimate Spider-Man continue while Ultimates waits?',
      blocked_issue_ids: [11],
      choices: [
        {
          choice: 'protect_order' as const,
          label: 'Ultimates waits; Ultimate Spider-Man continues',
          detail: 'Keeps the original reading order.',
          rollable_issue_ids: [11],
          waiting_issue_ids: [],
          series: [],
        },
        {
          choice: 'continue_series' as const,
          label: 'Continue Ultimate Spider-Man',
          detail: 'Lets the continuing series roll.',
          rollable_issue_ids: [11, 12],
          waiting_issue_ids: [],
          series: [],
        },
      ],
      selected_choice: null,
    }
    const graphPreview = {
      source_list_id: SOURCE_ID,
      content_hash: CONTENT_HASH,
      revision_sha: REVISION_SHA,
      series: [],
      overlaps: [overlap],
      issues: [],
      rollable_issue_ids: [11],
      waiting_issue_ids: [],
      cycle_errors: [],
    }

    await page.route(/\/api\/v1\/issue-identity\/cbl-sources\/browse(?:\?|$)/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          scope: 'folder',
          folder: '',
          query: null,
          breadcrumbs: [{ name: 'All CBLs', path: '' }],
          folders: [],
          items: [source],
          page: 1,
          page_size: 50,
          total: 1,
          catalog_total: 1,
          total_pages: 1,
          has_next: false,
          has_previous: false,
        }),
      }),
    )
    await page.route(/\/api\/v1\/issue-identity\/cbl-sources\/42(?:\?|$)/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...source,
          source_ref: 'JoshCLWren/CBL-ReadingLists:Marvel/Ultimate.cbl',
          entries_total: 2,
          entries_offset: 0,
          entries_limit: 200,
          entries: preview.entries.map((entry) => ({
            position: entry.cbl_position,
            series_name: entry.series_name,
            issue_number: entry.issue_number,
            volume_year: null,
            publication_year: null,
            comicvine_issue_id: entry.comicvine_issue_id,
            comicvine_volume_id: null,
          })),
        }),
      }),
    )
    await page.route(/\/api\/v1\/issue-identity\/cbl\/42\/adoption-preview(?:\?|$)/, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(preview) }),
    )
    await page.route(/\/api\/v1\/issue-identity\/cbl\/42\/reading-graph-preview(?:\?|$)/, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(graphPreview) }),
    )
    await page.route(/\/api\/v2\/reading-lists\/42\/adoption-commits(?:\?|$)/, async (route) => {
      // SAFETY: Playwright route body is the JSON sent by the app under test.
      const payload = route.request().postDataJSON() as CommitPayload & {
        overlap_decisions?: Array<{ overlap_id: string; choice: string }>
      }
      commits.push(payload)
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: LIST_ID,
          user_id: 1,
          name: source.name,
          ordering_mode: 'informational',
          lanes: {},
          nodes: {},
          created_at: '2026-11-28T00:00:00Z',
          updated_at: '2026-11-28T00:00:00Z',
          custom_cbl_list_id: LIST_ID,
          list_version: 1,
          reused_positions: [],
          created_positions: [],
          excluded_positions: [],
          unresolved_positions: [],
          selections: { entry_decisions: payload.entry_decisions, series_overrides: {} },
          overlap_decisions: payload.overlap_decisions ?? [],
        }),
      })
    })

    let staleDetail = false
    await page.route(/\/api\/v2\/reading-lists\/900(?:\?|$)/, (route) => {
      const last = commits.at(-1)
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: LIST_ID,
          user_id: 1,
          name: source.name,
          description: null,
          mode: 'strict',
          issue_count: 2,
          entries: [],
          created_at: '2026-11-28T00:00:00Z',
          updated_at: '2026-11-28T00:00:00Z',
          list_version: 1,
          source_content_hash: staleDetail ? 'stale-hash' : CONTENT_HASH,
          source_revision_sha: staleDetail ? 'stale-rev' : REVISION_SHA,
          selections: last
            ? { entry_decisions: last.entry_decisions, series_overrides: {} }
            : null,
          overlap_decisions: last?.overlap_decisions ?? [],
        }),
      })
    })

    await page.goto('/cbl-sources?list=42')
    await expect(page.getByRole('heading', { name: 'Ultimate Universe' })).toBeVisible()

    await page.getByRole('button', { name: 'Add this reading order' }).click()
    const graphDialog = page.getByTestId('reading-graph-overlap-dialog')
    await expect(graphDialog).toBeVisible()
    await graphDialog.getByRole('radio', { name: /Continue Ultimate Spider-Man/ }).click()
    await graphDialog.getByRole('button', { name: 'Apply decision' }).click()
    await page.getByRole('button', { name: 'Add reading order' }).click()
    await expect(page).toHaveURL(/\/reading-lists\/900$/)
    expect(commits).toHaveLength(1)
    expect(commits[0].overlap_decisions).toEqual([
      {
        overlap_id: 'provider-series:comicvine:4000|provider-series:comicvine:5000',
        choice: 'continue_series',
      },
    ])

    // Reopen with the same source fingerprint: the saved overlap decision is restored.
    await page.goto('/cbl-sources?list=42')
    await expect(page.getByTestId('cbl-owned-list')).toContainText(
      'Previously added. Linked to Reading List #900',
    )
    await page.getByRole('button', { name: 'Add this reading order' }).click()
    const restoredDialog = page.getByTestId('reading-graph-overlap-dialog')
    await expect(restoredDialog).toBeVisible()
    await expect(
      restoredDialog.getByRole('radio', { name: /Continue Ultimate Spider-Man/ }),
    ).toHaveAttribute('aria-checked', 'true')
    await restoredDialog.getByRole('button', { name: 'Close' }).click()

    // A changed source fingerprint must explain why the preview is stale.
    staleDetail = true
    await page.goto('/cbl-sources?list=42')
    await expect(
      page.getByText(
        'This source or its Reading List changed after you reviewed it. Refresh the preview before adding it again.',
      ),
    ).toBeVisible()
  })
})
