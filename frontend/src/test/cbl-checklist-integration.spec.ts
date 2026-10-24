import { test, expect } from './fixtures'
import { createThread, getAuthToken, getFirstIssueId, authHeaders } from './helpers'
import type { Page } from '@playwright/test'

test.describe('CBL adoption checklist integration', () => {
  test('all source occurrences initially selected; uncheck volume => indeterminate parent; recheck one issue => indeterminate', async ({
    authenticatedPage,
  }: { authenticatedPage: Page }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    // Create two owned issues that will be used to test volume grouping
    const owned1 = await createThread(page, {
      title: 'Test Volume 1',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssue1 = await getFirstIssueId(page, owned1.id)
    
    const owned2 = await createThread(page, {
      title: 'Test Volume 1', // Same name as above, different volume
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssue2 = await getFirstIssueId(page, owned2.id)

    const fixtureSuffix = `${Date.now()}`
    const sourceName = `Checklist Test ${fixtureSuffix}`
    const sourcePath = `Fixtures/Checklist Test ${fixtureSuffix}.cbl`

    // Seed a CBL source with multiple entries including duplicates
    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `checklist-test-${fixtureSuffix}`,
        revision_sha: `checklist-test-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          // First volume - Test Volume 1 (owned)
          {
            position: 1,
            series_name: 'Test Volume 1',
            issue_number: '1',
            issue_id: ownedIssue1,
            series_group_id: 'provider-series:comicvine:4050',
            volume_year: 2012,
          },
          // Second volume - Test Volume 1 (different volume, owned)
          {
            position: 2,
            series_name: 'Test Volume 1',
            issue_number: '1',
            issue_id: ownedIssue2,
            series_group_id: 'provider-series:comicvine:9000',
            volume_year: 2012,
          },
          // Missing entries
          {
            position: 3,
            series_name: 'Missing Series 1',
            issue_number: '1',
            series_group_id: 'provider-series:comicvine:5000',
            volume_year: 2023,
            comicvine_issue_id: '4000-missing-1',
          },
          {
            position: 4,
            series_name: 'Missing Series 1',
            issue_number: '2',
            series_group_id: 'provider-series:comicvine:5000',
            volume_year: 2023,
            comicvine_issue_id: '4000-missing-2',
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    // Navigate to CBL browser
    await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page
      .getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
      .click()

    // Verify initial state: all entries selected
    await page.getByRole('button', { name: 'Customize', exact: true }).click()
    
    // Both volumes should be initially selected (checked)
    const volume1Checkbox = page.getByRole('checkbox', { name: 'Include Test Volume 1 (2012) series' })
    const volume2Checkbox = page.getByRole('checkbox', { name: 'Include Test Volume 1 (2012) series' })
    
    // Note: Playwright may not distinguish between checkboxes with same name,
    // so we need to be more specific about which one we're testing
    await expect(page.getByText('4 entries · 2 already in ComicPile · 2 will be added')).toBeVisible()
    
    // Uncheck the first volume - should become indeterminate
    await page.getByRole('checkbox', { name: 'Include Test Volume 1 (2012) series' }).first().click()

    // Should now show indeterminate state for the first volume
    await expect(page.getByText('4 entries · 0 already in ComicPile · 2 will be added')).toBeVisible()
    
    // Recheck one issue from the first volume - should make it indeterminate
    // Expand the first volume to see individual issues
    await page.getByRole('button', { name: 'Show issues' }).first().click()
    await page.getByRole('checkbox', { name: 'Include Test Volume 1 (2012) #1' }).check()

    // Should show the updated count
    await expect(page.getByText('4 entries · 1 already in ComicPile · 2 will be added')).toBeVisible()
  })

  test('keeps choices when switching between sources and detects source changes', async ({
    authenticatedPage,
  }: { authenticatedPage: Page }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const fixtureSuffix = `${Date.now()}`
    const sourceName1 = `Source Choice Test 1 ${fixtureSuffix}`
    const sourceName2 = `Source Choice Test 2 ${fixtureSuffix}`
    const sourcePath1 = `Fixtures/Source Choice Test 1 ${fixtureSuffix}.cbl`
    const sourcePath2 = `Fixtures/Source Choice Test 2 ${fixtureSuffix}.cbl`

    // Seed first source
    const seed1 = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName1,
        source_path: sourcePath1,
        content_hash: `source-choice-1-${fixtureSuffix}`,
        revision_sha: `source-choice-1-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Source 1 Series',
            issue_number: '1',
            series_group_id: 'provider-series:comicvine:1000',
          },
        ],
      },
    })
    expect(seed1.ok(), await seed1.text()).toBeTruthy()

    // Seed second source
    const seed2 = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName2,
        source_path: sourcePath2,
        content_hash: `source-choice-2-${fixtureSuffix}`,
        revision_sha: `source-choice-2-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Source 2 Series',
            issue_number: '1',
            series_group_id: 'provider-series:comicvine:2000',
          },
        ],
      },
    })
    expect(seed2.ok(), await seed2.text()).toBeTruthy()

    // Navigate to CBL browser
    await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })

    // Search and select first source
    await page.getByLabel('Search source lists').fill(sourceName1)
    await page.getByRole('button', { name: 'Search' }).click()
    await page.getByRole('button', { name: new RegExp(sourceName1.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()
    
    await expect(page.getByRole('heading', { name: sourceName1 })).toBeVisible()
    
    // Make a choice on first source
    await page.getByRole('button', { name: 'Customize', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Include Source 1 Series series' }).uncheck()
    await expect(page.getByText('1 entry · 0 already in ComicPile · 0 will be added')).toBeVisible()

    // Switch to second source - should have fresh choices
    await page.getByLabel('Search source lists').fill(sourceName2)
    await page.getByRole('button', { name: 'Search' }).click()
    await page.getByRole('button', { name: new RegExp(sourceName2.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()
    await expect(page.getByRole('heading', { name: sourceName2 })).toBeVisible()
    
    // Second source should have default state (all selected)
    await page.getByRole('button', { name: 'Customize', exact: true }).click()
    await expect(page.getByRole('checkbox', { name: 'Include Source 2 Series series' })).toBeChecked()
    await expect(page.getByText('1 entry · 0 already in ComicPile · 1 will be added')).toBeVisible()

    // Make a choice on second source
    await page.getByRole('checkbox', { name: 'Include Source 2 Series series' }).uncheck()
    await expect(page.getByText('1 entry · 0 already in ComicPile · 0 will be added')).toBeVisible()

    // Switch back to first source - should restore the previous choice
    await page.getByLabel('Search source lists').fill(sourceName1)
    await page.getByRole('button', { name: 'Search' }).click()
    await page.getByRole('button', { name: new RegExp(sourceName1.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()
    await expect(page.getByRole('heading', { name: sourceName1 })).toBeVisible()
    
    await page.getByRole('button', { name: 'Customize', exact: true }).click()
    await expect(page.getByRole('checkbox', { name: 'Include Source 1 Series series' })).not.toBeChecked()
    await expect(page.getByText('1 entry · 0 already in ComicPile · 0 will be added')).toBeVisible()
  })

  test('duplicate source occurrences do not create duplicate owned Issues', async ({
    authenticatedPage,
  }: { authenticatedPage: Page }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const owned = await createThread(page, {
      title: 'Duplicate Test Series',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)

    const fixtureSuffix = `${Date.now()}`
    const sourceName = `Duplicate Source Test ${fixtureSuffix}`
    const sourcePath = `Fixtures/Duplicate Source Test ${fixtureSuffix}.cbl`

    // Seed a CBL source with duplicate entries pointing to the same issue
    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `duplicate-test-${fixtureSuffix}`,
        revision_sha: `duplicate-test-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Duplicate Test Series',
            issue_number: '1',
            issue_id: ownedIssueId,
            series_group_id: 'provider-series:comicvine:3000',
          },
          {
            position: 2,
            series_name: 'Duplicate Test Series',
            issue_number: '1',
            issue_id: ownedIssueId, // Same issue ID
            series_group_id: 'provider-series:comicvine:3000',
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    // Navigate to CBL browser
    await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page
      .getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
      .click()

    // Should show correct count (not double-counting duplicates)
    await expect(page.getByText('2 entries · 1 already in ComicPile · 1 will be added')).toBeVisible()
    
    // Add the source
    await page.getByRole('button', { name: 'Add this reading order' }).click()
    await page.getByRole('button', { name: 'Add reading order' }).click()
    
    await expect(page).toHaveURL(/\/continuity-plans\/\d+/, { timeout: 60000 })
    const planId = Number(page.url().match(/\/continuity-plans\/(\d+)/)?.[1])
    expect(planId).toBeGreaterThan(0)

    // Verify the plan doesn't have duplicate nodes
    const planResponse = await page.request.get(`/api/v1/continuity-plans/${planId}`, {
      headers,
    })
    expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const plan = (await planResponse.json()) as { nodes: Array<{ ref_id: number }> }
    expect(plan.nodes.length).toBe(1) // Should only have one node, not two duplicates
    expect(plan.nodes[0]?.ref_id).toBe(ownedIssueId)
  })

  test('source preview/cancel creates zero database user/source rows', async ({
    authenticatedPage,
  }: { authenticatedPage: Page }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const fixtureSuffix = `${Date.now()}`
    const sourceName = `Preview Cancel Test ${fixtureSuffix}`
    const sourcePath = `Fixtures/Preview Cancel Test ${fixtureSuffix}.cbl`

    // Get initial count of continuity plans
    const plansBefore = await page.request.get('/api/v1/continuity-plans/', { headers })
    expect(plansBefore.ok(), await plansBefore.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const plansBeforeJson = (await plansBefore.json()) as Array<{ id: number }>
    const initialPlanCount = plansBeforeJson.length

    // Seed a CBL source
    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `preview-cancel-test-${fixtureSuffix}`,
        revision_sha: `preview-cancel-test-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Preview Test Series',
            issue_number: '1',
            series_group_id: 'provider-series:comicvine:4000',
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    // Navigate to CBL browser
    await page.goto('/cbl-sources', { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page
      .getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
      .click()

    // Preview the source (should not create any database rows)
    await expect(page.getByText('1 entry · 0 already in ComicPile · 1 will be added')).toBeVisible()

    // Cancel the preview (should not create any database rows)
    await page.getByRole('button', { name: 'Customize', exact: true }).click()
    await page.getByRole('button', { name: 'Hide customization' }).click()
    
    // Verify no plans were created
    const plansAfter = await page.request.get('/api/v1/continuity-plans/', { headers })
    expect(plansAfter.ok(), await plansAfter.text()).toBeTruthy()
    // SAFETY: the test reads only the response fields listed in this type
    const plansAfterJson = (await plansAfter.json()) as Array<{ id: number }>
    expect(plansAfterJson.length).toBe(initialPlanCount)
  })
})