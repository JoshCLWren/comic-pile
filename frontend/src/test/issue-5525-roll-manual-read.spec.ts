/**
 * P0 #5525: Intentional manual reading is separate from random Roll offers.
 * These authenticated Chromium paths run with real Rust APIs and test users.
 */
import { test, expect } from './fixtures'
import { createThread, gotoRollPage, rollPoolThreadByTitle } from './helpers'

test.describe('P0 #5525 Roll manual selection', () => {
  test('Read Now from a die face opens an exact owned issue with no pending offer write', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Manual Roll Face'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    const rollRequests: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'GET') return
      const path = new URL(request.url()).pathname
      // `/issues/cards` is the batched read-model projection used to hydrate
      // the exact issue card, not a pending-offer or read-state write.
      if (
        (path.includes('/roll/offers') || path.includes('/issues/')) &&
        !path.includes('/issues/cards')
      ) {
        rollRequests.push(`${request.method()} ${path}`)
      }
    })

    await rollPoolThreadByTitle(page, title).click()
    const actionSheet = page.getByRole('dialog')
    await actionSheet.getByRole('button', { name: 'Read Now' }).click()
    const manualCard = page.getByTestId('direct-read-issue-panel')
    await expect(manualCard).toBeVisible()
    await expect(manualCard.getByRole('article', { name: `Issue ${title} #1` })).toBeVisible()
    await manualCard.getByRole('button', { name: 'Read now', exact: true }).click()
    await expect(manualCard.getByRole('slider')).toBeVisible()
    await manualCard.getByRole('button', { name: 'Cancel' }).click()
    expect(rollRequests).toEqual([])
    await expect(page).toHaveURL(/\/$/)
  })

  test('Pick manually opens any selected owned issue without generating an automatic offer', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Independent Manual Pick'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    const disallowed: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'GET') return
      const path = new URL(request.url()).pathname
      if (path.includes('roll/override') || path.includes('/roll/offer')) {
        disallowed.push(path)
      }
    })

    await page.getByRole('button', { name: 'Pick manually', exact: true }).click()
    const picker = page.getByRole('dialog', { name: 'Pick manually' })
    await picker.getByRole('combobox', { name: 'Series' }).fill(title)
    await picker.getByRole('option', { name: new RegExp(title) }).click()
    await picker.getByRole('button', { name: 'Open issue card' }).click()
    const card = page.getByTestId('direct-read-issue-panel')
    await expect(card.getByRole('article', { name: `Issue ${title} #1` })).toBeVisible()
    await card.getByRole('button', { name: 'Choose another owned issue' }).click()
    const chooser = page.getByTestId('direct-read-issue-picker')
    await chooser.getByRole('button', { name: `${title} #2 (unread)` }).click()
    await expect(card.getByRole('article', { name: `Issue ${title} #2` })).toBeVisible()
    expect(disallowed).toEqual([])
  })
})
