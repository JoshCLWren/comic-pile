import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread } from './helpers'

for (const width of [390, 1280]) {
  test(`canonical boundaries keep JLI available and name Fourth World at ${width}px`, async ({ authenticatedPage: page }) => {
    await page.setViewportSize({ width, height: 900 })
    const jli = await createThread(page, { title: 'JLI', format: 'Issue', issues_remaining: 2, total_issues: 2 })
    const miracle = await createThread(page, { title: 'Mister Miracle', format: 'Issue', issues_remaining: 2, total_issues: 2 })
    const fourth = await createThread(page, { title: 'Fourth World', format: 'Issue', issues_remaining: 2, total_issues: 2 })
    const requested: number[][] = []
    await page.route('**/api/v2/reading-boundaries', async route => {
      // SAFETY: this intercept targets the batch client, which posts its typed thread_ids array.
      const body = route.request().postDataJSON() as { thread_ids: number[] }
      requested.push(body.thread_ids)
      await route.fulfill({ json: { threads: {
        [jli.id]: { thread_id: jli.id, state: 'available', summary: 'JLI is ready to read.', blockers: [] },
        [miracle.id]: { thread_id: miracle.id, state: 'blocked', summary: 'Mister Miracle is waiting on Fourth World.', blockers: [{ kind: 'prerequisite', origin: 'reader_prerequisite', reason: 'Read Fourth World #2 first', waiting_on: [{ issue_id: fourth.id, thread_id: fourth.id, thread_title: 'Fourth World', issue_number: '2', label: 'Fourth World #2', volume_label: 'Fourth World Omnibus' }], editor: { kind: 'prerequisite', thread_id: miracle.id, label: 'Mister Miracle prerequisites' } }] },
      } } })
    })
    await page.goto('/queue')
    const jliCard = page.getByTestId('queue-thread-item').filter({ has: page.getByRole('heading', { name: 'JLI', exact: true }) })
    const miracleCard = page.getByTestId('queue-thread-item').filter({ has: page.getByRole('heading', { name: 'Mister Miracle', exact: true }) })
    // Available Queue rows do not render a blocked-details panel in v2.
    await expect(jliCard.getByTestId('queue-thread-blocked-detail')).toHaveCount(0)
    await expect(jliCard.getByRole('list', { name: 'Active reading blockers' })).toHaveCount(0)
    await expect(miracleCard.getByText('Read Fourth World #2 first')).toBeVisible()
    await expect(miracleCard.getByRole('link', { name: 'Open Fourth World issue #2' })).toHaveAttribute('href', `/thread/${fourth.id}?issue=${fourth.id}#issue-${fourth.id}`)
    await expect(miracleCard.getByRole('link', { name: 'Edit Mister Miracle prerequisites' })).toHaveAttribute('href', `/thread/${miracle.id}?prerequisites=1`)
    expect(requested.some(ids => ids.includes(jli.id) && ids.includes(miracle.id))).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}
