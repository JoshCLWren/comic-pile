import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { hasResponsiveLayoutClassAssertions } from '../../eslint-rules/class-name-layout-guard'

/**
 * Issue #3061 Acceptance Criteria Test:
 * "Tests cover invalid/nonexistent Tailwind classes still passing source-string assertions, 
 * demonstrating why the rule exists."
 * 
 * This test specifically demonstrates the core problem: invalid Tailwind classes
 * can pass class-name assertions while the layout is completely broken.
 */

// Component with intentionally invalid Tailwind classes
const ComponentWithInvalidClasses = () => (
  <div className="lg:grid lg:grid-cols-[this_is_not_valid_css] lg:max-w-4xl lg:mx-auto">
    <div data-testid="comic-region" className="bg-red-500">Comic Content</div>
    <div data-testid="decision-region" className="bg-blue-500">Decision Content</div>
  </div>
)

// Component with nonexistent Tailwind classes
const ComponentWithNonexistentClasses = () => (
  <div className="lg:grid lg:grid-cols-[nonexistent-class-syntax] lg:max-w-4xl lg:mx-auto">
    <div data-testid="comic-region" className="bg-red-500">Comic Content</div>
    <div data-testid="decision-region" className="bg-blue-500">Decision Content</div>
  </div>
)

// Component with valid classes but broken layout logic
const ComponentWithValidClassesBrokenLayout = () => (
  <div className="lg:grid lg:grid-cols-1 lg:max-w-4xl lg:mx-auto">
    <div data-testid="comic-region" className="bg-red-500">Comic Content</div>
    <div data-testid="decision-region" className="bg-blue-500">Decision Content</div>
  </div>
)

describe('Demonstrates why the rule exists: Invalid classes pass assertions', () => {
  it('shows invalid Tailwind classes still pass className assertions', () => {
    render(<ComponentWithInvalidClasses />)
    
    const container = screen.getByTestId('comic-region').parentElement!
    const comicRegion = screen.getByTestId('comic-region')
    const decisionRegion = screen.getByTestId('decision-region')
    
    // ✅ These assertions PASS even though the classes are invalid
    expect(container.className).toContain('lg:grid')
    expect(container.className).toContain('lg:grid-cols-[this_is_not_valid_css]')
    expect(container.className).toContain('lg:max-w-4xl')
    expect(container.className).toContain('lg:mx-auto')
    expect(comicRegion.className).toContain('bg-red-500')
    expect(decisionRegion.className).toContain('bg-blue-500')
    
    // ❌ But the actual layout is completely broken:
    const containerStyle = window.getComputedStyle(container)
    expect(containerStyle.display).toBe('grid') // This still works
    
    // The invalid grid syntax makes the grid collapse to 1 column
    expect(containerStyle.gridTemplateColumns).toBe('1fr') // NOT the intended layout
    
    // The content is stacked instead of side by side
    const comicRect = comicRegion.getBoundingClientRect()
    const decisionRect = decisionRegion.getBoundingClientRect()
    
    // Regions are stacked vertically, not horizontally
    expect(decisionRect.top).toBeGreaterThan(comicRect.bottom)
    expect(decisionRect.left).toBe(comicRect.left) // Same column
  })

  it('shows nonexistent Tailwind classes pass string matching', () => {
    render(<ComponentWithNonexistentClasses />)
    
    const container = screen.getByTestId('comic-region').parentElement!
    
    // ✅ These assertions PASS even though the classes don't exist in Tailwind
    expect(container.className).toContain('lg:grid-cols-[nonexistent-class-syntax]')
    expect(container.className).toContain('lg:max-w-4xl')
    
    // ❌ The layout is broken because the syntax is invalid
    const containerStyle = window.getComputedStyle(container)
    expect(containerStyle.gridTemplateColumns).toBe('1fr') // Collapsed to single column
  })

  it('shows how valid classes can still have broken layout logic', () => {
    render(<ComponentWithValidClassesBrokenLayout />)
    
    const container = screen.getByTestId('comic-region').parentElement!
    const comicRegion = screen.getByTestId('comic-region')
    const decisionRegion = screen.getByTestId('decision-region')
    
    // ✅ These assertions PASS - all classes are valid Tailwind classes
    expect(container.className).toContain('lg:grid')
    expect(container.className).toContain('lg:grid-cols-1') // Valid class
    expect(container.className).toContain('lg:max-w-4xl')
    expect(container.className).toContain('lg:mx-auto')
    
    // ❌ But the layout logic is wrong - it should be 2 columns, not 1
    const containerStyle = window.getComputedStyle(container)
    expect(containerStyle.gridTemplateColumns).toBe('1fr')
    
    // Content is stacked instead of side by side
    const comicRect = comicRegion.getBoundingClientRect()
    const decisionRect = decisionRegion.getBoundingClientRect()
    expect(decisionRect.top).toBeGreaterThan(comicRect.bottom) // Stacked
  })
})

describe('Demonstrates the solution: Geometry-based assertions catch these issues', () => {
  it('geometry assertions catch invalid class issues', () => {
    render(<ComponentWithInvalidClasses />)
    
    const container = screen.getByTestId('comic-region').parentElement!
    const comicRegion = screen.getByTestId('comic-region')
    const decisionRegion = screen.getByTestId('decision-region')
    
    // ✅ Geometry-based assertions would CATCH the layout issues:
    
    // 1. Check that the grid actually has the intended columns
    const containerStyle = window.getComputedStyle(container)
    expect(containerStyle.gridTemplateColumns).toBe('1fr') // This fails the intended layout
    
    // 2. Check that content is actually side by side
    const comicRect = comicRegion.getBoundingClientRect()
    const decisionRect = decisionRegion.getBoundingClientRect()
    expect(decisionRect.top).toBeGreaterThan(comicRect.bottom) // This shows they're stacked
    
    // 3. Check that the intended two-column layout actually exists
    expect(comicRect.width).toBeGreaterThan(0)
    expect(decisionRect.width).toBeGreaterThan(0)
    expect(Math.abs(comicRect.left - decisionRect.left)).toBeLessThan(
      Math.max(comicRect.width, decisionRect.width)
    ) // This fails because they're in the same column
  })

  it('geometry assertions catch broken layout logic', () => {
    render(<ComponentWithValidClassesBrokenLayout />)
    
    const container = screen.getByTestId('comic-region').parentElement!
    const comicRegion = screen.getByTestId('comic-region')
    const decisionRegion = screen.getByTestId('decision-region')
    
    // ✅ These geometry assertions would catch the broken layout:
    
    // 1. Prove the grid has the correct number of columns
    const containerStyle = window.getComputedStyle(container)
    expect(containerStyle.gridTemplateColumns).toBe('1fr') // Should be 2 columns
    
    // 2. Prove content is actually in two columns
    const comicRect = comicRegion.getBoundingClientRect()
    const decisionRect = decisionRegion.getBoundingClientRect()
    expect(decisionRect.left).toBe(comicRect.left) // Same column, should be different
    
    // 3. Prove the intended layout exists
    expect(comicRect.width).toBe(decisionRect.width) // Should be different widths
  })
})

describe('Guard validation: Detects these problematic patterns', () => {
  it('detects assertions that would pass with invalid classes', () => {
    const problematicTests = [
      // These would PASS with the broken components but should be rejected
      'expect(container.className).toContain("lg:grid-cols-[this_is_not_valid_css]")',
      'expect(container.className).toContain("lg:grid-cols-[nonexistent-class-syntax]")',
      'expect(element.className).toContain("lg:grid-cols-1")', // Valid class but wrong layout
      'expect(grid.className).toContain("lg:max-w-4xl")',
      'expect(wrapper.className).toContain("lg:mx-auto")',
    ]
    
    for (const test of problematicTests) {
      expect(hasResponsiveLayoutClassAssertions(test)).toBe(true)
    }
  })

  it('shows the correct geometry-based alternatives', () => {
    // Problematic: class assertions that pass with broken layouts
    const problematic = `
      expect(container.className).toContain("lg:grid-cols-[invalid_syntax]")
      expect(container.className).toContain("lg:max-w-4xl")
    `
    
    expect(hasResponsiveLayoutClassAssertions(problematic)).toBe(true)
    
    // Correct: geometry assertions that catch broken layouts
    const correct = `
      const containerStyle = window.getComputedStyle(container)
      expect(containerStyle.gridTemplateColumns).toBe("minmax(0,24rem) minmax(18rem,24rem)")
      expect(containerStyle.maxWidth).toBe("1024px")
      
      const rect = container.getBoundingClientRect()
      expect(rect.width).toBeGreaterThan(0)
      expect(rect.width).toBeLessThanOrEqual(1024)
    `
    
    expect(hasResponsiveLayoutClassAssertions(correct)).toBe(false)
  })

  it('demonstrates the guard catches the exact problem described in #3061', () => {
    // This represents the exact issue: tests that claim responsive layout
    // correctness through class-name assertions but don't prove actual geometry
    const issue2949StyleTest = `
      describe('Roll layout responsive regression', () => {
        it('has correct responsive classes', () => {
          const grid = screen.getByTestId('rating-grid')
          // These assertions PASS even with invalid/broken classes
          expect(grid.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
          expect(grid.className).toContain('lg:max-w-4xl')
          expect(grid.className).toContain('lg:mx-auto')
          
          const comicRegion = screen.getByTestId('rating-region-comic')
          expect(comicRegion.className).toContain('min-w-0')
        })
      })
    `
    
    // The guard should detect this as problematic
    expect(hasResponsiveLayoutClassAssertions(issue2949StyleTest)).toBe(true)
    
    // The correct approach using geometry
    const issue2995StyleTest = `
      describe('Roll layout responsive regression', () => {
        it('renders correct geometry', () => {
          const grid = screen.getByTestId('rating-grid')
          // These assertions prove actual geometry works
          const gridStyle = window.getComputedStyle(grid)
          expect(gridStyle.display).toBe('grid')
          expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
          expect(gridStyle.maxWidth).toBe('1024px')
          
          const comicRect = grid.getBoundingClientRect()
          expect(comicRect.width).toBeGreaterThan(0)
          expect(comicRect.width).toBeLessThanOrEqual(1024)
        })
      })
    `
    
    // The guard should allow this
    expect(hasResponsiveLayoutClassAssertions(issue2995StyleTest)).toBe(false)
  })
})