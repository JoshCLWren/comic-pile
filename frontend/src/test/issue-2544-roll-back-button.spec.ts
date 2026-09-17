/**
 * Issue #2544: back button after opening a creator from the roll page.
 *
 * Acceptance contract (from the issue): after clicking a creator on the roll
 * page, the browser back button must return to the previous roll page
 * without forcing another roll.
 *
 * Creator links on the roll page live in the rating view
 * (`RatingView -> ComicPillar -> ComicIdentity -> CreatorName`) and are fed
 * by ComicVine issue intelligence, so the intelligence and creator-detail
 * payloads are fulfilled at the network layer while the roll itself and the
 * pending session stay real. The spec rolls once, opens the creator, goes
 * back, and asserts the same in-flight read is restored with no additional
 * roll POST.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const DESKTOP_VIEWPORT = { width: 1280, height: 900 }

function issueIntelligencePayload() {
  return {
    comicvine_issue_id: '12345',
    comicvine_url: null,
    series_name: 'Back Button Thread',
    series_id: null,
    issue_number: '1',
    name: 'Back Button Debut',
    description: 'A test issue carrying a stable creator identity.',
    image_url: null,
    cover_date: null,
    store_date: null,
    creators: [
      {
        creator_id: 7,
        name: 'Test Creator',
        roles: ['Writer'],
      },
    ],
    story_arcs: [],
  }
}

function creatorDetailPayload() {
  return {
    summary: {
      canonical_creator_key: 'creator:7',
      display_name: 'Test Creator',
      normalized_roles: ['Writer'],
      average_rating: 4.0,
      ratings_count: 1,
      read_unrated_count: 0,
      upcoming_count: 0,
    },
    coverage: {
      rated_issues_total: 1,
      rated_issues_with_creator_metadata: 1,
      ratings_complete: true,
      read_unrated_issues_total: 0,
      read_unrated_issues_with_creator_metadata: 0,
      read_unrated_complete: true,
      unread_issues_total: 0,
      unread_issues_with_creator_metadata: 0,
      upcoming_complete: true,
    },
    role_stats: [{ role: 'Writer', issue_count: 1, average_rating: 4.0 }],
    rated_issues: [
      {
        issue_id: 101,
        issue_number: '1',
        thread_id: 1,
        thread_title: 'Back Button Thread',
        status: 'read',
        roles: ['Writer'],
        effective_rating: 4,
        rating_timestamp: '2026-01-01T00:00:00Z',
        sort_key: '1',
      },
    ],
    read_unrated_issues: [],
    upcoming_issues: [],
    next_cursor: null,
  }
}

test.describe('Issue #2544: Roll Page Back Button', () => {
  test('back from creator detail restores the in-flight read without re-rolling', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)

    await createThread(page, {
      title: 'Back Button Thread',
      format: 'Issue',
      issues_remaining: 1,
      total_issues: 1,
    })

    // Exactly one intentional roll may POST to the roll endpoint; anything
    // more means returning to the roll page tried to roll again.
    let rollPosts = 0
    page.on('request', (request) => {
      if (request.method() !== 'POST') {
        return
      }
      let pathname = ''
      try {
        pathname = new URL(request.url()).pathname
      } catch {
        // Non-hierarchical URLs (e.g. data:) never target the roll endpoint.
        return
      }
      if (pathname.endsWith('/v1/roll/')) {
        rollPosts += 1
      }
    })

    // ComicVine-backed layers are fulfilled at the network; the roll and the
    // pending session stay real.
    await page.route('**/v1/issues/*/comicvine', (route) =>
      route.fulfill({ json: issueIntelligencePayload() }),
    )
    await page.route('**/v1/creators/*', (route) =>
      route.fulfill({ json: creatorDetailPayload() }),
    )

    // 1. Roll once to enter the rating view (the in-flight read).
    await gotoRollPage(page)
    await page.getByTestId('roll-primary-action').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    expect(rollPosts).toBe(1)

    // 2. Click the creator on the roll page (auto-expanded Creators section).
    const creatorLink = page.getByRole('link', { name: 'View creator Test Creator' })
    await expect(creatorLink).toBeVisible({ timeout: 20000 })
    await creatorLink.click()

    // 3. Verify we are on the creator detail page.
    await expect(page).toHaveURL(/\/creators\/creator(%3A|:)7/)
    await expect(page.getByRole('heading', { name: 'Test Creator' })).toBeVisible()

    // 4. Use the browser back button.
    await page.goBack()

    // 5. The previous roll page returns with the same in-flight read and no
    // additional roll attempt.
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByTestId('rating-view-top')).toBeVisible({ timeout: 20000 })
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    expect(rollPosts).toBe(1)
  })
})
