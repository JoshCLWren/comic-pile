/** Browser coverage for the production blank-confirmation shape; API regressions replay the roster. */
import { expect } from '@playwright/test'
import { test } from './fixtures'

for (const width of [390, 1280]) {
  test(`Queue updates a verified blank link without removing it at ${width}px`, async ({
    authenticatedWithThreadsPage: page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    let originId = 0
    let committed = false
    const removed: string[] = []
    page.on('request', (request) => {
      if (request.url().includes('remove-identity')) removed.push(request.url())
    })
    await page.route('**/api/v1/comicvine/search/series**', (route) => route.fulfill({ json: {
      query: 'Tom Strong', results: [{ comicvine_volume_id: 6566, name: 'Tom Strong',
        publisher: 'America’s Best Comics', start_year: 1999, issue_count: 36,
        site_detail_url: null, image_url: null }],
      total_available: 1, offset: 0, limit: 20, has_more: false, next_offset: null,
    } }))
    await page.route('**/api/v1/catalog/series-mappings/preview', async (route) => {
      // SAFETY: the preview hook sends origin_issue_id; this fixture reads only that field.
      const body = route.request().postDataJSON() as { origin_issue_id: number }
      originId = body.origin_issue_id
      await route.fulfill({ json: {
        preview_token: 'verified-blank-preview', issued_at: 1, expires_at: null,
        scope: { status: 'available', scope_key: 'verified', origin_issue_id: originId,
          series_label: 'Tom Strong', basis: 'queue_thread_bootstrap_exact_match' },
        provider_series: null,
        counts: { already_confirmed: 1, safe_exact_match: 0, needs_review_ambiguous: 0,
          needs_review_conflict: 0, unresolved: 0, excluded_special: 0 },
        rows: [{ row_id: `issue:${originId}`, issue_id: originId, issue_number: '8',
          title: 'Tom Strong', thread_id: 1, thread_title: 'Tom Strong',
          classification: 'already_confirmed', current_mapping_status: 'confirmed',
          proposed_mapping: true, default_selected: true, metadata_refresh_required: true,
          reason: null }],
      } })
    })
    await page.route('**/api/v1/catalog/series-mappings/commit', async (route) => {
      // SAFETY: this test owns the approval flow and asserts its row IDs before using the body.
      const body = route.request().postDataJSON() as { approved_row_ids: string[]; idempotency_key: string }
      expect(body.approved_row_ids).toEqual([`issue:${originId}`])
      committed = true
      await route.fulfill({ json: {
        idempotency_key: body.idempotency_key, confirmed_issue_ids: [originId],
        already_confirmed_issue_ids: [originId], needs_review_issue_ids: [],
        hydration_queued_issue_ids: [originId],
        series_mapping: { provider: 'comicvine', external_id: '6566', status: 'confirmed',
          evidence_source: 'user_series_confirmation' },
      } })
    })
    await page.goto('/queue')
    await page.getByRole('button', { name: 'Map series', exact: true }).first().click()
    await page.getByTestId('queue-map-series-result').click()
    await expect(page.getByText('Missing details', { exact: true })).toBeVisible()
    const approve = page.getByRole('button', { name: 'Update 1 issue', exact: true })
    await expect(approve).toBeEnabled()
    await approve.scrollIntoViewIfNeeded()
    await expect(approve).toBeInViewport()
    await page.screenshot({ path: testInfo.outputPath('missing-details.png') })
    await approve.click()
    await expect.poll(() => committed).toBe(true)
    await expect(page.getByTestId('queue-map-series-dialog')).toHaveCount(0)
    expect(removed).toEqual([])
  })
}
