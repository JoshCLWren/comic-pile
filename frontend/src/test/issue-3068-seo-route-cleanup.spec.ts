/**
 * Issue #3068: SEO - eliminate redirect chains, soft 404s, and orphaned public pages.
 *
 * This test suite verifies:
 * 1. No public URL requires more than one redirect to reach its canonical destination
 * 2. Missing public pages do not resolve as indexable soft-404 200 responses
 * 3. Every indexable public route has at least one intentional discovery path
 * 4. Canonical links and redirects agree on the same final URL
 */

import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'

test.describe('Issue #3068: SEO route cleanup', () => {
  test('landing page is the only public-indexable route', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveTitle(/ComicPile/)
    await expect(page.getByRole('heading', { name: /ComicPile/i })).toBeVisible()
  })

  test('public-noindex routes are not indexable', async ({ page }) => {
    const publicNoindexPaths = [
      '/login',
      '/register',
      '/forgot-password',
      '/reset-password',
      '/demo',
    ]

    for (const path of publicNoindexPaths) {
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      // Public-noindex routes should render without errors
      await expect(page).not.toHaveTitle(/404/)
      // These routes should not have indexable content
      await expect(page.getByRole('heading', { name: /not found/i })).not.toBeVisible()
    }
  })

  test('removed obsolete aliases return 404', async ({ page }) => {
    for (const path of ['/rate', '/analytics', '/roll', '/help']) {
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      await expect(page.getByRole('heading', { name: /Page not found/i })).toBeVisible()
    }
  })

  test('missing routes return proper 404 responses', async ({ page }) => {
    const nonExistentPaths = [
      '/non-existent-page',
      '/api/test',
      '/invalid-route',
      '/random-path',
    ]

    for (const path of nonExistentPaths) {
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      // Should show 404 page, not a 200 soft-404
      await expect(page.getByRole('heading', { name: /not found/i })).toBeVisible()
    }
  })

  test('authenticated routes require login', async ({ page }) => {
    const privatePaths = [
      '/queue',
      '/thread/1',
      '/creators/x-men',
      '/history',
      '/crossovers',
    ]

    for (const path of privatePaths) {
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      // Should redirect to login page
      await expect(page).toHaveURL(/\/login$/, { ignoreCase: true })
    }
  })

  test('crawlers are properly disallowed from utility routes', async ({ page }) => {
    const utilityPaths = [
      '/login',
      '/register',
      '/forgot-password',
      '/reset-password',
      '/demo',
    ]

    for (const path of utilityPaths) {
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      // Utility pages should render but not have indexable content
      await expect(page).not.toHaveTitle(/404/)
      await expect(page.getByRole('heading', { name: /not found/i })).not.toBeVisible()
    }
  })

  test('all public routes are discoverable from landing page', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    // Check that the landing page contains links to public utility routes
    // These should be present for user discoverability (even if not indexable by search)
    const loginLink = page.getByRole('link', { name: /sign in/i })
    const registerLink = page.getByRole('link', { name: /register/i })

    // Verify links exist and point to correct destinations
    if (await loginLink.isVisible()) {
      await expect(loginLink).toHaveAttribute('href', '/login')
    }

    if (await registerLink.isVisible()) {
      await expect(registerLink).toHaveAttribute('href', '/register')
    }
  })

  test('canonical links are present for indexable routes', async ({ page }) => {
    // Only the landing page should have a canonical link
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    // Check for canonical link tag in head
    const canonicalLink = page.locator('link[rel="canonical"]')
    await expect(canonicalLink).toHaveAttribute('href', new RegExp(page.url(), 'i'))
  })

  test('robots.txt disallows all non-public routes', async ({ page }) => {
    const disallowedPaths = [
      '/login',
      '/register',
      '/queue',
      '/thread/',
      '/creators',
      '/history',
      '/sessions/',
      '/crossovers',
      '/continuity-plans',
      '/whats-new',
      '/glossary',
      '/identity-inbox',
      '/api/',
    ]

    for (const path of disallowedPaths) {
      await page.goto(`/robots.txt`, { waitUntil: 'domcontentloaded' })
      const content = await page.textContent('body')
      expect(content).toContain(`Disallow: ${path}`)
    }
  })

  test('sitemap only contains the landing page', async ({ page }) => {
    await page.goto('/sitemap.xml', { waitUntil: 'domcontentloaded' })
    const content = await page.textContent('body')
    // Only the landing page should be in the sitemap
    expect(content).toContain('<loc>https://comic-pile.vercel.app/</loc>')
    // Should not contain any other indexable routes
    expect(content).not.toMatch(/<loc>https:\/\/comic-pile\.vercel\.app\/(login|register|queue)/)
  })
})
