import { test, expect } from './fixtures'

test.describe('Review Feature Flag E2E Tests', () => {
  test('thread details do not render the review section while reviews are disabled', async ({ authenticatedWithThreadsPage }) => {
    const page = authenticatedWithThreadsPage
    const token = await page.evaluate(() =>
      localStorage.getItem('auth_token') || (window as any).__COMIC_PILE_ACCESS_TOKEN
    )

    if (!token) {
      throw new Error('No auth token found')
    }

    const threadsResponse = await page.request.get('/api/threads/', {
      headers: { 'Authorization': `Bearer ${token}` },
    })
    expect(threadsResponse.ok()).toBeTruthy()
    const threadsData = await threadsResponse.json()
    const threads = threadsData.threads ?? threadsData
    expect(threads.length).toBeGreaterThan(0)

    await page.goto(`/thread/${threads[0].id}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/Reviews/)).toHaveCount(0)
    await expect(page.getByText('No reviews yet.')).toHaveCount(0)
  })
})
