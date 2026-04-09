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
})
