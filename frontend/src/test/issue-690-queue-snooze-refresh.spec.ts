import { test, expect } from './fixtures'
import { createThread, gotoQueue, waitForThreadInQueue } from './helpers'

function isFullThreadListRequest(url: string, method: string): boolean {
  if (method !== 'GET') return false
  const parsed = new URL(url)
  return parsed.pathname === '/api/threads/' && parsed.searchParams.get('page_size') === '200'
}

test.describe('Queue snooze refresh contract (#690)', () => {
  test('snooze and unsnooze update visible state without refetching the full thread list', async ({ authenticatedPage }) => {
    const title = `Queue snooze refresh ${Date.now()}`
    await createThread(authenticatedPage, {
      title,
      format: 'Comics',
      issues_remaining: 5,
    })

    await gotoQueue(authenticatedPage)
    await waitForThreadInQueue(authenticatedPage, title)

    const card = authenticatedPage
      .getByTestId('queue-thread-item')
      .filter({ hasText: title })
    const fullThreadListRequests: string[] = []
    const captureFullThreadListRequest = (request: { url(): string; method(): string }) => {
      if (isFullThreadListRequest(request.url(), request.method())) {
        fullThreadListRequests.push(request.url())
      }
    }

    authenticatedPage.on('request', captureFullThreadListRequest)

    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/snooze/') &&
        response.request().method() === 'POST' &&
        response.status() < 300,
      ),
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/sessions/current/') &&
        response.request().method() === 'GET' &&
        response.status() < 300,
      ),
      card.getByRole('button', { name: 'Snooze' }).click({ force: true }),
    ])

    await expect(card.getByRole('button', { name: 'Unsnooze' })).toBeAttached()
    expect(fullThreadListRequests).toEqual([])

    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/snooze/') &&
        response.url().includes('/unsnooze') &&
        response.request().method() === 'POST' &&
        response.status() < 300,
      ),
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/sessions/current/') &&
        response.request().method() === 'GET' &&
        response.status() < 300,
      ),
      card.getByRole('button', { name: 'Unsnooze' }).click({ force: true }),
    ])

    await expect(card.getByRole('button', { name: 'Snooze' })).toBeAttached()
    expect(fullThreadListRequests).toEqual([])

    authenticatedPage.off('request', captureFullThreadListRequest)
  })
})
