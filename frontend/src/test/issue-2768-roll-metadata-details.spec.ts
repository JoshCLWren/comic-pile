/**
 * ISSUE-2768: Roll redesign - finish Comic metadata details and cover utilities.
 *
 * Acceptance contract:
 * 1. `View larger` opens the already-loaded cover through the shared Modal/overlay path.
 * 2. `Open in ComicVine` uses the existing `comicvine_url` contract when present.
 * 3. Story title/date follow the identity block cleanly.
 * 4. Normal summary text is visible by default; long summary has bounded disclosure.
 * 5. Creators render in the compact role/name treatment with row separation.
 * 6. Long creator lists preserve a useful `Show all` path.
 * 7. Story Arcs / related issues remain available but visually secondary.
 * 8. Tablet Story Arc content does not regress to a clipped nested scroller.
 * 9. Missing optional metadata collapses cleanly without empty cards/gaps.
 * 10. Phone/tablet remain free of horizontal overflow.
 */
import { expect, type Page } from '@playwright/test'
import { type ComicVineIssueIntelligence } from '../services/api-comicvine'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const DESKTOP_VIEWPORT = { width: 1280, height: 900 }
const PHONE_VIEWPORT = { width: 390, height: 844 }
const TABLET_VIEWPORT = { width: 800, height: 1094 }

/** Small opaque SVG used so the cover never hits the image optimizer. */
const COVER_DATA_URI = (() => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#111"/></svg>'
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
})()

function baseIntelligence(overrides: Partial<ComicVineIssueIntelligence> = {}): ComicVineIssueIntelligence {
  return {
    comicvine_issue_id: '100',
    comicvine_url: null,
    series_name: 'Test Series',
    series_id: 1,
    issue_number: '1',
    name: 'Issue One',
    description: null,
    image_url: null,
    cover_date: null,
    store_date: null,
    creators: [],
    story_arcs: [],
    ...overrides,
  }
}

function confirmedIdentity() {
  return {
    issue_id: 1,
    thread_id: 1,
    thread_title: 'Identity Thread',
    has_confirmed_identity: true,
    confirmed_mappings: [],
    candidate_mappings: [],
    has_unresolved: false,
  }
}

function minimalReaderContext() {
  return {
    issue_id: 100,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: 'series-1',
      series_name: 'Test Series',
      average_rating: null,
      ratings_count: 0,
      previous_issue: null,
      recent_ratings: [],
      highest_rating: null,
      lowest_rating: null,
    },
    crossovers: [],
    local_chain: { issues: [], edges: [] },
  }
}

async function installRoutes(page: Page, intelligence: ComicVineIssueIntelligence): Promise<void> {
  await page.route('**/v1/threads/*/reading-orders', (route) =>
    route.fulfill({ json: { reading_orders: [] } }),
  )
  await page.route('**/v1/threads/*/connected', (route) =>
    route.fulfill({ json: { connected_threads: [] } }),
  )
  await page.route('**/v1/reading-order-groups/threads/*/groups', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/v1/issues/*/reader-context', (route) =>
    route.fulfill({ json: minimalReaderContext() }),
  )
  await page.route('**/v1/issues/*/comicvine', (route) =>
    route.fulfill({ json: intelligence }),
  )
  await page.route('**/v1/comicvine/issues/*/identity', (route) =>
    route.fulfill({ json: confirmedIdentity() }),
  )
}

test.describe('issue #2768: cover utilities and metadata details', () => {
  test('View larger opens cover in Modal when image exists', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Cover Modal Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({ image_url: COVER_DATA_URI }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Cover Modal Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    const viewLargerBtn = page.locator('button[aria-label="View cover larger"]')
    await expect(viewLargerBtn).toBeVisible()
    await viewLargerBtn.click()
    await expect(page.getByTestId('cover-viewer-modal')).toBeVisible({ timeout: 5000 })
    await expect(page.getByRole('dialog', { name: 'Comic Cover' })).toBeVisible()
  })

  test('View larger button absent when no cover image', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'No Cover Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({ image_url: null }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('No Cover Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    const viewLargerBtn = page.locator('button[aria-label="View cover larger"]')
    await expect(viewLargerBtn).not.toBeVisible()
  })

  test('Open in ComicVine link present when comicvine_url exists', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'ComicVine Link Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({ comicvine_url: 'https://comicvine.example/100' }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('ComicVine Link Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    const comicVineLink = page.locator('a[aria-label="Open on ComicVine"]')
    await expect(comicVineLink).toBeVisible()
    await expect(comicVineLink).toHaveAttribute('href', 'https://comicvine.example/100')
  })

  test('ComicVine link absent when comicvine_url is null', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'No ComicVine Link Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({ comicvine_url: null }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('No ComicVine Link Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    const comicVineLink = page.locator('a[aria-label="Open on ComicVine"]')
    await expect(comicVineLink).not.toBeVisible()
  })

  test('story title and date render after cover', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Story Title Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({
      name: 'Amazing Story',
      description: 'A short story.',
      store_date: '2026-06-15',
    }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Story Title Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    // Story title rendered as heading
    await expect(page.getByText('Amazing Story')).toBeVisible()
    // Date rendered near title
    await expect(page.getByText('Jun 15, 2026')).toBeVisible()
  })

  test('normal summary is visible by default on desktop', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Normal Summary Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({
      description: 'This is a normal summary that fits on screen.',
    }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Normal Summary Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    // Summary should be visible (details is open on desktop)
    await expect(page.getByText('This is a normal summary that fits on screen.')).toBeVisible()
  })

  test('long summary has bounded disclosure on desktop', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const longDescription = 'A '.repeat(200) + 'very long description that should be truncated.'
    await createThread(page, {
      title: 'Long Summary Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({ description: longDescription }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Long Summary Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    // Should show "Show more" for long summaries
    const showMoreBtn = page.getByRole('button', { name: 'Show more' })
    await expect(showMoreBtn).toBeVisible()
    // The full text should NOT be visible initially
    await expect(page.getByText('very long description that should be truncated.')).not.toBeVisible()

    // Click Show more
    await showMoreBtn.click()
    await expect(page.getByText('very long description that should be truncated.')).toBeVisible()

    // Show less should appear
    const showLessBtn = page.getByRole('button', { name: 'Show less' })
    await expect(showLessBtn).toBeVisible()
  })
})

test.describe('issue #2768: creators and story arcs', () => {
  test('creators render in compact role/name treatment with row separation', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Creators Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({
      creators: [
        { name: 'Writer One', roles: ['writer'] },
        { name: 'Artist One', roles: ['penciler', 'inker'] },
      ],
    }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Creators Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    // Creator names should be present
    await expect(page.getByText('Writer One')).toBeVisible()
    await expect(page.getByText('Artist One')).toBeVisible()
    // Roles should be present
    const writerRow = page.locator('[data-testid="creator-row"]', { hasText: 'Writer One' })
    await expect(writerRow).toContainText('writer')
    const artistRow = page.locator('[data-testid="creator-row"]', { hasText: 'Artist One' })
    await expect(artistRow).toContainText('penciler')
    await expect(artistRow).toContainText('inker')
  })

  test('long creator list preserves Show all path', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    const manyCreators = Array.from({ length: 10 }, (_, i) => ({
      name: `Creator ${i + 1}`,
      roles: ['writer'],
    }))
    await createThread(page, {
      title: 'Long Creators Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({ creators: manyCreators }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Long Creators Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    // Initially only first 6 shown
    await expect(page.getByText('Creator 6')).toBeVisible()
    await expect(page.getByText('Creator 7')).toHaveCount(0)

    // Show all button
    const showAllBtn = page.getByRole('button', { name: /show all 10/i })
    await expect(showAllBtn).toBeVisible()
    await showAllBtn.click()
    await expect(page.getByText('Creator 10')).toBeVisible()
  })

  test('story arcs remain available but visually secondary', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Story Arcs Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({
      story_arcs: [{
        comicvine_arc_id: 1,
        name: 'Test Arc',
        comicvine_url: null,
        total_related_count: null,
        related_issues: [
          {
            comicvine_issue_id: '101',
            series_name: 'Test',
            issue_number: '2',
            name: 'Second Issue',
            cover_date: null,
            comicvine_url: null,
            comicpile_matches: [],
          },
        ],
      }],
    }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Story Arcs Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    // Story arcs section should exist
    await expect(page.getByText('Story arcs (1)')).toBeVisible()
    await expect(page.getByText('Test Arc')).toBeVisible()
  })

  test('story arc content does not regress to clipped nested scroller on tablet', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(TABLET_VIEWPORT)
    const manyIssues = Array.from({ length: 8 }, (_, i) => ({
      comicvine_issue_id: `${i + 1}`,
      series_name: 'Series',
      issue_number: `${i + 1}`,
      name: null,
      cover_date: null,
      comicvine_url: null,
      comicpile_matches: [],
    }))
    await createThread(page, {
      title: 'Tablet Arc Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({
      story_arcs: [{
        comicvine_arc_id: 1,
        name: 'Big Arc',
        comicvine_url: null,
        total_related_count: null,
        related_issues: manyIssues,
      }],
    }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Tablet Arc Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    const list = page.locator('[data-testid="story-arc-issue-list"]')
    // The list should not have overflow-y: auto or max-height constraints
    const overflowStyle = await list.evaluate((el) => {
      const style = window.getComputedStyle(el)
      return { overflowY: style.overflowY, maxHeight: style.maxHeight }
    })
    expect(overflowStyle.overflowY).not.toBe('auto')
    expect(overflowStyle.maxHeight).toBe('none')
  })
})

test.describe('issue #2768: responsive and edge cases', () => {
  test('phone viewport has no horizontal overflow', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(PHONE_VIEWPORT)
    await createThread(page, {
      title: 'Phone Overflow Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({
      description: 'Short summary.',
      creators: [{ name: 'Creator', roles: ['writer'] }],
      story_arcs: [],
    }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Phone Overflow Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    // No horizontal overflow
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    const innerWidth = await page.evaluate(() => window.innerWidth)
    expect(scrollWidth).toBeLessThanOrEqual(innerWidth + 1)
  })

  test('missing optional metadata collapses cleanly', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createThread(page, {
      title: 'Sparse Metadata Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await installRoutes(page, baseIntelligence({
      description: null,
      creators: [],
      story_arcs: [],
      comicvine_url: null,
      image_url: null,
    }))
    await gotoRollPage(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
    await page.getByText('Sparse Metadata Thread').first().click()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
    await page.evaluate(async () => {
      if (document.fonts) {
        await document.fonts.ready
      }
    })

    // No empty cards/gaps - description, creators, and story arcs sections should not render
    await expect(page.getByText('Summary')).not.toBeVisible()
    await expect(page.getByText('Creators')).not.toBeVisible()
    await expect(page.getByText('Story arcs')).not.toBeVisible()
    await expect(page.getByText('View issue on ComicVine')).not.toBeVisible()
  })
})
