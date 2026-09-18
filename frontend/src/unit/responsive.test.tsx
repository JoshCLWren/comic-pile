import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import {
  BREAKPOINTS,
  MOBILE_MAX_WIDTH,
  TABLET_MAX_WIDTH,
  useMatchMedia,
  useResponsive,
  getDefaultCollapsedForWidth,
  getDefaultCollapsed,
} from '../utils/responsive'
import { cast } from '../utils/cast'

describe('responsive contract', () => {
  describe('BREAKPOINTS', () => {
    it('defines the canonical breakpoints', () => {
      expect(BREAKPOINTS.md).toBe(768)
      expect(BREAKPOINTS.lg).toBe(1024)
      expect(BREAKPOINTS.xl).toBe(1280)
    })
  })

  describe('MOBILE_MAX_WIDTH', () => {
    it('is one below the md breakpoint', () => {
      expect(MOBILE_MAX_WIDTH).toBe(767)
    })
  })

  describe('TABLET_MAX_WIDTH', () => {
    it('is one below the lg breakpoint', () => {
      expect(TABLET_MAX_WIDTH).toBe(1023)
    })
  })

  describe('getDefaultCollapsedForWidth', () => {
    it('returns false below md (mobile)', () => {
      expect(getDefaultCollapsedForWidth(390)).toBe(false)
      expect(getDefaultCollapsedForWidth(767)).toBe(false)
    })

    it('returns true in the tablet portrait band', () => {
      expect(getDefaultCollapsedForWidth(768)).toBe(true)
      expect(getDefaultCollapsedForWidth(800)).toBe(true)
      expect(getDefaultCollapsedForWidth(1023)).toBe(true)
    })

    it('returns false at and above lg (desktop)', () => {
      expect(getDefaultCollapsedForWidth(1024)).toBe(false)
      expect(getDefaultCollapsedForWidth(1440)).toBe(false)
    })
  })
})

describe('useMatchMedia', () => {
  it('returns false when matchMedia is unavailable', () => {
    const original = window.matchMedia
    // @ts-expect-error — intentionally break matchMedia for this test
    delete window.matchMedia
    const { result } = renderHook(() => useMatchMedia('(max-width: 767px)'))
    expect(result.current).toBe(false)
    window.matchMedia = original
  })

  it('tracks whether the media query matches', () => {
    const mql = cast<MediaQueryList>({
      matches: true,
      addListener: vi.fn(),
      removeListener: vi.fn(),
    })
    window.matchMedia = vi.fn(() => mql)

    const { result } = renderHook(() => useMatchMedia('(max-width: 767px)'))
    expect(result.current).toBe(true)
  })
})

describe('useResponsive', () => {
  it('returns isMobile true for narrow viewports', () => {
    const makeMql = (matches: boolean) =>
      cast<MediaQueryList>({
        matches,
        addListener: vi.fn(),
        removeListener: vi.fn(),
      })

    window.matchMedia = vi.fn((query: string) => {
      if (query === '(max-width: 767px)') return makeMql(true)
      if (query.includes('min-width: 768px')) return makeMql(false)
      return makeMql(false)
    })

    const { result } = renderHook(() => useResponsive())
    expect(result.current.isMobile).toBe(true)
    expect(result.current.isTablet).toBe(false)
    expect(result.current.isDesktop).toBe(false)
  })
})

describe('getDefaultCollapsed', () => {
  it('returns false in SSR', () => {
    const originalWindow = global.window
    // @ts-expect-error — simulate SSR
    delete global.window
    expect(getDefaultCollapsed()).toBe(false)
    global.window = originalWindow
  })

  it('returns true in the tablet portrait band via matchMedia', () => {
    const originalMatchMedia = window.matchMedia
    window.matchMedia = vi.fn(
      () =>
        cast<MediaQueryList>({
          matches: true,
          addListener: vi.fn(),
          removeListener: vi.fn(),
        }),
    )
    expect(getDefaultCollapsed()).toBe(true)
    window.matchMedia = originalMatchMedia
  })

  it('returns false on mobile via matchMedia', () => {
    const originalMatchMedia = window.matchMedia
    window.matchMedia = vi.fn(
      () =>
        cast<MediaQueryList>({
          matches: false,
          addListener: vi.fn(),
          removeListener: vi.fn(),
        }),
    )
    expect(getDefaultCollapsed()).toBe(false)
    window.matchMedia = originalMatchMedia
  })
})
