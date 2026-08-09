import { expect, test } from './fixtures'
import { createThread } from './helpers'

test.describe('Crossovers human-readable membership selection', () => {
  test('adds whole-series and issue-range memberships on mobile without thread IDs', async ({ authenticatedPage }) => {
    await authenticatedPage.setViewportSize({ width: 390, height: 844 })

    await createThread(authenticatedPage, {
      title: 'Mobile Whole Series',
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    })
    await createThread(authenticatedPage, {
      title: 'Mobile Range Series',
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    })

    await authenticatedPage.goto('/crossovers')
    await expect(authenticatedPage.getByRole('heading', { name: 'Crossovers' })).toBeVisible()

    await authenticatedPage.getByLabel('New crossover').fill('Mobile Selector Crossover')
    await authenticatedPage.getByRole('button', { name: 'Create crossover' }).click()
    await expect(authenticatedPage.getByText('Mobile Selector Crossover', { exact: true })).toBeVisible()

    await authenticatedPage.getByText('Mobile Selector Crossover', { exact: true }).click()

    const wholeSeriesForm = authenticatedPage.locator('form[aria-label="Add thread to Mobile Selector Crossover"]')
    const wholeSeriesSearch = wholeSeriesForm.getByRole('searchbox', { name: 'Whole comic series' })
    await expect(wholeSeriesSearch).toBeVisible()
    await expect(wholeSeriesForm).not.toContainText(/thread id/i)
    await wholeSeriesSearch.fill('Mobile Whole')
    await wholeSeriesForm.getByRole('option', { name: /Mobile Whole Series/ }).click()
    await expect(wholeSeriesSearch).toHaveValue('Mobile Whole Series')
    await wholeSeriesForm.getByRole('button', { name: 'Add series' }).click()
    await expect(authenticatedPage.getByRole('status')).toContainText('Mobile Whole Series added to crossover.')

    const rangeForm = authenticatedPage.locator('form[aria-label="Add issue range to Mobile Selector Crossover"]')
    const rangeSeriesSearch = rangeForm.getByRole('searchbox', { name: 'Comic series for issue range' })
    await expect(rangeSeriesSearch).toBeVisible()
    await expect(rangeForm).not.toContainText(/thread id/i)
    await rangeSeriesSearch.fill('Mobile Range')
    await rangeForm.getByRole('option', { name: /Mobile Range Series/ }).click()
    await expect(rangeSeriesSearch).toHaveValue('Mobile Range Series')

    const firstIssue = rangeForm.getByRole('combobox', { name: 'First issue' })
    const lastIssue = rangeForm.getByRole('combobox', { name: 'Last issue' })
    await expect(firstIssue).toBeEnabled()
    await expect(lastIssue).toBeEnabled()
    await firstIssue.selectOption({ label: '#1' })
    await lastIssue.selectOption({ label: '#2' })
    await rangeForm.getByRole('button', { name: 'Add range' }).click()

    await expect(authenticatedPage.getByRole('status')).toContainText('2 added, 0 already present.')
  })
})
