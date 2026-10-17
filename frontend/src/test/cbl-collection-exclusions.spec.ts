import { test, expect } from './fixtures'
import { createThread, getAuthToken } from './helpers'

/** Excluding an owned Issue must survive the CBL preview's local Include controls. */
test('collection-excluded material stays unselected in the reviewed CBL source', async ({ authenticatedPage }) => {
  const page = authenticatedPage
  const thread = await createThread(page, { title: 'Absolute Flash Exclusion Browser', format: 'Comics', issues_remaining: 1, total_issues: 1 })
  const token = await getAuthToken(page)
  const csrfResponse = await page.request.get('/api/auth/csrf', { headers: { Authorization: `Bearer ${token}` } })
  expect(csrfResponse.ok()).toBeTruthy()
  // SAFETY: only csrf_token is read from the response.
  const csrf = await csrfResponse.json() as { csrf_token: string }
  const headers = { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrf.csrf_token }
  const issueResponse = await page.request.get(`/api/v1/threads/${thread.id}/issues`, { headers })
  expect(issueResponse.ok()).toBeTruthy()
  // SAFETY: only owned Issue IDs are read from the response.
  const issues = await issueResponse.json() as { issues: Array<{ id: number }> }
  const issueId = issues.issues[0].id
  const exclusion = await page.request.post('/api/v1/collection-exclusions', { headers, data: { issue_id: issueId } })
  expect(exclusion.ok(), await exclusion.text()).toBeTruthy()
  const sourceName = `Collection Exclusion Browser ${thread.id}`
  const seed = await page.request.post('/api/test/cbl-source', { headers, data: {
    name: sourceName, entries: [{ position: 1, series_name: 'Absolute Flash Exclusion Browser', issue_number: '1', issue_id: issueId }],
  } })
  expect(seed.ok(), await seed.text()).toBeTruthy()
  await page.goto('/continuity-plans')
  await page.getByRole('button', { name: 'New Reading Plan' }).click()
  await page.getByLabel('Plan name').fill(`Exclusion Preview ${thread.id}`)
  await page.getByRole('button', { name: 'Save plan' }).click()
  await expect(page).toHaveURL(/\/continuity-plans\/\d+/)
  await page.getByRole('button', { name: 'Add from CBL' }).click()
  await page.getByLabel('Search source lists').fill(sourceName)
  await page.getByRole('button', { name: 'Search' }).click()
  await page.getByRole('button', { name: new RegExp(sourceName) }).click()
  const include = page.getByRole('checkbox', { name: 'Include Absolute Flash Exclusion Browser #1' })
  await expect(page.getByText('Excluded from your collection')).toBeVisible()
  await expect(include).not.toBeChecked()
  await expect(include).toBeDisabled()
  await page.getByRole('group', { name: 'Absolute Flash Exclusion Browser series choice' }).getByRole('button', { name: 'Include', exact: true }).click()
  await expect(include).not.toBeChecked()
  await expect(include).toBeDisabled()
})
