import { expect, type Page } from '@playwright/test';
import { test } from './fixtures';

const DESKTOP_VIEWPORT = { width: 1280, height: 900 };

function rollBootstrapPayload() {
  return {
    current_die: 6,
    last_rolled_result: null,
    pending_thread_id: null,
    roll_pool: [
      {
        id: 1,
        title: 'Thread 1',
        format: 'Standard',
        issues_remaining: 5,
        queue_position: 1,
        total_issues: 10,
        reading_progress: 0,
        issue_id: 101,
        issue_number: '1',
        next_issue_id: 102,
        next_issue_number: '2',
        last_rolled_result: null,
        creators: [
          {
            name: 'Test Creator',
            roles: ['Writer'],
            id: 7,
          },
        ],
      },
    ],
    snoozed_threads: [],
    skipped_threads: [],
    blocked_threads: [],
    session_mode: null,
  };
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
        thread_title: 'Thread 1',
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
  };
}

test.describe('Issue #2544: Roll Page Back Button', () => {
  test('navigating to creator detail and back returns to roll page with dice visible', async ({ page }) => {
    await page.setViewportSize(DESKTOP_VIEWPORT);

    // Bypass authentication by mocking the /v1/auth/me call
    await page.route('**/v1/auth/me', (route) =>
      route.fulfill({ 
        status: 200, 
        json: { id: 1, username: 'testuser', email: 'test@example.com' } 
      })
    );

    // Mock Roll Bootstrap
    await page.route('**/v1/roll/bootstrap', (route) =>
      route.fulfill({ json: rollBootstrapPayload() })
    );

    // Mock Creator Detail
    await page.route('**/v1/creators/*', (route) =>
      route.fulfill({ json: creatorDetailPayload() })
    );

    // 1. Go to Roll Page
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-testid="main-die-3d"]')).toBeVisible();

    // 2. Click a creator on the Roll Page
    const creatorLink = page.getByRole('link', { name: /View creator Test Creator/ });
    await expect(creatorLink).toBeVisible();
    await creatorLink.click();

    // 3. Verify we are on Creator Detail Page
    await expect(page).toHaveURL(/\/creators\/creator:7/);
    await expect(page.getByRole('heading', { name: 'Test Creator' })).toBeVisible();

    // 4. Use Browser Back Button
    await page.goBack();

    // 5. Verify we are back on Roll Page and dice is visible
    await expect(page).toHaveURL('/');
    await expect(page.locator('[data-testid="main-die-3d"]')).toBeVisible();
  });
});
