import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'

async function createThread(page: Page, title: string, issuesRemaining = 3): Promise<void> {
  await page.goto('/queue')
  await page.getByRole('button', { name: 'Add new series' }).click()
  await page.getByPlaceholder('Series title').fill(title)
  await page.getByPlaceholder('Number of issues').fill(issuesRemaining.toString())
  await page.getByRole('button', { name: 'Add series' }).click()
  await expect(page.getByText('Series added successfully')).toBeVisible()
}

async function setManualDie(page: Page, dieSize: number): Promise<void> {
  await page.goto('/roll')
  // Click on the die selector to open the modal
  await page.getByRole('button', { name: `Current die d6, automatic mode` }).click()
  
  // Wait for the die modal to be visible
  await expect(page.locator('[data-testid="die-modal"]')).toBeVisible()
  
  // Click on the desired die size
  await page.getByRole('button', { name: `d${dieSize}` }).click()
  
  // Wait for the modal to close and die to be updated
  await expect(page.locator('[data-testid="die-modal"]')).not.toBeVisible()
  await expect(page.getByText(`d${dieSize}`)).toBeVisible()
}

async function enterRatingView(page: Page, title: string): Promise<void> {
  await page.goto('/roll')
  await page.locator('#main-die-3d').click()
  await page.getByText(title).first().click()
  await expect(page.getByTestId('rating-actions')).toBeVisible()
}

test.describe('DecisionCard manual die mode', () => {
  test('shows manual die message when manual die is set', async ({ authenticatedPage }: { authenticatedPage: Page }) => {
    const page = authenticatedPage
    const threadTitle = 'Test Comic for Manual Die'
    
    // Create a test thread
    await createThread(page, threadTitle, 3)
    
    // Set manual die to d20
    await setManualDie(page, 20)
    
    // Go to roll page and roll to get the thread
    await enterRatingView(page, threadTitle)
    
    // Verify that manual die message is shown instead of ladder move
    const dieDisplay = page.locator('text=Manual die pinned at d20')
    await expect(dieDisplay).toBeVisible()
    
    // Verify that the ladder move is NOT shown
    const ladderMove = page.locator('text=d20 → d12')
    await expect(ladderMove).not.toBeVisible()
    
    // Verify that rating still works
    const ratingSlider = page.locator('role=slider[name="Rating from 0.5 to 5.0 in steps of 0.5"]')
    await expect(ratingSlider).toBeVisible()
    await expect(ratingSlider).toHaveValue('3.0')
    
    // Test that we can still submit the rating
    await ratingSlider.fill('4.0')
    await page.getByRole('button', { name: 'Mark read & save' }).click()
    
    // Should return to roll view
    await expect(page.locator('#main-die-3d')).toBeVisible()
  })

  test('shows ladder move when in auto mode', async ({ authenticatedPage }: { authenticatedPage: Page }) => {
    const page = authenticatedPage
    const threadTitle = 'Test Comic for Auto Mode'
    
    // Create a test thread
    await createThread(page, threadTitle, 3)
    
    // Ensure we're in auto mode (don't set manual die)
    await page.goto('/roll')
    await expect(page.getByText('Automatic mode is active')).toBeVisible()
    
    // Go to roll page and roll to get the thread
    await enterRatingView(page, threadTitle)
    
    // Verify that ladder move is shown in auto mode
    const ladderMove = page.locator('text=d6 → d8')
    await expect(ladderMove).toBeVisible()
    
    // Verify that manual die message is NOT shown
    const manualDieMessage = page.locator('text=Manual die pinned at d6')
    await expect(manualDieMessage).not.toBeVisible()
    
    // Test that rating still works
    const ratingSlider = page.locator('role=slider[name="Rating from 0.5 to 5.0 in steps of 0.5"]')
    await expect(ratingSlider).toBeVisible()
    await expect(ratingSlider).toHaveValue('3.0')
  })

  test('switching between manual and auto mode updates display correctly', async ({ authenticatedPage }: { authenticatedPage: Page }) => {
    const page = authenticatedPage
    const threadTitle = 'Test Comic for Mode Switch'
    
    // Create a test thread
    await createThread(page, threadTitle, 3)
    
    // Start in auto mode
    await page.goto('/roll')
    await enterRatingView(page, threadTitle)
    
    // Should show ladder move in auto mode
    await expect(page.locator('text=d6 → d8')).toBeVisible()
    await expect(page.locator('text=Manual die pinned at d6')).not.toBeVisible()
    
    // Cancel rating and go back to roll view
    await page.getByRole('button', { name: 'Cancel roll' }).click()
    await expect(page.locator('#main-die-3d')).toBeVisible()
    
    // Set manual die to d20
    await setManualDie(page, 20)
    
    // Roll again to get the same thread
    await page.locator('#main-die-3d').click()
    await page.getByText(threadTitle).first().click()
    
    // Should show manual die message in manual mode
    await expect(page.locator('text=Manual die pinned at d20')).toBeVisible()
    await expect(page.locator('text=d20 → d12')).not.toBeVisible()
    
    // Clear manual die and go back to auto mode
    await page.getByRole('button', { name: 'Exit manual mode (currently d20)' }).click()
    await expect(page.getByText('Automatic mode is active')).toBeVisible()
    
    // Cancel rating and roll again
    await page.getByRole('button', { name: 'Cancel roll' }).click()
    await page.locator('#main-die-3d').click()
    await page.getByText(threadTitle).first().click()
    
    // Should show ladder move again in auto mode
    await expect(page.locator('text=d6 → d8')).toBeVisible()
    await expect(page.locator('text=Manual die pinned at d6')).not.toBeVisible()
  })
})