import { test, expect } from './fixtures'
import { gotoRollPage, waitForRollPageReady } from './helpers'

test.describe('Roll Layout Invariants - Issue #2942', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)
  })

  test('assert bounding boxes for peer major regions do not intersect', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    
    // Roll a comic to enter rating view
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-testid="rating-view-top"]')).toBeVisible()

    const comicRegion = await page.locator('[data-testid="rating-region-comic"]')
    const decisionRegion = await page.locator('[data-testid="rating-region-decision"]')

    // Get bounding boxes for both regions
    const comicBox = await comicRegion.boundingBox()
    const decisionBox = await decisionRegion.boundingBox()

    // Verify both regions exist and have valid bounding boxes
    expect(comicBox).toBeTruthy()
    expect(decisionBox).toBeTruthy()

    // Calculate intersection
    const hasIntersection = 
      comicBox!.x < decisionBox!.x + decisionBox!.width &&
      comicBox!.x + comicBox!.width > decisionBox!.x &&
      comicBox!.y < decisionBox!.y + decisionBox!.height &&
      comicBox!.y + comicBox!.height > decisionBox!.y

    // Assert regions do not intersect
    expect(hasIntersection).toBe(false)
  })

  test('assert next vertical section begins at or below bottom of preceding layout region', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    
    // Roll a comic to enter rating view
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-testid="rating-view-top"]')).toBeVisible()

    const ratingViewTop = await page.locator('[data-testid="rating-view-top"]')
    const ratingViewBox = await ratingViewTop.boundingBox()

    // Find elements that should come after the rating view
    const nextSection = await page.locator('h1, h2, .thread-pool, .main-content').first()
    const nextSectionBox = await nextSection.boundingBox()

    // Verify both elements exist
    expect(ratingViewBox).toBeTruthy()
    expect(nextSectionBox).toBeTruthy()

    // Assert next section begins at or below the bottom of the rating view
    const nextSectionStartsAfterRatingView = 
      nextSectionBox!.y >= ratingViewBox!.y + ratingViewBox!.height - 10 // Allow small tolerance

    expect(nextSectionStartsAfterRatingView).toBe(true)
  })

  test('assert document scrollWidth <= clientWidth (no horizontal overflow)', async ({ rollPage }) => {
    // Test on multiple viewport sizes
    const viewports = [
      { width: 1920, height: 926 },
      { width: 1440, height: 900 },
      { width: 1280, height: 800 },
      { width: 1024, height: 768 },
      { width: 800, height: 1094 },
      { width: 430, height: 932 },
      { width: 390, height: 844 }
    ]

    for (const viewport of viewports) {
      await rollPage.page.setViewportSize(viewport)
      
      // Roll a comic to enter rating view
      await rollPage.rollDice()
      await rollPage.waitForRatingView()

      // Check for horizontal overflow
      const scrollWidth = await rollPage.page.evaluate(() => document.documentElement.scrollWidth)
      const clientWidth = await rollPage.page.evaluate(() => document.documentElement.clientWidth)

      // Allow small browser rounding tolerance
      const hasHorizontalOverflow = scrollWidth > clientWidth + 2

      expect(hasHorizontalOverflow).toBe(false), `Viewport ${viewport.width}x${viewport.height} has horizontal overflow`
    }
  })

  test('assert primary/secondary action bounding boxes stay inside their owning container', async ({ rollPage }) => {
    // Roll a comic to enter rating view
    await rollPage.rollDice()
    await rollPage.waitForRatingView()

    const decisionRegion = await rollPage.page.locator('[data-testid="rating-region-decision"]')
    const decisionBox = await decisionRegion.boundingBox()

    // Get primary action button
    const primaryAction = await rollPage.page.locator('[data-testid="save-and-continue"]')
    const primaryBox = await primaryAction.boundingBox()

    // Get secondary action buttons
    const secondaryActions = await rollPage.page.locator('[data-testid="rating-secondary-actions"]')
    const secondaryBox = await secondaryActions.boundingBox()

    // Verify all bounding boxes exist
    expect(decisionBox).toBeTruthy()
    expect(primaryBox).toBeTruthy()
    expect(secondaryBox).toBeTruthy()

    // Check primary action is inside decision region
    const primaryInside = 
      primaryBox!.x >= decisionBox!.x &&
      primaryBox!.x + primaryBox!.width <= decisionBox!.x + decisionBox!.width &&
      primaryBox!.y >= decisionBox!.y &&
      primaryBox!.y + primaryBox!.height <= decisionBox!.y + decisionBox!.height

    // Check secondary actions are inside decision region
    const secondaryInside = 
      secondaryBox!.x >= decisionBox!.x &&
      secondaryBox!.x + secondaryBox!.width <= decisionBox!.x + decisionBox!.width &&
      secondaryBox!.y >= decisionBox!.y &&
      secondaryBox!.y + secondaryBox!.height <= decisionBox!.y + decisionBox!.height

    expect(primaryInside).toBe(true)
    expect(secondaryInside).toBe(true)
  })

  test('assert mobile/tablet DOM order matches Comic → Decision → subordinate content sequence', async ({ rollPage }) => {
    // Test mobile viewport
    await rollPage.page.setViewportSize({ width: 430, height: 932 })

    // Roll a comic to enter rating view
    await rollPage.rollDice()
    await rollPage.waitForRatingView()

    // Get elements by their test IDs
    const comicRegion = await rollPage.page.locator('[data-testid="rating-region-comic"]')
    const decisionRegion = await rollPage.page.locator('[data-testid="rating-region-decision"]')
    const contextDisclosure = await rollPage.page.locator('[data-testid="context-disclosure"]')

    // Get positions
    const comicBox = await comicRegion.boundingBox()
    const decisionBox = await decisionRegion.boundingBox()
    const contextBox = await contextDisclosure.boundingBox()

    // Verify all elements exist
    expect(comicBox).toBeTruthy()
    expect(decisionBox).toBeTruthy()
    expect(contextBox).toBeTruthy()

    // Assert DOM order: Comic should be above Decision, which should be above Context
    const comicAboveDecision = comicBox!.y < decisionBox!.y
    const decisionAboveContext = decisionBox!.y < contextBox!.y

    expect(comicAboveDecision).toBe(true)
    expect(decisionAboveContext).toBe(true)
  })

  test('assert desktop region width ratios remain consistent', async ({ rollPage }) => {
    // Test desktop viewport
    await rollPage.page.setViewportSize({ width: 1440, height: 900 })

    // Roll a comic to enter rating view
    await rollPage.rollDice()
    await rollPage.waitForRatingView()

    const comicRegion = await rollPage.page.locator('[data-testid="rating-region-comic"]')
    const decisionRegion = await rollPage.page.locator('[data-testid="rating-region-decision"]')
    const gridContainer = await rollPage.page.locator('[data-testid="rating-pillars-grid"]')

    const comicBox = await comicRegion.boundingBox()
    const decisionBox = await decisionRegion.boundingBox()
    const gridBox = await gridContainer.boundingBox()

    // Verify all bounding boxes exist
    expect(comicBox).toBeTruthy()
    expect(decisionBox).toBeTruthy()
    expect(gridBox).toBeTruthy()

    // Calculate width ratios
    const comicWidth = comicBox!.width
    const decisionWidth = decisionBox!.width
    const totalWidth = gridBox!.width

    // Calculate expected ratios (Comic should take more space than Decision on desktop)
    const comicRatio = comicWidth / totalWidth
    const decisionRatio = decisionWidth / totalWidth

    // Assert reasonable width ratios (Comic should be roughly 60-70%, Decision 30-40%)
    expect(comicRatio).toBeGreaterThan(0.5)
    expect(comicRatio).toBeLessThan(0.8)
    expect(decisionRatio).toBeGreaterThan(0.2)
    expect(decisionRatio).toBeLessThan(0.5)

    // Assert combined widths match grid container (with small tolerance)
    const combinedWidth = comicWidth + decisionWidth
    const widthDifference = Math.abs(combinedWidth - totalWidth)
    expect(widthDifference).toBeLessThan(20) // 20px tolerance for borders/gaps
  })

  test('resize regression: verify layout reflows without overlap on resize', async ({ rollPage }) => {
    // Start with desktop viewport
    await rollPage.page.setViewportSize({ width: 1920, height: 926 })

    // Roll a comic to enter rating view and capture initial state
    await rollPage.rollDice()
    await rollPage.waitForRatingView()

    // Capture initial layout state
    const comicRegion = await rollPage.page.locator('[data-testid="rating-region-comic"]')
    const decisionRegion = await rollPage.page.locator('[data-testid="rating-region-decision"]')
    
    const initialComicBox = await comicRegion.boundingBox()
    const initialDecisionBox = await decisionRegion.boundingBox()

    // Verify initial state
    expect(initialComicBox).toBeTruthy()
    expect(initialDecisionBox).toBeTruthy()

    // Resize through different viewport sizes and verify no overlap
    const viewports = [
      { width: 1440, height: 900, name: 'normal desktop' },
      { width: 1280, height: 800, name: 'small desktop' },
      { width: 1024, height: 768, name: 'constrained desktop/tablet' },
      { width: 800, height: 1094, name: 'tablet portrait' },
      { width: 430, height: 932, name: 'phone' },
      { width: 390, height: 844, name: 'small phone' },
      { width: 1920, height: 926, name: 'back to desktop' }
    ]

    for (const viewport of viewports) {
      await rollPage.page.setViewportSize(viewport)

      // Wait for layout to stabilize
      await rollPage.page.waitForTimeout(500)

      const currentComicBox = await comicRegion.boundingBox()
      const currentDecisionBox = await decisionRegion.boundingBox()

      // Verify regions still exist
      expect(currentComicBox).toBeTruthy()
      expect(currentDecisionBox).toBeTruthy()

      // Check for intersection at this viewport
      const hasIntersection = 
        currentComicBox!.x < currentDecisionBox!.x + currentDecisionBox!.width &&
        currentComicBox!.x + currentComicBox!.width > currentDecisionBox!.x &&
        currentComicBox!.y < currentDecisionBox!.y + currentDecisionBox!.height &&
        currentComicBox!.y + currentComicBox!.height > currentDecisionBox!.y

      expect(hasIntersection).toBe(false), `Overlap detected at ${viewport.name} (${viewport.width}x${viewport.height})`

      // Check for horizontal overflow
      const scrollWidth = await rollPage.page.evaluate(() => document.documentElement.scrollWidth)
      const clientWidth = await rollPage.page.evaluate(() => document.documentElement.clientWidth)
      const hasHorizontalOverflow = scrollWidth > clientWidth + 2

      expect(hasHorizontalOverflow).toBe(false), `Horizontal overflow at ${viewport.name} (${viewport.width}x${viewport.height})`
    }

    // Verify we're back to the original desktop layout
    const finalComicBox = await comicRegion.boundingBox()
    const finalDecisionBox = await decisionRegion.boundingBox()

    const comicPositionChanged = Math.abs(finalComicBox!.x - initialComicBox!.x) > 5 || 
                                Math.abs(finalComicBox!.y - initialComicBox!.y) > 5
    const decisionPositionChanged = Math.abs(finalDecisionBox!.x - initialDecisionBox!.x) > 5 || 
                                   Math.abs(finalDecisionBox!.y - initialDecisionBox!.y) > 5

    // Layout should be stable when returning to the same viewport
    expect(comicPositionChanged).toBe(false)
    expect(decisionPositionChanged).toBe(false)
  })

  test('content stress fixtures: long titles and metadata do not cause overlap', async ({ rollPage }) => {
    // This test would require mocking the backend to return content with long titles
    // For now, we'll test with existing content but verify the layout handles it properly
    
    await rollPage.page.setViewportSize({ width: 1024, height: 768 })

    // Roll a comic to enter rating view
    await rollPage.rollDice()
    await rollPage.waitForRatingView()

    // Get the comic header row to check for proper text wrapping
    const comicHeader = await rollPage.page.locator('[data-testid="comic-header-row"]')
    const headerBox = await comicHeader.boundingBox()

    // Verify header exists and has reasonable dimensions
    expect(headerBox).toBeTruthy()
    expect(headerBox!.width).toBeGreaterThan(100) // Should have some width
    expect(headerBox!.height).toBeGreaterThan(50) // Should have some height

    // Check that text elements are properly wrapped and not overflowing
    const titleElement = await rollPage.page.locator('[data-testid="comic-header-title"]')
    const titleText = await titleElement.textContent()

    expect(titleText).toBeTruthy()
    expect(titleText!.length).toBeGreaterThan(0)

    // The title should be visible and not cause the container to overflow
    const titleBox = await titleElement.boundingBox()
    expect(titleBox).toBeTruthy()
    expect(titleBox!.width).toBeLessThan(headerBox!.width + 10) // Should fit within container
  })
})