import { test, expect } from './fixtures'
import { SELECTORS, setRangeInput } from './helpers'

test.describe('Review Feature Flag E2E Tests', () => {
  test('existing review data does not reopen the review prompt when reviews are disabled', async ({ authenticatedWithThreadsPage }) => {
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

    const thread = threads[0]
    const reviewResponse = await page.request.post('/api/v1/reviews/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        thread_id: thread.id,
        rating: 4.0,
        review_text: 'Seeded review text',
        ...(thread.issue_number ? { issue_number: thread.issue_number } : {}),
      },
    })
    expect(reviewResponse.ok()).toBeTruthy()

    let reviewRequestSeen = false
    await page.route('**/v1/reviews/**', () => {
      reviewRequestSeen = true
      throw new Error('Unexpected review request while reviews are disabled')
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const mainDie = page.locator(SELECTORS.roll.mainDie)
    await expect(mainDie).toBeVisible()
    await mainDie.click()

    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 })
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0')

    const submitButton = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")')
    await expect(submitButton).toBeVisible()

    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/rate/')),
      submitButton.click({ force: true }),
    ])

    await expect(page.getByText('Write a Review?')).toHaveCount(0)
    expect(reviewRequestSeen).toBe(false)

    await page.unroute('**/v1/reviews/**')
  })
})
