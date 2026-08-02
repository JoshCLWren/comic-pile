import { test, expect } from './fixtures'

test.describe('Bug Report Button', () => {
  test('opens modal when clicked', async ({ authenticatedPage }) => {
    const consoleErrors: string[] = []
    authenticatedPage.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    const button = authenticatedPage.getByRole('button', { name: /report a bug/i }).last()
    await expect(button).toBeVisible()
    await button.click()

    // Modal must open with the diagnostic info notice
    const modal = authenticatedPage.getByRole('dialog', { name: 'Report a Bug' })
    await expect(modal).toBeVisible({ timeout: 10000 })

    // Verify the diagnostics notice is shown
    await expect(authenticatedPage.getByText(/browser info & console errors/i)).toBeVisible()
  })

  test('moves the bug report entry point into the mobile nav', async ({ authenticatedPage }) => {
    await authenticatedPage.setViewportSize({ width: 390, height: 844 })
    await authenticatedPage.reload({ waitUntil: 'domcontentloaded' })

    await expect(authenticatedPage.getByRole('link', { name: /help page/i })).toHaveCount(0)

    const button = authenticatedPage.getByRole('navigation', { name: /main navigation/i }).getByLabel('Report a bug')
    await expect(button).toBeVisible()
    await button.click()

    const modal = authenticatedPage.getByRole('dialog', { name: 'Report a Bug' })
    await expect(modal).toBeVisible({ timeout: 10000 })
  })

  test('fits and scrolls on a 320px-wide viewport without horizontal overflow', async ({ authenticatedPage }) => {
    await authenticatedPage.setViewportSize({ width: 320, height: 400 })
    await authenticatedPage.reload({ waitUntil: 'domcontentloaded' })

    const reportButton = authenticatedPage.getByRole('button', { name: /report a bug/i }).last()
    await expect(reportButton).toBeVisible()
    await reportButton.click()

    const modal = authenticatedPage.getByRole('dialog', { name: 'Report a Bug' })
    await expect(modal).toBeVisible({ timeout: 10000 })

    // Exercise the validation-error state directly. The visible submit button is
    // correctly disabled while required fields are blank, but the form handler
    // still needs to keep its error message contained on a narrow viewport.
    await modal.locator('form').evaluate(form => {
      form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }))
    })
    await expect(modal.getByText('Title and description are required')).toBeVisible()

    const titleInput = modal.getByLabel('Title')
    const descriptionInput = modal.getByLabel('Description')

    await titleInput.fill('Test bug on narrow screen with an intentionally long title')
    await descriptionInput.fill(
      'This is an intentionally long description that verifies the form content remains contained inside the dialog on a 320px-wide viewport without widening the page.',
    )

    const submitButton = modal.getByRole('button', { name: 'Submit Report' })
    const cancelButton = modal.getByRole('button', { name: 'Cancel' })

    await expect(submitButton).toBeVisible()
    await expect(cancelButton).toBeVisible()

    const viewport = authenticatedPage.viewportSize()
    const modalBox = await modal.boundingBox()
    const submitBox = await submitButton.boundingBox()
    const cancelBox = await cancelButton.boundingBox()

    expect(viewport).not.toBeNull()
    expect(modalBox).not.toBeNull()
    expect(submitBox).not.toBeNull()
    expect(cancelBox).not.toBeNull()

    expect(modalBox!.x).toBeGreaterThanOrEqual(0)
    expect(modalBox!.x + modalBox!.width).toBeLessThanOrEqual(viewport!.width)

    for (const buttonBox of [submitBox!, cancelBox!]) {
      expect(buttonBox.x).toBeGreaterThanOrEqual(modalBox!.x)
      expect(buttonBox.x + buttonBox.width).toBeLessThanOrEqual(modalBox!.x + modalBox!.width)
    }

    const scrollRegion = modal.locator('.overflow-y-auto')
    const scrollMetrics = await scrollRegion.evaluate(element => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    }))
    expect(scrollMetrics.scrollHeight).toBeGreaterThan(scrollMetrics.clientHeight)

    await scrollRegion.evaluate(element => {
      element.scrollTop = element.scrollHeight
    })
    await expect.poll(() => scrollRegion.evaluate(element => element.scrollTop)).toBeGreaterThan(0)

    const documentWidths = await authenticatedPage.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))
    expect(documentWidths.scrollWidth).toBeLessThanOrEqual(documentWidths.clientWidth)
  })
})
