/**
 * Issue #4654: Edit Series preview must show human-readable before/after
 * effects, and cancel/retry must never mutate the series.
 *
 * The preview response is supplied as a documented fixture through page.route;
 * all navigation, auth and the Edit Series surface are real. This keeps the
 * spec deterministic while covering the cancel and failed-preview recovery
 * paths that the Rust HTTP tests cannot exercise.
 */
import { expect, test } from '@playwright/test'
import { createThread, registerUser } from './helpers'

const previewBody = (threadId: number, threadTitle: string) => ({
  thread_id: threadId,
  thread_title: threadTitle,
  requested_strategy: 'safe_default',
  default_outcome: {
    strategy: 'safe_default',
    can_commit: true,
    preserves_existing_relative_order: true,
    before: [{
      issue_id: 7,
      issue_number: '129',
      position: 1,
      is_new: false,
      series_title: threadTitle,
      source_lists: ['Authored order'],
      is_read: true,
      is_mapped: true,
      has_rating: true,
      frontier_label: 'current unread (Queue/Roll frontier)',
      effect: 'kept #129 at position 1',
      is_duplicate: false,
    }],
    after: [
      {
        issue_id: 7,
        issue_number: '129',
        position: 1,
        is_new: false,
        series_title: threadTitle,
        source_lists: ['Authored order'],
        is_read: true,
        is_mapped: true,
        has_rating: true,
        frontier_label: 'current unread (Queue/Roll frontier)',
        effect: 'kept #129 at position 1',
        is_duplicate: false,
      },
      {
        issue_id: null,
        issue_number: '101',
        position: 2,
        is_new: true,
        series_title: threadTitle,
        source_lists: [],
        is_read: false,
        is_mapped: false,
        has_rating: false,
        frontier_label: null,
        effect: 'new issue #101 inserted at position 2',
        is_duplicate: true,
      },
    ],
    added_issue_numbers: ['101'],
    graph: { status: 'ok', cycles: [] },
    conflict_message: null,
  },
  numeric_resort_outcome: null,
})

test('Edit Series preview shows labels and cancel leaves the series unchanged', async ({ page }) => {
  const suffix = `${Date.now()}`
  await registerUser(page, {
    username: `preview4654${suffix}`,
    email: `preview4654${suffix}@example.com`,
    password: 'PreviewTest123!',
  })
  const threadTitle = `Preview 4654 ${suffix}`
  const thread = await createThread(page, {
    title: threadTitle,
    format: 'comic',
    total_issues: 1,
    issues_remaining: 1,
  })

  let createCalls = 0
  await page.route(`**/api/v2/threads/${thread.id}/issues/preview`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(previewBody(thread.id, threadTitle)),
    })
  })
  await page.route(`**/api/v2/threads/${thread.id}/issues`, async (route) => {
    if (route.request().method() === 'POST') createCalls += 1
    await route.continue()
  })

  await page.goto(`/thread/${thread.id}`)
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Edit Series', exact: true })
  await expect(editor).toBeVisible()

  await editor.getByTestId('issue-add-input').fill('101')
  await editor.getByTestId('issue-add-button').click()

  const modal = page.getByTestId('edit-series-preview-modal')
  await expect(modal).toBeVisible()
  await expect(modal).toContainText(`${threadTitle} #129`)
  await expect(modal).toContainText('List: Authored order')
  await expect(modal).toContainText('kept #129 at position 1')
  await expect(modal).toContainText('current unread (Queue/Roll frontier)')
  await expect(modal).toContainText('new issue #101 inserted at position 2')
  await expect(modal).toContainText('Possible physical duplicate')

  await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(modal).toBeHidden()
  expect(createCalls).toBe(0)
  await expect(editor.getByTestId('pending-creates')).toHaveCount(0)
})

test('Edit Series failed preview can be retried from the error modal', async ({ page }) => {
  const suffix = `${Date.now()}`
  await registerUser(page, {
    username: `previewretry${suffix}`,
    email: `previewretry${suffix}@example.com`,
    password: 'PreviewTest123!',
  })
  const threadTitle = `Retry Preview 4654 ${suffix}`
  const thread = await createThread(page, {
    title: threadTitle,
    format: 'comic',
    total_issues: 1,
    issues_remaining: 1,
  })

  let shouldFail = true
  await page.route(`**/api/v2/threads/${thread.id}/issues/preview`, async (route) => {
    if (shouldFail) {
      shouldFail = false
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'preview exploded' }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(previewBody(thread.id, threadTitle)),
    })
  })

  await page.goto(`/thread/${thread.id}`)
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Edit Series', exact: true })
  await expect(editor).toBeVisible()

  await editor.getByTestId('issue-add-input').fill('101')
  await editor.getByTestId('issue-add-button').click()

  const errorModal = page.getByTestId('edit-series-preview-error-modal')
  await expect(errorModal).toBeVisible()
  await expect(errorModal).toContainText('preview exploded')

  await errorModal.getByTestId('retry-preview-add').click()
  await expect(page.getByTestId('edit-series-preview-modal')).toBeVisible()
  await expect(errorModal).toBeHidden()
})
