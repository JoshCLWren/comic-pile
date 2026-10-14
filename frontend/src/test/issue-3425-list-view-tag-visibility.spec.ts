/**
 * Issue #3425: a tagged series must not read as untagged outside its own page.
 *
 * Dogfood report: tag Spider-Man with "Physical", open the Queue, and the row
 * shows no tag; roll, and the die face shows no tag either. Tags were only
 * visible on the thread's own page, so there was no at-a-glance signal for
 * tag-based decisions before rolling.
 *
 * These browser checks close that loop end to end:
 *
 * 1. A Queue row renders the series' tag chips from the list projection.
 * 2. A Roll die face renders the same chips from the bootstrap projection.
 * 3. An untagged series renders no tag group at all on either surface — the
 *    fix must not add empty chrome to every row.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, getAuthToken, waitForQueueReady } from './helpers'

const TAGGED_TITLE = 'Tagged Series'
const UNTAGGED_TITLE = 'Untagged Series'
const TAG_NAME = 'Physical'

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = await getAuthToken(page)
  const csrfResponse = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(csrfResponse.ok()).toBeTruthy()
  // SAFETY: the CSRF bootstrap response always carries csrf_token.
  const { csrf_token: csrf } = (await csrfResponse.json()) as { csrf_token?: string }
  expect(csrf).toBeDefined()
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf!,
  }
}

/** Create a private tag owned by the test user and attach it to one thread. */
async function tagThread(page: Page, threadId: number, name: string): Promise<void> {
  const headers = await authHeaders(page)

  const createResponse = await page.request.post('/api/tags/', {
    headers,
    data: { name, color: 'red', scope: 'private' },
  })
  expect(createResponse.ok(), await createResponse.text()).toBeTruthy()
  // SAFETY: a successful create always returns the created tag with its id.
  const { tag } = (await createResponse.json()) as { tag: { id: number } }

  const assignResponse = await page.request.post(`/api/tags/${tag.id}/assign/`, {
    headers,
    data: { target_type: 'Thread', target_id: threadId },
  })
  expect(assignResponse.ok(), await assignResponse.text()).toBeTruthy()
}

test.describe('Tags are visible on Queue rows and Roll die faces (issue #3425)', () => {
  test('a tagged series shows its tag on the Queue row and the Roll die face', async ({
    freshUserPage: page,
  }) => {
    const tagged = await createThread(page, {
      title: TAGGED_TITLE,
      format: 'Comic',
      issues_remaining: 3,
    })
    await createThread(page, {
      title: UNTAGGED_TITLE,
      format: 'Comic',
      issues_remaining: 2,
    })
    await tagThread(page, tagged.id, TAG_NAME)

    await page.goto('/queue', { waitUntil: 'domcontentloaded' })
    await waitForQueueReady(page)

    const taggedRow = page.getByTestId('queue-thread-item').filter({ hasText: TAGGED_TITLE })
    await expect(taggedRow).toBeVisible()
    await expect(taggedRow.getByRole('list', { name: `Tags for ${TAGGED_TITLE}` })).toBeVisible()
    await expect(taggedRow.getByText(TAG_NAME, { exact: true })).toBeVisible()

    // The untagged row gains no empty chrome.
    const untaggedRow = page.getByTestId('queue-thread-item').filter({ hasText: UNTAGGED_TITLE })
    await expect(untaggedRow).toBeVisible()
    await expect(untaggedRow.getByRole('list', { name: /^Tags for / })).toHaveCount(0)

    await gotoRollPage(page)
    const pool = page.locator('[data-roll-pool]')
    await expect(pool).toBeVisible({ timeout: 20000 })
    await expect(pool.getByText(TAG_NAME, { exact: true })).toBeVisible()
    await expect(
      pool.getByRole('list', { name: `Tags for ${TAGGED_TITLE}` }),
    ).toBeVisible()
    // Untagged die faces stay clean.
    await expect(pool.getByRole('list', { name: `Tags for ${UNTAGGED_TITLE}` })).toHaveCount(0)
  })
})