import { describe, expect, it } from 'vitest'

import {
  DEFAULT_TAG_COLOR_NAME,
  TAG_COLOR_NAMES,
  TAG_COLOR_PALETTE,
  resolveTagColorHex,
  resolveTagColorName,
} from '../utils/tagColors'

describe('tag color palette', () => {
  it('mirrors the backend palette size', () => {
    expect(TAG_COLOR_NAMES).toHaveLength(32)
  })

  it('defaults new tags to red', () => {
    expect(DEFAULT_TAG_COLOR_NAME).toBe('red')
    expect(resolveTagColorHex(DEFAULT_TAG_COLOR_NAME)).toBe('#DC2626')
  })

  it('keeps every palette entry a #RRGGBB value', () => {
    for (const hex of Object.values(TAG_COLOR_PALETTE)) {
      expect(hex).toMatch(/^#[0-9A-F]{6}$/i)
    }
  })

  it('resolves palette names to hex', () => {
    expect(resolveTagColorHex('violet')).toBe('#8B5CF6')
  })

  it('passes an unknown value through instead of silently remapping it', () => {
    expect(resolveTagColorHex('#123456')).toBe('#123456')
    expect(resolveTagColorName('#123456')).toBe('#123456')
  })

  it('resolves hex back to its palette name', () => {
    expect(resolveTagColorName('#8B5CF6')).toBe('violet')
  })
})