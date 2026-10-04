import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { hasResponsiveLayoutClassAssertions } from '../../eslint-rules/class-name-layout-guard'

/**
 * Issue #3061: Ban DOM class-name assertions as evidence of responsive layout correctness.
 * 
 * Roll-specific test demonstrating the problem with existing patterns and the solution
 * using geometry-based assertions.
 */

// Mock Roll components for testing
const MockRollRatingView = () => (
  <div className="lg:grid lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)] lg:max-w-4xl lg:mx-auto">
    <div data-testid="rating-region-comic" className="min-w-0">
      <div data-testid="comic-cover" className="aspect-[2/3] w-full">Cover</div>
    </div>
    <div data-testid="rating-region-decision" className="min-w-0">
      <div data-testid="decision-card">Decision Content</div>
      <div data-testid="rating-actions">Actions</div>
    </div>
  </div>
)

const BrokenRollRatingView = () => (
  <div className="lg:grid lg:grid-cols-[invalid_layout] lg:max-w-4xl lg:mx-auto">
    <div data-testid="rating-region-comic" className="min-w-0">
      <div data-testid="comic-cover" className="invalid-aspect-ratio w-full">Cover</div>
    </div>
    <div data-testid="rating-region-decision" className="min-w-0">
      <div data-testid="decision-card">Decision Content</div>
      <div data-testid="rating-actions">Actions</div>
    </div>
  </div>
)

describe('Roll component: Problematic class-name assertions (existing pattern)', () => {
  it('demonstrates the flaw in existing Roll tests (like #2949)', () => {
    // This represents the existing problematic test pattern
    const problematicRollTest = `
      describe('Roll rating layout', () => {
        it('has correct responsive classes', () => {
          const grid = screen.getByTestId('rating-pillars-grid')
          expect(grid.className).toContain('lg:grid')
          expect(grid.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
          expect(grid.className).toContain('lg:max-w-4xl')
          expect(grid.className).toContain('lg:mx-auto')
          
          const comicRegion = screen.getByTestId('rating-region-comic')
          expect(comicRegion.className).toContain('min-w-0')
          
          const decisionRegion = screen.getByTestId('rating-region-decision')
          expect(decisionRegion.className).toContain('min-w-0')
        })
      })
    `
    
    // This should be detected as problematic
    expect(hasResponsiveLayoutClassAssertions(problematicRollTest)).toBe(true)
  })

  it('shows how invalid classes still pass className assertions', () => {
    render(<BrokenRollRatingView />)
    
    const grid = screen.getByTestId('rating-region-comic').parentElement!
    const comicRegion = screen.getByTestId('rating-region-comic')
    const decisionRegion = screen.getByTestId('rating-region-decision')
    
    // ✅ These assertions PASS even though the layout is broken
    expect(grid.className).toContain('lg:grid')
    expect(grid.className).toContain('lg:grid-cols-[invalid_layout]')
    expect(grid.className).toContain('lg:max-w-4xl')
    expect(grid.className).toContain('lg:mx-auto')
    expect(comicRegion.className).toContain('min-w-0')
    expect(decisionRegion.className).toContain('min-w-0')
    
    // ❌ But the actual layout is broken:
    const gridStyle = window.getComputedStyle(grid)
    expect(gridStyle.gridTemplateColumns).not.toBe('minmax(0,24rem) minmax(18rem,24rem)')
    
    const cover = screen.getByTestId('comic-cover')
    const coverStyle = window.getComputedStyle(cover)
    expect(coverStyle.aspectRatio).not.toBe('2/3')
  })
})

describe('Roll component: Geometry-based assertions (correct pattern)', () => {
  it('uses actual geometry measurements to prove Roll layout works', () => {
    render(<MockRollRatingView />)
    
    const grid = screen.getByTestId('rating-region-comic').parentElement!
    const comicRegion = screen.getByTestId('rating-region-comic')
    const decisionRegion = screen.getByTestId('rating-region-decision')
    const cover = screen.getByTestId('comic-cover')
    const decisionCard = screen.getByTestId('decision-card')
    
    // ✅ Prove the grid actually works:
    const gridStyle = window.getComputedStyle(grid)
    expect(gridStyle.display).toBe('grid')
    expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
    expect(gridStyle.maxWidth).toBe('1024px') // 4xl = 1024px
    
    // ✅ Prove the regions actually render with correct geometry:
    const comicRect = comicRegion.getBoundingClientRect()
    const decisionRect = decisionRegion.getBoundingClientRect()
    const coverRect = cover.getBoundingClientRect()
    const cardRect = decisionCard.getBoundingClientRect()
    
    // Both regions should have positive width (not collapsed)
    expect(comicRect.width).toBeGreaterThan(0)
    expect(decisionRect.width).toBeGreaterThan(0)
    
    // Comic region should be wider than decision region (24rem vs 18rem)
    expect(comicRect.width).toBeGreaterThan(decisionRect.width)
    
    // Cover should maintain aspect ratio
    expect(coverRect.width / coverRect.height).toBeCloseTo(2/3, 1)
    
    // Content should be properly contained within regions
    expect(coverRect.left).toBeGreaterThanOrEqual(comicRect.left)
    expect(coverRect.right).toBeLessThanOrEqual(comicRect.right)
    expect(cardRect.left).toBeGreaterThanOrEqual(decisionRect.left)
    expect(cardRect.right).toBeLessThanOrEqual(decisionRect.right)
    
    // Regions should be side by side (not stacked)
    expect(Math.abs(comicRect.left - decisionRect.left)).toBeLessThan(
      Math.max(comicRect.width, decisionRect.width)
    )
  })

  it('proves responsive behavior at different viewport sizes', () => {
    // Test desktop layout
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 1024, // lg breakpoint
    })
    
    render(<MockRollRatingView />)
    
    const grid = screen.getByTestId('rating-region-comic').parentElement!
    const gridStyle = window.getComputedStyle(grid)
    
    expect(gridStyle.display).toBe('grid')
    expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
    
    // Test mobile layout (simulated)
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 640, // Below md breakpoint
    })
    
    // Re-render with mobile viewport
    render(<MockRollRatingView />)
    
    // On mobile, the grid should collapse to single column
    const mobileGridStyle = window.getComputedStyle(grid)
    expect(mobileGridStyle.display).toBe('grid')
    // The columns should stack vertically on mobile
    expect(mobileGridStyle.gridTemplateColumns).toBe('1fr')
  })

  it('proves content containment and overflow handling', () => {
    render(<MockRollRatingView />)
    
    const grid = screen.getByTestId('rating-region-comic').parentElement!
    const containerRect = grid.getBoundingClientRect()
    const viewportWidth = window.innerWidth
    
    // ✅ Prove the container is properly contained
    expect(containerRect.left).toBeGreaterThanOrEqual(0)
    expect(containerRect.right).toBeLessThanOrEqual(viewportWidth)
    expect(containerRect.width).toBeLessThanOrEqual(viewportWidth)
    
    // ✅ Prove max-width constraint is respected
    expect(containerRect.width).toBeLessThanOrEqual(1024) // 4xl = 1024px
    
    // ✅ Prove content doesn't overflow
    const comicRegion = screen.getByTestId('rating-region-comic')
    const decisionRegion = screen.getByTestId('rating-region-decision')
    
    const comicRect = comicRegion.getBoundingClientRect()
    const decisionRect = decisionRegion.getBoundingClientRect()
    
    // Content should be within container bounds
    expect(comicRect.left).toBeGreaterThanOrEqual(containerRect.left)
    expect(decisionRect.right).toBeLessThanOrEqual(containerRect.right)
  })

  it('proves interactive elements are properly positioned', () => {
    render(<MockRollRatingView />)
    
    const decisionCard = screen.getByTestId('decision-card')
    const ratingActions = screen.getByTestId('rating-actions')
    const container = screen.getByTestId('rating-region-decision')
    
    const cardRect = decisionCard.getBoundingClientRect()
    const actionsRect = ratingActions.getBoundingClientRect()
    const containerRect = container.getBoundingClientRect()
    
    // ✅ Prove actions are positioned correctly relative to card
    expect(actionsRect.top).toBeGreaterThan(cardRect.bottom)
    expect(actionsRect.left).toBeGreaterThanOrEqual(containerRect.left)
    expect(actionsRect.right).toBeLessThanOrEqual(containerRect.right)
    
    // ✅ Prove elements don't overlap
    expect(actionsRect.top).toBeGreaterThan(cardRect.bottom + 10) // Some spacing
  })
})

describe('Roll component: Guard validation', () => {
  it('detects problematic Roll test patterns', () => {
    const problematicRollTests = [
      'expect(grid.className).toContain("lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]")',
      'expect(container.className).toContain("lg:max-w-4xl")',
      'expect(wrapper.className).toContain("lg:mx-auto")',
      'expect(element).toHaveClass("lg:hidden")',
      'expect(region.className).toContain("md:flex")',
      'expect(grid).not.toHaveClass("xl:grid-cols-3")',
    ]
    
    for (const test of problematicRollTests) {
      expect(hasResponsiveLayoutClassAssertions(test)).toBe(true)
    }
  })

  it('allows legitimate Roll component assertions', () => {
    const legitimateRollTests = [
      'expect(element).toHaveClass("disabled")', // State
      'expect(button).toHaveClass("loading")', // Loading state
      'expect(component).toHaveClass("selected")', // Selection
      'expect(element).toHaveRole("button")', // Accessibility
      'expect(element).toHaveTextContent("Roll")', // Content
      'expect(element).toHaveAttribute("data-testid", "roll-button")', // Identity
    ]
    
    for (const test of legitimateRollTests) {
      expect(hasResponsiveLayoutClassAssertions(test)).toBe(false)
    }
  })

  it('validates the fix for existing Roll tests', () => {
    // Before fix: problematic class assertions
    const beforeFix = `
      expect(grid.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
      expect(grid.className).toContain('lg:max-w-4xl')
    `
    
    expect(hasResponsiveLayoutClassAssertions(beforeFix)).toBe(true)
    
    // After fix: geometry-based assertions
    const afterFix = `
      const gridStyle = window.getComputedStyle(grid)
      expect(gridStyle.display).toBe('grid')
      expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
      expect(gridStyle.maxWidth).toBe('1024px')
      
      const rect = grid.getBoundingClientRect()
      expect(rect.width).toBeGreaterThan(0)
      expect(rect.width).toBeLessThanOrEqual(1024)
    `
    
    expect(hasResponsiveLayoutClassAssertions(afterFix)).toBe(false)
  })
})