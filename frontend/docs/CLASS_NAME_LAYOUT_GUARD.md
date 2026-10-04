# DOM Class-Name Layout Guard

## Issue #3061: Ban DOM class-name assertions as evidence of responsive layout correctness

This guard prevents tests from using DOM class-name assertions as evidence of responsive layout correctness. Instead, tests must prove rendered geometry or observable browser outcomes.

## Why This Rule Exists

Class-name assertions are insufficient for layout regression coverage because:

1. **Invalid/nonexistent Tailwind classes can still pass string assertions**
   - `lg:grid-cols-[invalid_syntax]` passes `.toContain()` but creates invalid CSS
   - The layout silently collapses but the test still passes

2. **Class names don't prove actual rendered geometry**
   - `lg:max-w-4xl` doesn't prove the element actually respects the max-width
   - `lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]` doesn't prove the grid actually renders with those columns

3. **Layout behavior should be tested through observable browser measurements**
   - Actual dimensions, positioning, and visibility
   - Computed styles and rendering behavior
   - Viewport containment and responsive behavior

## Rule Detection

The guard detects problematic patterns in test files:

### Problematic Patterns (Rejected)

```typescript
// ❌ These are rejected:
expect(element.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
expect(container.className).toContain('lg:max-w-4xl')
expect(grid.className).toContain('lg:mx-auto')
expect(element).toHaveClass('lg:hidden')
expect(wrapper.className).toContain('md:flex')
```

### Allowed Patterns (Accepted)

```typescript
// ✅ These are allowed:
expect(element).toHaveClass('disabled')        // Semantic state
expect(button).toHaveClass('loading')          // Loading state
expect(component).toHaveClass('selected')      // Selection state
expect(element.className).toContain('text-red-500') // Color (not layout)
expect(wrapper.className).toContain('p-3')       // Padding (not responsive)
expect(element).toHaveClass('bg-white')        // Background color
```

## Geometry-Based Testing Patterns

### 1. Bounding Box Measurements

Prove actual dimensions and positioning:

```typescript
// ✅ Prove actual dimensions
const rect = element.getBoundingClientRect()
expect(rect.width).toBeGreaterThan(0)
expect(rect.height).toBeGreaterThan(0)
expect(rect.width).toBeLessThanOrEqual(1024) // Respect max-w-4xl

// ✅ Prove positioning
expect(rect.left).toBeGreaterThanOrEqual(0)
expect(rect.right).toBeLessThanOrEqual(window.innerWidth)
expect(rect.top).toBeGreaterThanOrEqual(0)
```

### 2. Computed Styles

Prove actual CSS properties:

```typescript
// ✅ Prove grid behavior
const gridStyle = window.getComputedStyle(grid)
expect(gridStyle.display).toBe('grid')
expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
expect(gridStyle.maxWidth).toBe('1024px')

// ✅ Prove responsive behavior
expect(gridStyle.justifyContent).toBe('center')
expect(gridStyle.alignItems).toBe('start')
```

### 3. Viewport Containment

Prove responsive behavior at different sizes:

```typescript
// ✅ Prove responsive layout
const container = element.getBoundingClientRect()
const viewportWidth = window.innerWidth
expect(container.left).toBeGreaterThanOrEqual(0)
expect(container.right).toBeLessThanOrEqual(viewportWidth)
expect(container.width).toBeLessThanOrEqual(viewportWidth)
```

### 4. Content Layout

Prove content is properly arranged:

```typescript
// ✅ Prove side-by-side layout
const comicRect = comicElement.getBoundingClientRect()
const decisionRect = decisionElement.getBoundingClientRect()
expect(comicRect.width).toBeGreaterThan(decisionRect.width) // 24rem vs 18rem
expect(Math.abs(comicRect.left - decisionRect.left)).toBeLessThan(
  Math.max(comicRect.width, decisionRect.width)
)

// ✅ Prove no overlap
expect(decisionRect.top).toBeGreaterThan(comicRect.bottom)
```

### 5. Aspect Ratio and Sizing

Proper image and content sizing:

```typescript
// ✅ Prove aspect ratio
const cover = document.querySelector('[data-testid="comic-cover"]')
const coverRect = cover.getBoundingClientRect()
const aspectRatio = coverRect.width / coverRect.height
expect(aspectRatio).toBeCloseTo(2/3, 1)

// ✅ Prove responsive sizing
expect(coverRect.width).toBeGreaterThan(0)
expect(coverRect.height).toBeLessThanOrEqual(window.innerHeight * 0.45)
```

## Migration Guide

### Before: Class-Name Assertions (Problematic)

```typescript
describe('RatingView desktop layout', () => {
  it('has correct responsive classes', () => {
    const grid = screen.getByTestId('rating-pillars-grid')
    expect(grid.className).toContain('lg:grid')
    expect(grid.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
    expect(grid.className).toContain('lg:max-w-4xl')
    expect(grid.className).toContain('lg:mx-auto')
    
    const comicRegion = screen.getByTestId('rating-region-comic')
    expect(comicRegion.className).toContain('min-w-0')
  })
})
```

### After: Geometry-Based Assertions (Correct)

```typescript
describe('RatingView desktop layout', () => {
  it('renders correct geometry', () => {
    const grid = screen.getByTestId('rating-pillars-grid')
    
    // ✅ Prove actual grid behavior
    const gridStyle = window.getComputedStyle(grid)
    expect(gridStyle.display).toBe('grid')
    expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
    expect(gridStyle.maxWidth).toBe('1024px')
    expect(gridStyle.marginLeft).toBe('auto')
    expect(gridStyle.marginRight).toBe('auto')
    
    // ✅ Prove actual dimensions
    const gridRect = grid.getBoundingClientRect()
    expect(gridRect.width).toBeGreaterThan(0)
    expect(gridRect.width).toBeLessThanOrEqual(1024)
    
    // ✅ Prove content layout
    const comicRegion = screen.getByTestId('rating-region-comic')
    const decisionRegion = screen.getByTestId('rating-region-decision')
    const comicRect = comicRegion.getBoundingClientRect()
    const decisionRect = decisionRegion.getBoundingClientRect()
    
    expect(comicRect.width).toBeGreaterThan(decisionRect.width)
    expect(comicRect.width).toBeGreaterThan(0)
    expect(decisionRect.width).toBeGreaterThan(0)
  })
})
```

## Examples

### Example 1: Two-Column Grid Layout

#### Problem (Rejected)
```typescript
expect(grid.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
```

#### Solution (Accepted)
```typescript
const gridStyle = window.getComputedStyle(grid)
expect(gridStyle.display).toBe('grid')
expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')

const cells = grid.querySelectorAll(':scope > div')
expect(cells.length).toBe(2)

const cell1Rect = cells[0].getBoundingClientRect()
const cell2Rect = cells[1].getBoundingClientRect()
expect(cell1Rect.width).toBeGreaterThan(cell2Rect.width)
```

### Example 2: Responsive Max-Width

#### Problem (Rejected)
```typescript
expect(container.className).toContain('lg:max-w-4xl')
```

#### Solution (Accepted)
```typescript
const containerStyle = window.getComputedStyle(container)
expect(containerStyle.maxWidth).toBe('1024px')

const containerRect = container.getBoundingClientRect()
expect(containerRect.width).toBeGreaterThan(0)
expect(containerRect.width).toBeLessThanOrEqual(1024)
```

### Example 3: Responsive Visibility

#### Problem (Rejected)
```typescript
expect(element).toHaveClass('lg:hidden')
```

#### Solution (Accepted)
```typescript
const elementStyle = window.getComputedStyle(element)
const elementRect = element.getBoundingClientRect()

// Prove element is actually hidden or visible based on viewport
if (window.innerWidth < 768) {
  expect(elementRect.width).toBe(0) // Hidden
} else {
  expect(elementRect.width).toBeGreaterThan(0) // Visible
}
```

## Integration with CI

The rule is enforced through ESLint and will fail CI for new tests that use problematic patterns:

```bash
cd frontend && npm run lint
```

The rule specifically targets test files (`/test/`, `/unit/`) and ignores production code.

## Testing the Guard

Run the guard tests to verify the detection works:

```bash
cd frontend && npm test src/unit/class-name-layout-guard.test.ts
```

The tests demonstrate:
1. How invalid classes still pass assertions
2. How geometry-based assertions catch layout issues
3. Which patterns are detected vs allowed