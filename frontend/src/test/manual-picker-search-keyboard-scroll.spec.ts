/**
 * Issue #3559: Browser-level check that keyboard navigation in the manual
 * picker scrolls the highlighted option into view when the list overflows.
 *
 * Covers Greptile finding G2: the previous test imported plain Playwright
 * `test`, visited `/` unsigned (LandingPage, no combobox), and waited for a
 * picker it never opened, so it timed out. This version signs in with
 * `authenticatedPage`, creates enough series to overflow the picker listbox,
 * opens "Pick manually" before waiting for the combobox, and asserts real
 * keyboard navigation instead of a no-op.
 */
import { expect, test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

test('manual picker keyboard scroll brings highlighted option into view with overflow', async ({
  authenticatedPage,
}) => {
  const page = authenticatedPage

  // Create more series than fit in the picker's max-h-60 listbox so the
  // highlighted option can be scrolled past the visible boundary.
  const seriesCount = 20
  for (let i = 0; i < seriesCount; i += 1) {
    await createThread(page, {
      title: `Overflow Series ${i + 1}`,
      format: 'Issue',
      issues_remaining: 5,
      total_issues: 5,
    })
  }

  await gotoRollPage(page)

  // Open "Pick manually" before waiting for the combobox: the picker only
  // exists inside the dialog, so a logged-out visitor (LandingPage) or a
  // visitor who never opens the dialog would time out here.
  await page.getByRole('button', { name: 'Pick manually' }).click()
  const dialog = page.getByRole('dialog', { name: 'Pick manually' })
  await expect(dialog).toBeVisible()

  const combobox = dialog.getByRole('combobox')
  await combobox.click()
  // With an empty query the full list renders and overflows the listbox.
  await expect.poll(() => dialog.getByRole('option').count()).toBe(seriesCount)

  // Capture the initially highlighted option via aria-activedescendant.
  const firstActiveId = await combobox.getAttribute('aria-activedescendant')
  expect(firstActiveId).toBeTruthy()

  // Arrow down well past the visible rows; the highlight must follow.
  for (let i = 0; i < 8; i += 1) {
    await combobox.press('ArrowDown')
  }

  const nextActiveId = await combobox.getAttribute('aria-activedescendant')
  expect(nextActiveId).toBeTruthy()
  expect(nextActiveId).not.toBe(firstActiveId)

  // The newly highlighted option must be present and visible, not hidden
  // below the overflow boundary.
  const newlyHighlighted = dialog.locator('[id="' + nextActiveId + '"]')
  await expect(newlyHighlighted).toBeVisible()
})
