import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoQueue } from './helpers'

test.describe('PROBE #3147 v5', () => {
  test('transient DOM content', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    for (const title of ['T1', 'T2']) {
      await createThread(page, { title, format: 'Issue', issues_remaining: 3, total_issues: 3 })
    }
    await gotoQueue(page)
    await expect(page.getByLabel('Series actions')).toHaveCount(2)
    await page.getByLabel('Series actions').first().focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('menu')).toBeVisible()
    await page.waitForTimeout(300)
    await page.keyboard.press('ArrowDown')
    await page.waitForTimeout(200)

    const captured = await page.evaluate(async () => {
      const btn = document.querySelector('[aria-label="Move to front"]') as HTMLButtonElement
      const samples: string[] = []
      btn.click()
      for (let i = 0; i < 12; i++) {
        await new Promise((r) => requestAnimationFrame(r))
        const root = document.getElementById('root')!
        const listMissing = !document.querySelector('[data-testid="queue-thread-list"]')
        if (listMissing) {
          const all = root.innerHTML.replace(/\s+/g, ' ')
          samples.push('LEN=' + all.length + ' TAIL>>>' + all.slice(-900))
        }
      }
      return samples
    })
    for (const s of captured) console.log('TRANSIENT>>>', s)
    console.log('transient samples:', captured.length)
  })
})