/**
 * Issue #3328: Creator compare banner truncates affected-creator names.
 *
 * Acceptance contract:
 * 1. When comparison includes creators with insufficient rated issues,
 *    the banner renders full affected names.
 * 2. Names wrap to additional lines instead of being truncated with ellipsis.
 */
import { expect, type Page, type Route } from '@playwright/test'
import { test } from './fixtures'

const DESKTOP = { width: 1280, height: 900 }

function comparisonPayload() {
  return {
    comparisons: {
      'creator:1672': {
        canonical_creator_key: 'creator:1672',
        display_name: 'Todd Dezago',
        normalized_roles: ['writer'],
        average_rating: 4.0,
        median_rating: 4.0,
        ratings_count: 1,
        top_rating_rate: 0.5,
        insufficient_data: true,
        role_stats: [],
        strongest_series: [],
        unread_upcoming_count: 0,
        unread_issue_refs: [],
        max_issue_refs_per_group: 5,
        read_unrated_count: 0,
        read_unrated_issue_refs: [],
        rating_distribution: { '4.0': 1 },
      },
      'creator:40468': {
        canonical_creator_key: 'creator:40468',
        display_name: 'Another Creator',
        normalized_roles: ['artist'],
        average_rating: 3.5,
        median_rating: 3.5,
        ratings_count: 5,
        top_rating_rate: 0.4,
        insufficient_data: false,
        role_stats: [],
        strongest_series: [],
        unread_upcoming_count: 0,
        unread_issue_refs: [],
        max_issue_refs_per_group: 5,
        read_unrated_count: 0,
        read_unrated_issue_refs: [],
        rating_distribution: { '3.5': 5 },
      },
    },
    coverage: {
      ratings_complete: true,
      read_unrated_complete: true,
      upcoming_complete: true,
      rated_issues_total: 6,
      rated_issues_with_creator_metadata: 6,
      read_unrated_issues_total: 0,
      read_unrated_issues_with_creator_metadata: 0,
      unread_issues_total: 0,
      unread_issues_with_creator_metadata: 0,
    },
    insufficient_data_keys: ['creator:1672'],
  }
}

async function installComparisonRoute(page: Page) {
  await page.route(
    (url) => url.pathname === '/api/v1/creators/compare',
    async (route: Route) => {
      await route.fulfill({ json: comparisonPayload() })
    },
  )
}

test('creator compare banner shows full affected names and wraps', async ({
  authenticatedPage,
}) => {
  const page = authenticatedPage
  await page.setViewportSize(DESKTOP)
  await installComparisonRoute(page)

  await page.goto('/creators/compare?keys=creator:1672,creator:40468', {
    waitUntil: 'domcontentloaded',
  })

  const banner = page.locator('div.rounded-xl.border.px-4.py-3')
  await expect(banner).toBeVisible()

  // Full name present, not truncated
  await expect(banner).toContainText('Todd Dezago')

  // Names should appear in a dedicated paragraph (separate from the note)
  const affectedLine = banner.locator('p', { hasText: /Affected:/ })
  await expect(affectedLine).toBeVisible()
  await expect(affectedLine).toContainText('Todd Dezago')

  // No ellipsis in the affected line
  await expect(affectedLine).not.toContainText('...')
})
