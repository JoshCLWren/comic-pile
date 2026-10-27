import { test, expect } from '@playwright/test'
import { getAuthToken, registerUser } from './helpers'

/**
 * Issue #4193: the custom CBL delete previously confirmed through a native
 * `window.confirm`, which QA automation cannot accept — the harness
 * auto-dismisses it, so every automated delete attempt looked like a dead
 * button. The confirmation is now an in-page dialog this lane can fully
 * exercise, including the MQA-LIST-004 "explicit prerequisite survives list
 * deletion" sub-step that needs a deletable list.
 */
for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`Custom CBL delete is exercisable through an in-page confirmation dialog at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    const suffix = `${Date.now()}${viewport.width}`
    await registerUser(page, { username: `cbldelete${suffix}`, email: `cbldelete${suffix}@example.com`, password: 'CblDeleteTest123!' })
    const token = await getAuthToken(page)
    expect(token).toBeTruthy()
    const csrfResponse = await page.request.get('/api/auth/csrf', { headers: { Authorization: `Bearer ${token}` } })
    expect(csrfResponse.ok()).toBeTruthy()
    // SAFETY: the auth endpoint supplies the CSRF token for these local fixture writes.
    const csrf = await csrfResponse.json() as { csrf_token: string }
    const headers = { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrf.csrf_token }

    const listResponse = await page.request.post('/api/v1/custom-cbls', { headers, data: {
      name: `QA List Test 004P ${suffix}`,
      issue_ids: [],
    } })
    expect(listResponse.ok(), await listResponse.text()).toBeTruthy()
    // SAFETY: successful list creation returns its numeric ID.
    const list = await listResponse.json() as { id: number }

    await page.goto(`/reading-lists/${list.id}`)
    await expect(page.getByLabel('Name')).toHaveValue(`QA List Test 004P ${suffix}`)

    // Delete confirms in-page, so automation can see and operate the dialog;
    // a native confirm would be auto-dismissed before any click could land.
    const deleteButton = page.getByRole('button', { name: 'Delete', exact: true })
    await expect(deleteButton).toBeVisible()
    await deleteButton.click()
    const dialog = page.getByRole('dialog', { name: 'Delete custom CBL' })
    await expect(dialog).toBeVisible()

    // Cancel keeps the saved list exactly as it is.
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()
    const afterCancel = await page.request.get('/api/v1/custom-cbls', { headers })
    // SAFETY: the list endpoint returns a JSON array of custom CBLs with numeric ids.
    const afterCancelBody = await afterCancel.json() as Array<{ id: number }>
    expect(afterCancelBody.some((item) => item.id === list.id)).toBe(true)

    // Confirm actually deletes the list on the backend.
    await deleteButton.click()
    await page.getByRole('dialog', { name: 'Delete custom CBL' })
      .getByRole('button', { name: 'Delete custom CBL' })
      .click()
    await expect(page.getByRole('status')).toContainText('Custom CBL deleted.')
    const afterDelete = await page.request.get('/api/v1/custom-cbls', { headers })
    // SAFETY: the list endpoint returns a JSON array of custom CBLs with numeric ids.
    const afterDeleteBody = await afterDelete.json() as Array<{ id: number }>
    expect(afterDeleteBody.some((item) => item.id === list.id)).toBe(false)
    const reload = await page.request.get(`/api/v1/custom-cbls/${list.id}`, { headers })
    expect([404, 410]).toContain(reload.status())
    await page.screenshot({ path: testInfo.outputPath('custom-cbl-delete-confirm.png'), fullPage: true })
  })
}
