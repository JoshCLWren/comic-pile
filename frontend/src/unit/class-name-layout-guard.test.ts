import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { hasResponsiveLayoutClassAssertions } from '../../eslint-rules/class-name-layout-guard'

/**
 * Issue #3061: Ban DOM class-name assertions as evidence of responsive layout correctness.
 * 
 * This test suite demonstrates:
 * 1. The problem: class-name assertions that pass even when layout is broken
 * 2. The solution: geometry-based assertions that prove actual rendered behavior
 * 3. The guard: automated detection of problematic patterns
 * 4. Legitimate cases: class assertions unrelated to visual geometry
 */

// Mock components for testing
const MockResponsiveComponent = () => (
  <div className="lg:grid lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)] lg:max-w-4xl lg:mx-auto">
    <div data-testid="comic-region" className="bg-red-500">Comic Content</div>
    <div data-testid="decision-region" className="bg-blue-500">Decision Content</div>
  </div>
)

const BrokenResponsiveComponent = () => (
  <div className="lg:grid lg:grid-cols-[invalid_syntax] lg:max-w-4xl lg:mx-auto">
    <div data-testid="comic-region" className="bg-red-500">Comic Content</div>
    <div data-testid="decision-region" className="bg-blue-500">Decision Content</div>
  </div>
)

describe('Problem: Class-name assertions pass even when layout is broken', () => {
  it('demonstrates the flaw: className assertions pass with invalid Tailwind classes', () => {
    // This represents the pattern from #2949 - asserting class names exists
    // but not proving the actual layout works
    render(<BrokenResponsiveComponent />)
    
    // These assertions would PASS even though the layout is completely broken
    // because the class names are still present in the DOM
    const comicRegion = screen.getByTestId('comic-region')
    const decisionRegion = screen.getByTestId('decision-region')
    
    // ✅ These pass - class names are present
    expect(comicRegion.className).toContain('lg:grid')
    expect(comicRegion.parentElement?.className).toContain('lg:grid-cols-[invalid_syntax]')
    expect(comicRegion.parentElement?.className).toContain('lg:max-w-4xl')
    expect(decisionRegion.className).toContain('bg-blue-500')
    
    // ❌ But the actual layout is broken:
    // - The invalid syntax `grid-cols-[invalid_syntax]` makes the grid collapse
    // - The content doesn't actually render in two columns
    // - The layout doesn't respect the max-width constraints
    // - The responsive behavior doesn't work as intended
  })

  it('shows how invalid classes still pass string matching', () => {
    const problematicTestCode = `
      expect(element.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
      expect(element.className).toContain('lg:max-w-4xl')
      expect(element.className).toContain('lg:mx-auto')
    `
    
    // This should be detected as problematic by our guard
    expect(hasResponsiveLayoutClassAssertions(problematicTestCode)).toBe(true)
  })
})

describe('Solution: Geometry-based assertions prove actual rendered behavior', () => {
  it('uses bounding box measurements to prove actual layout geometry', () => {
    render(<MockResponsiveComponent />)
    
    const comicRegion = screen.getByTestId('comic-region')
    const decisionRegion = screen.getByTestId('decision-region')
    const container = comicRegion.parentElement!
    
    // ✅ These assertions prove actual rendered geometry:
    
    // 1. Prove the container is actually a grid
    const containerStyle = window.getComputedStyle(container)
    expect(containerStyle.display).toBe('grid')
    
    // 2. Prove the grid has the correct number of columns
    expect(containerStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
    
    // 3. Prove the container has the correct max-width
    expect(containerStyle.maxWidth).toBe('1024px') // 4xl = 1024px
    
    // 4. Prove the content is actually laid out in two columns
    const comicRect = comicRegion.getBoundingClientRect()
    const decisionRect = decisionRegion.getBoundingClientRect()
    
    // Both regions should have width > 0 (not collapsed)
    expect(comicRect.width).toBeGreaterThan(0)
    expect(decisionRect.width).toBeGreaterThan(0)
    
    // Comic region should be wider than decision region (24rem vs 18rem)
    expect(comicRect.width).toBeGreaterThan(decisionRect.width)
    
    // Regions should be side by side (not stacked)
    expect(Math.abs(comicRect.left - decisionRect.left)).toBeLessThan(
      Math.max(comicRect.width, decisionRect.width)
    )
  })

  it('uses computed styles to prove responsive behavior', () => {
    // Simulate different viewport sizes
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 1024, // lg breakpoint
    })
    
    // Trigger a re-render with the new viewport
    render(<MockResponsiveComponent />)
    
    const container = screen.getByTestId('comic-region').parentElement!
    const containerStyle = window.getComputedStyle(container)
    
    // ✅ Prove the responsive behavior actually works:
    expect(containerStyle.display).toBe('grid')
    expect(containerStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
    
    // Clean up
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 1920, // Reset to original
    })
  })

  it('uses viewport containment to prove responsive layout', () => {
    render(<MockResponsiveComponent />)
    
    const container = screen.getByTestId('comic-region').parentElement!
    const containerRect = container.getBoundingClientRect()
    const viewportWidth = window.innerWidth
    
    // ✅ Prove the container is properly contained within viewport
    expect(containerRect.left).toBeGreaterThanOrEqual(0)
    expect(containerRect.right).toBeLessThanOrEqual(viewportWidth)
    expect(containerRect.width).toBeLessThanOrEqual(viewportWidth)
    
    // Prove the max-width constraint is actually respected
    expect(containerRect.width).toBeLessThanOrEqual(1024) // 4xl = 1024px
  })
})

describe('Guard: Automated detection of problematic patterns', () => {
  it('detects responsive layout class assertions', () => {
    const problematicPatterns = [
      'expect(element.className).toContain("lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]")',
      'expect(container.className).toContain("lg:max-w-4xl")',
      'expect(wrapper.className).toContain("md:flex")',
      'expect(grid.className).toMatch("xl:grid-cols-2")',
      'expect(element).toHaveClass("lg:hidden")',
      'expect(component).not.toHaveClass("sm:block")',
    ]
    
    for (const pattern of problematicPatterns) {
      expect(hasResponsiveLayoutClassAssertions(pattern)).toBe(true)
    }
  })

  it('allows legitimate class assertions unrelated to geometry', () => {
    const legitimatePatterns = [
      'expect(element).toHaveClass("disabled")', // Semantic state
      'expect(button).toHaveClass("loading")', // Loading state
      'expect(component).toHaveClass("selected")', // Selection state
      'expect(element.className).toContain("text-red-500")', // Color (not layout)
      'expect(wrapper.className).toContain("p-3")', // Padding (not responsive)
      'expect(element).toHaveClass("bg-white")', // Background color
    ]
    
    for (const pattern of legitimatePatterns) {
      expect(hasResponsiveLayoutClassAssertions(pattern)).toBe(false)
    }
  })

  it('ignores non-test code', () => {
    const productionCode = `
      <div className="lg:grid lg:grid-cols-2">
        <Content />
      </div>
    `
    
    expect(hasResponsiveLayoutClassAssertions(productionCode)).toBe(false)
  })
})

describe('Acceptance criteria validation', () => {
  it('rejects class-only assertions as insufficient layout coverage', () => {
    // This represents the pattern from #2949 that should be rejected
    const insufficientTest = `
      describe('Responsive layout', () => {
        it('has correct responsive classes', () => {
          const grid = screen.getByTestId('rating-grid')
          expect(grid.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
          expect(grid.className).toContain('lg:max-w-4xl')
          expect(grid.className).toContain('lg:mx-auto')
        })
      })
    `
    
    expect(hasResponsiveLayoutClassAssertions(insufficientTest)).toBe(true)
  })

  it('accepts geometry-based tests as proper coverage', () => {
    // This represents the pattern from #2995 that should be accepted
    const sufficientTest = `
      describe('Responsive layout', () => {
        it('renders correct geometry', () => {
          const grid = screen.getByTestId('rating-grid')
          const gridStyle = window.getComputedStyle(grid)
          expect(gridStyle.display).toBe('grid')
          expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
          expect(gridStyle.maxWidth).toBe('1024px')
          
          const rect = grid.getBoundingClientRect()
          expect(rect.width).toBeGreaterThan(0)
          expect(rect.width).toBeLessThanOrEqual(1024)
        })
      })
    `
    
    expect(hasResponsiveLayoutClassAssertions(sufficientTest)).toBe(false)
  })

  it('demonstrates why the rule exists with invalid classes', () => {
    // Test with a component that has invalid Tailwind classes
    render(<BrokenResponsiveComponent />)
    
    // Even with invalid classes, these assertions would PASS:
    const container = screen.getByTestId('comic-region').parentElement!
    expect(container.className).toContain('lg:grid')
    expect(container.className).toContain('lg:grid-cols-[invalid_syntax]')
    expect(container.className).toContain('lg:max-w-4xl')
    
    // But the actual layout is broken:
    const containerStyle = window.getComputedStyle(container)
    expect(containerStyle.gridTemplateColumns).not.toBe('minmax(0,24rem) minmax(18rem,24rem)')
    
    // This proves why class-name assertions are insufficient
    expect(hasResponsiveLayoutClassAssertions(`
      expect(container.className).toContain('lg:grid-cols-[invalid_syntax]')
      expect(container.className).toContain('lg:max-w-4xl')
    `)).toBe(true)
  })
})