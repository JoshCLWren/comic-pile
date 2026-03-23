import { test, expect } from './fixtures'

test.describe('Collection Toolbar', () => {
  test('should display collection toolbar on Roll page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/')
    await authenticatedPage.waitForLoadState('networkidle')

    const toolbar = authenticatedPage.locator('.collection-toolbar').first()
    await expect(toolbar).toBeVisible()

    const selector = authenticatedPage.getByLabel('Filter by collection')
    await expect(selector).toBeVisible()

    const newButton = authenticatedPage.getByRole('button', { name: /new collection/i })
    await expect(newButton).toBeVisible()
  })

  test('should display collection toolbar on Queue page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const toolbar = authenticatedPage.locator('.collection-toolbar').first()
    await expect(toolbar).toBeVisible()

    const selector = authenticatedPage.getByLabel('Filter by collection')
    await expect(selector).toBeVisible()

    const newButton = authenticatedPage.getByRole('button', { name: /new collection/i })
    await expect(newButton).toBeVisible()
  })

  test('should allow switching collections from toolbar on Roll page', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)
    if (!token) throw new Error('No auth token found')

    const collectionName = `Toolbar Test Collection ${Date.now()}`
    const response = await request.post('/api/v1/collections/', {
      data: { name: collectionName },
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok()) {
      throw new Error(`Failed to create collection: ${response.status()}`)
    }

    const collection = await response.json()
    const collectionId = collection.id

    await authenticatedPage.goto('/')
    await authenticatedPage.waitForLoadState('networkidle')

    const selector = authenticatedPage.getByLabel('Filter by collection')
    await selector.selectOption(String(collectionId))
    await expect(selector).toHaveValue(String(collectionId))

    await selector.selectOption('all')
    await expect(selector).toHaveValue('all')
  })

  test('should allow switching collections from toolbar on Queue page', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN)
    if (!token) throw new Error('No auth token found')

    const collectionName = `Queue Toolbar Test ${Date.now()}`
    const response = await request.post('/api/v1/collections/', {
      data: { name: collectionName },
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok()) {
      throw new Error(`Failed to create collection: ${response.status()}`)
    }

    const collection = await response.json()
    const collectionId = collection.id

    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const selector = authenticatedPage.getByLabel('Filter by collection')
    await selector.selectOption(String(collectionId))
    await expect(selector).toHaveValue(String(collectionId))

    await selector.selectOption('all')
    await expect(selector).toHaveValue('all')
  })

  test('should open collection dialog from toolbar on Roll page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/')
    await authenticatedPage.waitForLoadState('networkidle')

    const newButton = authenticatedPage.getByRole('button', { name: /new collection/i })
    await newButton.click()

    const dialog = authenticatedPage.locator('[role="dialog"]')
    await expect(dialog).toBeVisible({ timeout: 5000 })
  })

  test('should open collection dialog from toolbar on Queue page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue')
    await authenticatedPage.waitForLoadState('networkidle')

    const newButton = authenticatedPage.getByRole('button', { name: /new collection/i })
    await newButton.click()

    const dialog = authenticatedPage.locator('[role="dialog"]')
    await expect(dialog).toBeVisible({ timeout: 5000 })
  })
})
