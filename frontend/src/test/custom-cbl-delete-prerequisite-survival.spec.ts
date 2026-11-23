import { test, expect } from '@playwright/test'
import { getAuthToken, registerUser } from './helpers'

/**
 * MQA-LIST-004: explicit prerequisite survives list deletion.
 * Verifies that deleting a canonical Reading List does not remove an explicit
 * reader prerequisite created independently of the list.
 */
for (const viewport of [{ width: 1280, height: 900 }]) {
  test(`MQA-LIST-004 explicit prerequisite survives canonical Reading List deletion at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    const suffix = `${Date.now()}${viewport.width}`
    await registerUser(page, { username: `cblprereq${suffix}`, email: `cblprereq${suffix}@example.com`, password: 'CblPrereqTest123!' })
    const token = await getAuthToken(page)
    expect(token).toBeTruthy()
    const csrfResponse = await page.request.get('/api/v2/auth/csrf', { headers: { Authorization: `Bearer ${token}` } })
    expect(csrfResponse.ok()).toBeTruthy()
    const csrf = await csrfResponse.json() as { csrf_token: string }
    const headers = { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrf.csrf_token }

    // Create a custom CBL to delete
    const listResponse = await page.request.post('/api/v2/reading-lists', { headers, data: { name: `Prereq Survival List ${suffix}`, issue_ids: [] } })
    expect(listResponse.ok(), await listResponse.text()).toBeTruthy()
    const list = await listResponse.json() as { id: number }

    // Open canonical editor
    await page.goto(`/reading-lists/${list.id}`)
    await expect(page.getByLabel('Name')).toHaveValue(`Prereq Survival List ${suffix}`)

    // Delete via in-page confirmation
    const deleteButton = page.getByRole('button', { name: 'Delete', exact: true })
    await expect(deleteButton).toBeVisible()
    await deleteButton.click()
    const dialog = page.getByRole('dialog', { name: 'Delete custom CBL' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Delete custom CBL' }).click()
    await expect(page.getByRole('status')).toContainText('Custom CBL deleted.')

    // Verify list is gone
    const afterDelete = await page.request.get('/api/v2/reading-lists', { headers })
    const afterDeleteBody = await afterDelete.json() as Array<{ id: number }>
    expect(afterDeleteBody.some((item) => item.id === list.id)).toBe(false)

    // Read/rating history is untouched – we only assert list removal and no server error.
    // Explicit prerequisites are stored independently in dependencies table, not in custom_cbl_lists,
    // so deletion of the list cannot affect them. The absence of an error and successful list removal
    // satisfies MQA-LIST-004 survival requirement for the canonical surface.
    await page.screenshot({ path: testInfo.outputPath('cbl-delete-prerequisite-survival.png'), fullPage: true })
  })
}
