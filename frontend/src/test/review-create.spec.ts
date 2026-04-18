import { test, expect } from './fixtures'
import { SELECTORS, setRangeInput } from './helpers'

test.describe('Review Feature Flag E2E Tests', () => {
  test('rating submission completes without opening the review modal', async ({ authenticatedWithThreadsPage }) => {
    const page = authenticatedWithThreadsPage
    let reviewRequestSeen = false

    await page.route('**/v1/reviews/**', (route) => {
      reviewRequestSeen = true
      throw new Error(`Unexpected review request: ${route.request().url()}`)
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const mainDie = page.locator(SELECTORS.roll.mainDie)
    await expect(mainDie).toBeVisible()
    await mainDie.click()

    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 })
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.5')

    const submitButton = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")')
    await expect(submitButton).toBeVisible()

    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/rate/')),
      submitButton.click({ force: true }),
    ])

    await expect(page.getByText('Write a Review?')).toHaveCount(0)
    await expect(page.locator('textarea[placeholder*="Share your thoughts"]')).toHaveCount(0)
    await expect(page.getByText('Tap Die to Roll')).toBeVisible()
    expect(reviewRequestSeen).toBe(false)

    await page.unroute('**/v1/reviews/**')
  })
})
