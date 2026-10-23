import { test, expect } from './fixtures'
import { createThread, getAuthToken } from './helpers'

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`source names and provenance stay readable at ${viewport.width}px`, async ({ authenticatedPage: page }, testInfo) => {
    await page.setViewportSize(viewport)
    const token = await getAuthToken(page)
    expect(token).toBeTruthy()
    const csrfResponse = await page.request.get('/api/auth/csrf', {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(csrfResponse.ok()).toBeTruthy()
    // SAFETY: this fixture only reads the CSRF token returned by the auth endpoint.
    const csrf = await csrfResponse.json() as { csrf_token: string }
    const headers = { Authorization: `Bearer ${token}`, 'X-CSRF-Token': csrf.csrf_token }
    const suffix = `${Date.now()}-${testInfo.workerIndex}`
    const title = `Alpha Flight label ${suffix}`
    const path = `Marvel/Teams/Alpha Flight/${title}.cbl`
    const hostPath = `/mnt/bigdata/CBL-ReadingLists/${path}`
    const thread = await createThread(page, { title: `Alpha Flight ${suffix}`, format: 'comic', issues_remaining: 1, total_issues: 1 })
    const issueResponse = await page.request.get(`/api/v1/threads/${thread.id}/issues`, { headers })
    expect(issueResponse.ok(), await issueResponse.text()).toBeTruthy()
    // SAFETY: the issue endpoint returns numeric issue IDs, the only fields used here.
    const issueData = await issueResponse.json() as { issues: Array<{ id: number }> }
    const issueId = issueData.issues[0].id
    const sourceThread = await createThread(page, { title: `Alpha Flight source ${suffix}`, format: 'comic', issues_remaining: 1, total_issues: 1 })
    const sourceIssues = await page.request.get(`/api/v1/threads/${sourceThread.id}/issues`, { headers })
    expect(sourceIssues.ok(), await sourceIssues.text()).toBeTruthy()
    // SAFETY: this fixture reads only the numeric ID returned by the issue endpoint.
    const sourceIssueData = await sourceIssues.json() as { issues: Array<{ id: number }> }
    const sourceIssueId = sourceIssueData.issues[0].id
    const listResponse = await page.request.post('/api/v1/custom-cbls', {
      headers, data: { name: `Mignolaverse ${suffix}`, mode: 'loose', issue_ids: [issueId] },
    })
    expect(listResponse.ok(), await listResponse.text()).toBeTruthy()
    // SAFETY: a successful Reading List creation returns its numeric ID.
    const list = await listResponse.json() as { id: number }
    const sourceReference = `custom-cbl:${list.id}`
    const planResponse = await page.request.post('/api/v1/continuity-plans/', {
      headers,
      data: {
        name: title, ordering_mode: 'informational',
        lanes: [{ id: 'main', name: 'Main', order: 0 }],
        nodes: [
          { id: 'custom-source', node_type: 'issue', ref_id: issueId, lane_id: 'main', position: 0, source_paths: [sourceReference] },
          { id: 'alpha-flight', node_type: 'issue', ref_id: sourceIssueId, lane_id: 'main', position: 1, source_paths: [hostPath] },
        ],
      },
    })
    expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
    // SAFETY: a successful Reading Plan creation returns its numeric ID.
    const plan = await planResponse.json() as { id: number }
    const seeded = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: `[Marvel] ${title}`, source_path: hostPath,
        repository: `/mnt/bigdata/CBL-ReadingLists/${suffix}`, revision_sha: '1234567890abcdef',
        entries: [{ position: 1, series_name: 'Alpha Flight', issue_number: '1', issue_id: sourceIssueId }],
      },
    })
    expect(seeded.ok(), await seeded.text()).toBeTruthy()

    await page.goto('/continuity-plans', { waitUntil: 'domcontentloaded' })
    const card = page.getByTestId(`plan-card-${plan.id}`)
    await expect(card.getByText(`Source reading order: Mignolaverse ${suffix}`)).toBeVisible()
    await expect(card.getByText(path, { exact: true })).toBeHidden()
    await card.getByText('Source details', { exact: true }).click()
    await expect(card.getByText(path, { exact: true })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('/mnt/bigdata')
    await expect(page.locator('body')).not.toContainText(sourceReference)

    await card.getByRole('button', { name: new RegExp(title) }).click()
    await expect(page.getByTestId('reading-plan-reader')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Available now', exact: true }).getByText(`Source reading order: Mignolaverse ${suffix}`, { exact: true })).toBeVisible()
    const provenance = page.getByRole('region', { name: 'Source reading order', exact: true })
    await expect(provenance.getByText(`Mignolaverse ${suffix}`, { exact: true })).toBeVisible()
    await expect(provenance.getByText(path, { exact: true })).toBeHidden()
    await provenance.getByText('Source details', { exact: true }).click()
    await expect(provenance.getByText(path, { exact: true })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('/mnt/bigdata')
    await expect(page.locator('body')).not.toContainText(sourceReference)

    await page.getByRole('button', { name: 'Add from CBL', exact: true }).click()
    const source = page.getByRole('group', { name: `Source ${title}`, exact: true })
    await expect(source.getByRole('button', { name: new RegExp(title) })).toBeVisible()
    await expect(source.getByText(path, { exact: true })).toBeHidden()
    await source.getByText('Source details', { exact: true }).click()
    await expect(source.getByText(path, { exact: true })).toBeVisible()
    await expect(source.getByText('JoshCLWren/CBL-ReadingLists', { exact: true })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('/mnt/bigdata')
    await expect(page.locator('body')).not.toContainText(sourceReference)
    await source.getByRole('button', { name: new RegExp(title) }).click()
    const preview = page.locator('section[aria-labelledby="source-preview-heading"]')
    await expect(preview.getByRole('heading', { name: title, exact: true })).toBeVisible()
    await expect(preview.getByText('Revision 12345678', { exact: true })).toBeHidden()
    await preview.getByText('Source details', { exact: true }).click()
    await expect(preview.getByText('Revision 12345678', { exact: true })).toBeVisible()
    await expect(preview.getByText(path, { exact: true })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('/mnt/bigdata')
    await expect(page.locator('body')).not.toContainText(sourceReference)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const screenshotPath = testInfo.outputPath('readable-source-provenance.png')
    await page.screenshot({ path: screenshotPath, fullPage: true })
    await testInfo.attach('readable-source-provenance', { path: screenshotPath, contentType: 'image/png' })
  })
}
