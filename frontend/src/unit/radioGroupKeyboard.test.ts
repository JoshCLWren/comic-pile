import { describe, expect, it } from 'vitest'

import { radioGroupNavigationTarget } from '../utils/radioGroupKeyboard'

describe('radioGroupNavigationTarget', () => {
  it('moves forward with ArrowRight and ArrowDown', () => {
    expect(radioGroupNavigationTarget('ArrowRight', 0, 3)).toBe(1)
    expect(radioGroupNavigationTarget('ArrowDown', 1, 3)).toBe(2)
  })

  it('moves backward with ArrowLeft and ArrowUp', () => {
    expect(radioGroupNavigationTarget('ArrowLeft', 2, 3)).toBe(1)
    expect(radioGroupNavigationTarget('ArrowUp', 1, 3)).toBe(0)
  })

  it('wraps at both ends', () => {
    expect(radioGroupNavigationTarget('ArrowRight', 2, 3)).toBe(0)
    expect(radioGroupNavigationTarget('ArrowLeft', 0, 3)).toBe(2)
  })

  it('jumps to the group edges with Home and End', () => {
    expect(radioGroupNavigationTarget('Home', 2, 5)).toBe(0)
    expect(radioGroupNavigationTarget('End', 0, 5)).toBe(4)
  })

  it('ignores unrelated keys and unusable focus positions', () => {
    expect(radioGroupNavigationTarget('Tab', 0, 3)).toBeNull()
    expect(radioGroupNavigationTarget('Enter', 0, 3)).toBeNull()
    expect(radioGroupNavigationTarget('ArrowRight', -1, 3)).toBeNull()
    expect(radioGroupNavigationTarget('ArrowRight', 0, 0)).toBeNull()
    expect(radioGroupNavigationTarget('ArrowRight', 3, 3)).toBeNull()
  })
})
