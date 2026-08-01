import { test, expect } from './fixtures';
import { gotoRollPage, SELECTORS } from './helpers';

test.describe('Issue #688: Roll rating modal stacking and pointer interception', () => {
  test('roll opening the rating panel closes a competing thread dialog', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/')
    await expect(authenticatedWithThreadsPage.locator('[data-roll-pool]')).toBeVisible({ timeout: 10000 })

    // Start a roll; the animation gives time for the user to open a thread dialog.
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie)

    // Open a thread's dialog while the roll animation is still running.
    const firstPoolThread = authenticatedWithThreadsPage.locator('[data-roll-pool] [role="button"]').first()
    await firstPoolThread.click()
    await expect(authenticatedWithThreadsPage.getByRole('dialog')).toBeVisible()

    // The roll completes and the rating panel opens. The competing dialog must
    // not remain mounted over it — otherwise its backdrop intercepts the button.
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 })
    await expect(authenticatedWithThreadsPage.getByRole('dialog')).toHaveCount(0)

    // Save & Continue must receive pointer input.
    const saveButton = authenticatedWithThreadsPage.getByTestId('save-and-continue')
    await expect(saveButton).toBeVisible()
    await saveButton.click()
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie)).toBeVisible({ timeout: 10000 })
  })

  test('Escape dismisses only the topmost thread dialog over the rating panel', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/')
    await expect(authenticatedWithThreadsPage.locator('[data-roll-pool]')).toBeVisible({ timeout: 10000 })

    // Enter the rating panel by reading a thread.
    const firstPoolThread = authenticatedWithThreadsPage.locator('[data-roll-pool] [role="button"]').first()
    await firstPoolThread.click()
    await expect(authenticatedWithThreadsPage.getByRole('dialog')).toBeVisible()
    await authenticatedWithThreadsPage.getByRole('button', { name: 'Read Now' }).click()
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 })

    // Open a second thread's dialog on top of the rating panel.
    const otherPoolThread = authenticatedWithThreadsPage
      .locator('[data-roll-pool] [role="button"]')
      .nth(1)
    await otherPoolThread.click()
    await expect(authenticatedWithThreadsPage.getByRole('dialog')).toBeVisible()

    // Escape dismisses only the dialog, leaving the rating panel intact.
    await authenticatedWithThreadsPage.keyboard.press('Escape')
    await expect(authenticatedWithThreadsPage.getByRole('dialog')).toHaveCount(0)
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible()
    await expect(authenticatedWithThreadsPage.getByTestId('save-and-continue')).toBeVisible()
  })
})
