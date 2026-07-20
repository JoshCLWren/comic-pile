import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDiagnostics } from '../hooks/useDiagnostics'

describe('useDiagnostics', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should return collectDiagnostics function', () => {
    const { result } = renderHook(() => useDiagnostics())

    expect(result.current.collectDiagnostics).toBeInstanceOf(Function)
  })

  it('should collect diagnostic data', () => {
    const { result } = renderHook(() => useDiagnostics())

    const diagnostics = result.current.collectDiagnostics()

    expect(diagnostics).toHaveProperty('timestamp')
    expect(diagnostics).toHaveProperty('url')
    expect(diagnostics).toHaveProperty('userAgent')
    expect(diagnostics).toHaveProperty('screen')
    expect(diagnostics).toHaveProperty('viewport')
    expect(diagnostics).toHaveProperty('scroll')
    expect(diagnostics).toHaveProperty('performance')
    expect(diagnostics).toHaveProperty('errors')
    expect(Array.isArray(diagnostics.errors)).toBe(true)
  })

  it('should have screen dimensions', () => {
    const { result } = renderHook(() => useDiagnostics())

    const diagnostics = result.current.collectDiagnostics()

    expect(diagnostics.screen.width).toBeGreaterThanOrEqual(0)
    expect(diagnostics.screen.height).toBeGreaterThanOrEqual(0)
    expect(diagnostics.screen.pixelRatio).toBeGreaterThan(0)
  })

  it('should have viewport dimensions', () => {
    const { result } = renderHook(() => useDiagnostics())

    const diagnostics = result.current.collectDiagnostics()

    expect(diagnostics.viewport.width).toBeGreaterThanOrEqual(0)
    expect(diagnostics.viewport.height).toBeGreaterThanOrEqual(0)
  })

  it('should have scroll position', () => {
    const { result } = renderHook(() => useDiagnostics())

    const diagnostics = result.current.collectDiagnostics()

    expect(typeof diagnostics.scroll.x).toBe('number')
    expect(typeof diagnostics.scroll.y).toBe('number')
  })

  it('should have performance data', () => {
    const { result } = renderHook(() => useDiagnostics())

    const diagnostics = result.current.collectDiagnostics()

    if (diagnostics.performance.domContentLoaded !== null) {
      expect(typeof diagnostics.performance.domContentLoaded).toBe('number')
    }
    if (diagnostics.performance.loadComplete !== null) {
      expect(typeof diagnostics.performance.loadComplete).toBe('number')
    }
  })

  it('should have timestamp in ISO format', () => {
    const { result } = renderHook(() => useDiagnostics())

    const diagnostics = result.current.collectDiagnostics()

    expect(diagnostics.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/)
  })

  it('captures mixed console errors and keeps only the newest entries', () => {
    const original = console.error
    const passthrough = vi.fn()
    console.error = passthrough
    const { result, unmount } = renderHook(() => useDiagnostics())
    const circular: Record<string, unknown> = {}
    circular.self = circular

    console.error('plain message')
    console.error(new Error('boom'))
    console.error({ detail: 'object' }, circular)
    for (let index = 0; index < 21; index += 1) console.error(`later-${index}`)

    const diagnostics = result.current.collectDiagnostics()
    expect(diagnostics.errors).toHaveLength(20)
    expect(diagnostics.errors.at(-1)?.message).toContain('later-20')
    expect(passthrough).toHaveBeenCalled()
    unmount()
    console.error = original
  })

  it('uses navigation timing values and tolerates missing or broken performance APIs', () => {
    const getEntriesByType = vi.spyOn(performance, 'getEntriesByType')
      .mockReturnValueOnce([{ domContentLoadedEventEnd: 12, loadEventEnd: 34 }] as unknown as PerformanceEntry[])
      .mockReturnValueOnce([])
      .mockImplementationOnce(() => { throw new Error('performance unavailable') })
    const { result, unmount } = renderHook(() => useDiagnostics())

    expect(result.current.collectDiagnostics().performance).toEqual({ domContentLoaded: 12, loadComplete: 34 })
    expect(result.current.collectDiagnostics().performance).toEqual({ domContentLoaded: null, loadComplete: null })
    expect(result.current.collectDiagnostics().performance).toEqual({ domContentLoaded: null, loadComplete: null })
    unmount()
    getEntriesByType.mockRestore()
  })

  it('uses safe screen and device-pixel fallbacks when browser metrics are absent', () => {
    const originalScreen = window.screen
    const originalPixelRatio = window.devicePixelRatio
    Object.defineProperty(window, 'screen', { configurable: true, value: undefined })
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 0 })
    const { result, unmount } = renderHook(() => useDiagnostics())

    expect(result.current.collectDiagnostics().screen).toEqual({ width: 0, height: 0, pixelRatio: 1 })
    unmount()
    Object.defineProperty(window, 'screen', { configurable: true, value: originalScreen })
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: originalPixelRatio })
  })

  it('falls back when performance timing is unavailable', () => {
    const originalPerformance = globalThis.performance
    vi.stubGlobal('performance', undefined)
    const { result, unmount } = renderHook(() => useDiagnostics())
    expect(result.current.collectDiagnostics().performance).toEqual({ domContentLoaded: null, loadComplete: null })
    unmount()
    vi.stubGlobal('performance', originalPerformance)
  })

  it('collects safe server-side defaults when browser globals disappear', () => {
    const { result, unmount } = renderHook(() => useDiagnostics())
    vi.stubGlobal('window', undefined)
    vi.stubGlobal('navigator', undefined)
    const diagnostics = result.current.collectDiagnostics()
    expect(diagnostics.url).toBe('')
    expect(diagnostics.userAgent).toBe('')
    expect(diagnostics.screen).toEqual({ width: 0, height: 0, pixelRatio: 1 })
    expect(diagnostics.viewport).toEqual({ width: 0, height: 0 })
    expect(diagnostics.scroll).toEqual({ x: 0, y: 0 })
    vi.unstubAllGlobals()
    unmount()
  })

})
