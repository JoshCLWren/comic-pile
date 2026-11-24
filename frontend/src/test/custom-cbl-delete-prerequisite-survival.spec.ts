import { test, expect } from '@playwright/test'
import { createThread, getAuthToken, registerUser } from './helpers'

/**
 * MQA-LIST-004: explicit prerequisite survives canonical Reading List deletion.
 *
 * An explicit issue dependency (reader prerequisite) is stored independently of
 * custom_cbl_lists. Deleting a canonical Reading List must not remove it, must
 * not change read/rating history, and must not affect other lists.
 */
for (const viewport of [{ width: 1280, height: 900 }]) {
  test(`MQA-LIST-004 explicit prerequisite survives canonical Reading List deletion at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    const suffix = `${Date.now()}${viewport.width}`
    await registerUser(page, {
      username: `cblprereq${suffix}`,
      email: `cblprereq${suffix}@example.com`,
      password: 'CblPrereqTest123!',
    })
    const token = await getAuthToken(page)
    expect(token).toBeTruthy()

    const csrfResponse = await page.request.get('/api/v2/auth/csrf', {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(csrfResponse.ok()).toBeTruthy()
    // SAFETY: csrf endpoint returns { csrf_token: string } on success; checked by ok() above.
    const csrf = (await csrfResponse.json()) as { csrf_token: string }
    const headers = { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrf.csrf_token }

    // Two threads/issues so we can create an explicit issue dependency (prerequisite).
    const sourceThread = await createThread(page, {
      title: `Prereq Source ${suffix}`,
      format: 'comic',
      issues_remaining: 1,
      total_issues: 1,
    })
    const targetThread = await createThread(page, {
      title: `Prereq Target ${suffix}`,
      format: 'comic',
      issues_remaining: 1,
      total_issues: 1,
    })

    const sourceIssuesResp = await page.request.get(`/api/v1/threads/${sourceThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(sourceIssuesResp.ok()).toBeTruthy()
    // SAFETY: thread issues endpoint returns { issues: [{ id, ... }] }.
    const sourceIssues = (await sourceIssuesResp.json()) as { issues: Array<{ id: number }> }
    const targetIssuesResp = await page.request.get(`/api/v1/threads/${targetThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(targetIssuesResp.ok()).toBeTruthy()
    // SAFETY: thread issues endpoint returns { issues: [{ id, ... }] }.
    const targetIssues = (await targetIssuesResp.json()) as { issues: Array<{ id: number }> }
    const sourceIssueId = sourceIssues.issues[0].id
    const targetIssueId = targetIssues.issues[0].id

    // Explicit reader prerequisite: source issue depends on target issue.
    const depResp = await page.request.post('/api/v2/dependencies/', {
      headers,
      data: {
        source_type: 'issue',
        source_id: sourceIssueId,
        target_type: 'issue',
        target_id: targetIssueId,
      },
    })
    expect(depResp.ok(), await depResp.text()).toBeTruthy()
    // SAFETY: dependency create returns the created dependency with id.
    const dep = (await depResp.json()) as { id: number }
    expect(dep.id).toBeGreaterThan(0)

    // Create a canonical Reading List containing the dependent issue, then another list
    // that must be unaffected by deletion.
    const listResponse = await page.request.post('/api/v2/reading-lists', {
      headers,
      data: { name: `Prereq Survival List ${suffix}`, issue_ids: [sourceIssueId] },
    })
    expect(listResponse.ok(), await listResponse.text()).toBeTruthy()
    // SAFETY: reading-lists POST returns created list object with numeric id on success.
    const list = (await listResponse.json()) as { id: number }

    const otherListResponse = await page.request.post('/api/v2/reading-lists', {
      headers,
      data: { name: `Unaffected List ${suffix}`, issue_ids: [targetIssueId] },
    })
    expect(otherListResponse.ok(), await otherListResponse.text()).toBeTruthy()
    // SAFETY: reading-lists POST returns created list object with numeric id on success.
    const otherList = (await otherListResponse.json()) as { id: number }

    // Open canonical editor and delete via in-page confirmation.
    await page.goto(`/reading-lists/${list.id}`)
    await expect(page.getByLabel('Name')).toHaveValue(`Prereq Survival List ${suffix}`)

    const deleteButton = page.getByRole('button', { name: 'Delete', exact: true })
    await expect(deleteButton).toBeVisible()
    await deleteButton.click()
    const dialog = page.getByRole('dialog', { name: 'Delete custom CBL' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Delete custom CBL' }).click()
    await expect(page.getByRole('status')).toContainText('Custom CBL deleted.')

    // Deleted list is gone.
    const afterDelete = await page.request.get('/api/v2/reading-lists', { headers })
    // SAFETY: GET /api/v2/reading-lists returns an array of list objects with numeric id.
    const afterDeleteBody = (await afterDelete.json()) as Array<{ id: number }>
    expect(afterDeleteBody.some((item) => item.id === list.id)).toBe(false)

    // Other list is unchanged (no silent changes to other lists).
    expect(afterDeleteBody.some((item) => item.id === otherList.id)).toBe(true)
    const otherListResp = await page.request.get(`/api/v2/reading-lists/${otherList.id}`, { headers })
    expect(otherListResp.ok(), await otherListResp.text()).toBeTruthy()
    // SAFETY: reading-list GET returns object with issue_ids.
    const otherListBody = (await otherListResp.json()) as { issue_ids: number[] }
    expect(otherListBody.issue_ids).toContain(targetIssueId)

    // Explicit prerequisite survives list deletion.
    const depsResp = await page.request.get(`/api/v2/issues/${sourceIssueId}/dependencies`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(depsResp.ok(), await depsResp.text()).toBeTruthy()
    // SAFETY: outgoing edges encode the other issue in source_issue_* fields per IssueDependencyEdge contract.
    const depsBody = (await depsResp.json()) as {
      outgoing: Array<{ dependency_id: number; source_issue_id: number }>
    }
    expect(
      depsBody.outgoing.some((edge) => edge.dependency_id === dep.id && edge.source_issue_id === targetIssueId),
    ).toBe(true)

    await page.screenshot({
      path: testInfo.outputPath('cbl-delete-prerequisite-survival.png'),
      fullPage: true,
    })
  })
}
