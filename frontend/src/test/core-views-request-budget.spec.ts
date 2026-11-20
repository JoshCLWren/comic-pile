/**
 * Issue #4501: authenticated core-view request budgets.
 *
 * Browser-level evidence for the measured baseline: a Thread visit must not
 * read the usable-tag catalog until the reader opens the picker, and Queue
 * search must commit one request for the final debounced value.
 */
import { expect, type Request } from '@playwright/test'
import { test } from './fixtures'
import { createThread, waitForQueueReady } from './helpers'

type ApiCall = { method: string; path: string; search: string }

function recordApiCalls(page: import('@playwright/test').Page) {
  const calls: ApiCall[] = []
  const listener = (request: Request) => {
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) return
    calls.push({ method: request.method(), path: url.pathname, search: url.search })
  }
  page.on('request', listener)
  return {
    calls,
    stop: () => page.off('request', listener),
  }
}

/**
 * The authenticated fixture lands on `/`, and the Python test backend does not
 * serve the native Rust v2 bootstrap used by the production ingress. Allow only
 * that known local/CI boundary probe; these specs do not assert Roll behavior.
 */
function allowLocalRollBootstrapBoundary(
  allowExpectedBrowserFailures: { allow: (failure: { category: 'console'; message: string }) => void },
) {
  allowExpectedBrowserFailures.allow({
    category: 'console',
    message: '/api/v2/roll/bootstrap',
  })
  allowExpectedBrowserFailures.allow({
    category: 'console',
    message: 'status code 404',
  })
}

test.describe('Issue #4501: core-view request budgets', () => {
  test('Thread load skips the closed tag catalog and opens it on demand', async ({
    authenticatedPage: page,
    allowExpectedBrowserFailures,
  }) => {
    allowLocalRollBootstrapBoundary(allowExpectedBrowserFailures)
    const title = 'Budget Thread'
    const thread = await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })

    const recorder = recordApiCalls(page)
    await page.goto(`/thread/${thread.id}`)
    await expect(page.getByRole('heading', { name: title })).toBeVisible({ timeout: 20000 })
    await expect(page.getByRole('button', { name: 'Edit tags' }).first()).toBeVisible()
    await page.waitForTimeout(500)

    const catalogCalls = () =>
      recorder.calls.filter(
        (call) => call.method === 'GET' && call.path === '/api/v1/tags/',
      )

    expect(catalogCalls()).toHaveLength(0)
    expect(
      recorder.calls.filter(
        (call) => call.method === 'POST' && call.path === '/api/v1/threads/groups:batch',
      ),
    ).toHaveLength(1)

    await page.getByRole('button', { name: 'Edit tags' }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect.poll(() => catalogCalls().length).toBe(1)
    await page.waitForTimeout(300)
    expect(catalogCalls()).toHaveLength(1)
    recorder.stop()
  })

  test('Queue search commits only the final debounced value', async ({
    authenticatedPage: page,
    allowExpectedBrowserFailures,
  }) => {
    allowLocalRollBootstrapBoundary(allowExpectedBrowserFailures)
    await createThread(page, {
      title: 'Debounce Thread',
      format: 'Comic',
      issues_remaining: 1,
      total_issues: 1,
    })

    const recorder = recordApiCalls(page)
    await page.goto('/queue')
    await waitForQueueReady(page)
    await page.waitForTimeout(300)

    await page.getByRole('textbox', { name: 'Search series' }).type('robert', { delay: 50 })
    await page.waitForTimeout(700)

    const searchCalls = recorder.calls.filter(
      (call) =>
        call.method === 'GET' &&
        call.path === '/api/v1/threads/' &&
        new URLSearchParams(call.search).has('search'),
    )
    expect(searchCalls.map((call) => new URLSearchParams(call.search).get('search'))).toEqual([
      'robert',
    ])
    recorder.stop()
  })
})
