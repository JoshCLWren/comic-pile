import { test, expect } from '@playwright/test'
import { createThread, getAuthToken, registerUser } from './helpers'

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`Create cycle feedback opens the affected prerequisite editor at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    const suffix = `${Date.now()}${viewport.width}`
    await registerUser(page, { username: `cycle${suffix}`, email: `cycle${suffix}@example.com`, password: 'CycleTest123!' })
    const token = await getAuthToken(page)
    const csrfResponse = await page.request.get('/api/auth/csrf', { headers: { Authorization: `Bearer ${token}` } })
    expect(csrfResponse.ok()).toBeTruthy()
    // SAFETY: the auth endpoint supplies the CSRF token for these local fixture writes.
    const csrf = await csrfResponse.json() as { csrf_token: string }
    const headers = { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrf.csrf_token }
    const threadTitle = `X-Force ${suffix}`
    const thread = await createThread(page, { title: threadTitle, format: 'comic', total_issues: 2, issues_remaining: 2 })
    const issuesResponse = await page.request.get(`/api/v1/threads/${thread.id}/issues`, { headers })
    expect(issuesResponse.ok(), await issuesResponse.text()).toBeTruthy()
    // SAFETY: the real issue endpoint supplies the numeric IDs used in the error fixture.
    const issues = await issuesResponse.json() as { issues: Array<{ id: number }> }
    const first = issues.issues[0].id
    const second = issues.issues[1].id
    const planResponse = await page.request.post('/api/v1/continuity-plans/', { headers, data: {
      name: `Cycle feedback ${suffix}`, ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Main', order: 0 }],
      nodes: [{ id: 'first', node_type: 'issue', ref_id: first, lane_id: 'main', position: 0 }],
    } })
    expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
    // SAFETY: successful plan creation returns its numeric ID.
    const plan = await planResponse.json() as { id: number }

    // Legacy invalid graph state cannot be authored through the protected API.
    // Supply its documented 422 response only; all navigation/editor reads are real.
    await page.route('**/api/v1/custom-cbls', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: {
        code: 'reading_list_cycle', message: `Reading constraint cycle: Issue ${second} -> Issue ${first}`,
        path: [{ source_issue_id: second, target_issue_id: first,
          source_issue_name: `${threadTitle} #2`, target_issue_name: `${threadTitle} #1`,
          source_thread_id: thread.id, target_thread_id: thread.id,
          origin: 'prerequisite 123 (converted)', prerequisite_origin: 'converted', provenance: [],
        }],
      } }) })
    })
    await page.goto(`/continuity-plans/${plan.id}`)
    await page.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    const attemptedName = `My new list ${suffix}`
    await page.getByLabel('New custom CBL name').fill(attemptedName)
    await page.getByRole('button', { name: 'Create', exact: true }).click()
    const alert = page.getByRole('alert').filter({ hasText: 'An existing reading cycle' })
    await expect(alert).toContainText(`${threadTitle} #2 → ${threadTitle} #1`)
    await expect(alert).toContainText('No new list was saved')
    await expect(alert).not.toContainText(`Issue ${second}`)
    await expect(page.getByLabel('New custom CBL name')).toHaveValue(attemptedName)
    const lists = await page.request.get('/api/v1/custom-cbls', { headers })
    expect(await lists.json()).toEqual([])
    await page.screenshot({ path: testInfo.outputPath('named-create-cycle.png'), fullPage: true })
    await alert.getByRole('link', { name: `Review prerequisites for ${threadTitle} #1` }).click()
    await expect(page).toHaveURL(new RegExp(`/thread/${thread.id}\\?prerequisites=1`))
    const editor = page.getByRole('dialog', { name: `Dependencies: ${threadTitle}` })
    await expect(editor).toBeVisible()
    await editor.getByRole('button', { name: 'Close modal' }).click()
    await expect(editor).toBeHidden()
    await expect(page.getByRole('heading', { name: threadTitle, exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    const edit = page.getByRole('dialog', { name: 'Edit Series', exact: true })
    const refreshedNotes = `Controlled series refresh ${suffix}`
    await edit.getByLabel('Notes', { exact: true }).fill(refreshedNotes)
    await edit.getByRole('button', { name: 'Save Changes', exact: true }).click()
    await expect(edit).toBeHidden()
    await expect(page.getByText(refreshedNotes, { exact: true })).toBeVisible()
    // Let effects caused by the changed thread settle before asserting dismissal.
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    await expect(editor).toBeHidden()
  })
}
