import { test, expect } from './fixtures'
import { createThread, SELECTORS, setRangeInput } from './helpers'

test.describe('Review Editing E2E Tests', () => {
  test('should edit existing review', async ({ freshUserPage }) => {
    const page = freshUserPage

    const token = await page.evaluate(() =>
      localStorage.getItem('auth_token') || (window as any).__COMIC_PILE_ACCESS_TOKEN
    )

    if (!token) {
      throw new Error('No auth token found')
    }

    const threadTitle = `Review Edit Thread ${Date.now()}`
    const thread = await createThread(page, {
      title: threadTitle,
      format: 'issue',
      issues_remaining: 10,
      total_issues: 10,
      issue_range: '1-10',
    })
    const threadId = thread.id

    const createReviewResponse = await page.request.post('/api/v1/reviews/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        thread_id: threadId,
        rating: 4.0,
        issue_number: '1',
        review_text: 'Original review',
      },
    })
    expect(createReviewResponse.ok()).toBeTruthy()

    const reviewsResponse = await page.request.get('/api/v1/reviews/', {
      headers: { 'Authorization': `Bearer ${token}` },
    })
    const reviewsData = await reviewsResponse.json()
    const latestReview = reviewsData.reviews?.find((review: any) => review.thread_id === threadId)

    expect(latestReview).toBeDefined()
    expect(latestReview.review_text).toBe('Original review')

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible({ timeout: 15000 })
    await page.locator(SELECTORS.roll.mainDie).click()

    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 })
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0')

    const submitButtonAgain = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")')
    await expect(submitButtonAgain).toBeVisible()
    await Promise.all([
      page.waitForResponse((response) => response.url().includes('/api/rate/')),
      submitButtonAgain.click({ force: true }),
    ])

    const reviewModal = page.locator('[data-testid="modal"]')
    const reviewModalOpened = await reviewModal.isVisible({ timeout: 2000 }).catch(() => false)

    if (!reviewModalOpened) {
      await expect(page.getByText('Write a Review?')).toHaveCount(0)

      const unchangedReviewsResponse = await page.request.get('/api/v1/reviews/', {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      const unchangedReviewsData = await unchangedReviewsResponse.json()
      const unchangedReview = unchangedReviewsData.reviews?.find(
        (review: any) => review.thread_id === latestReview.thread_id
      )

      expect(unchangedReview).toBeDefined()
      expect(unchangedReview.review_text).toBe('Original review')
      return
    }

    const textarea = page.locator('textarea[placeholder*="Share your thoughts"]')
    const textareaValue = await textarea.inputValue()

    if (textareaValue === 'Original review') {
      await textarea.fill('Updated review')

      const updateButton = page.locator('button:has-text("Save Review"), button:has-text("Update Review")')
      await Promise.all([
        page.waitForResponse((response) => response.url().includes('/v1/reviews/')),
        updateButton.click(),
      ])

      await expect(reviewModal).not.toBeVisible()

      const updatedReviewsResponse = await page.request.get('/api/v1/reviews/', {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      const updatedReviewsData = await updatedReviewsResponse.json()
      const updatedReview = updatedReviewsData.reviews?.find(
        (review: any) => review.thread_id === latestReview.thread_id
      )

      expect(updatedReview).toBeDefined()
      expect(updatedReview.review_text).toBe('Updated review')
    } else {
      const skipButton = page.locator('button:has-text("Skip")')
      await Promise.all([
        page.waitForResponse((response) => response.url().includes('/api/rate/')),
        skipButton.click(),
      ])

      await expect(reviewModal).not.toBeVisible()
    }
  })
})

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
      page.waitForResponse((response) => response.url().includes('/api/rate/')),
      submitButton.click({ force: true }),
    ])

    await expect(page.getByText('Write a Review?')).toHaveCount(0)
    expect(reviewRequestSeen).toBe(false)

    await page.unroute('**/v1/reviews/**')
  })
})
