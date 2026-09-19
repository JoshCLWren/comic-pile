import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  beginRouteRestore,
  isRouteRestoreSettling,
  requestSemanticScroll,
  restoreRouteScrollPosition,
  scrollToTopSemantic,
  waitForLayoutSettled,
} from '../scroll/scrollCoordinator'

describe('scrollCoordinator (issue #2582)', () => {
  let scrollTo: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 0
    })
    vi.stubGlobal('cancelAnimationFrame', () => undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    expect(isRouteRestoreSettling()).toBe(false)
  })

  it('restores a route position through the single restoration write', () => {
    restoreRouteScrollPosition(240)
    expect(scrollTo).toHaveBeenCalledTimes(1)
    expect(scrollTo).toHaveBeenCalledWith(0, 240)
  })

  it('runs semantic scrolling immediately when no restore is settling', () => {
    const action = vi.fn()
    requestSemanticScroll(action)
    expect(action).toHaveBeenCalledTimes(1)
  })

  it('defers semantic scrolling while a restore settles, then flushes in order', () => {
    const calls: string[] = []
    const endRestore = beginRouteRestore()
    expect(isRouteRestoreSettling()).toBe(true)

    requestSemanticScroll(() => {
      calls.push('first')
    })
    requestSemanticScroll(() => {
      calls.push('second')
    })
    expect(calls).toEqual([])

    endRestore()
    expect(isRouteRestoreSettling()).toBe(false)
    expect(calls).toEqual(['first', 'second'])
  })

  it('keeps nested restores settling until the outermost restore ends', () => {
    const action = vi.fn()
    const endOuter = beginRouteRestore()
    const endInner = beginRouteRestore()

    requestSemanticScroll(action)
    endInner()
    expect(isRouteRestoreSettling()).toBe(true)
    expect(action).not.toHaveBeenCalled()

    endOuter()
    expect(isRouteRestoreSettling()).toBe(false)
    expect(action).toHaveBeenCalledTimes(1)
  })

  it('scrolls to the top for an explicit semantic transition when idle', () => {
    scrollToTopSemantic()
    expect(scrollTo).toHaveBeenCalledTimes(1)
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: 'auto' })
  })

  it('defers the semantic top scroll while a restore is settling', () => {
    const endRestore = beginRouteRestore()
    scrollToTopSemantic()
    expect(scrollTo).not.toHaveBeenCalled()
    endRestore()
    expect(scrollTo).toHaveBeenCalledTimes(1)
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: 'auto' })
  })

  it('settles against layout stability without any fixed timeout', async () => {
    const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout')
    const heights = [800, 1200, 1200, 1200, 1200]
    const reapply = vi.fn()
    const needsReapply = vi.fn(() => false)

    await waitForLayoutSettled({
      readHeight: () => heights.shift() ?? 1200,
      needsReapply,
      reapply,
    })

    expect(needsReapply).toHaveBeenCalled()
    expect(reapply).not.toHaveBeenCalled()
    expect(setTimeoutSpy).not.toHaveBeenCalled()
    setTimeoutSpy.mockRestore()
  })

  it('re-applies the target while deferred layout is still shifting', async () => {
    const heights = [800, 1600, 1600, 1600, 1600]
    const reapplied: number[] = []

    await waitForLayoutSettled({
      readHeight: () => heights.shift() ?? 1600,
      needsReapply: () => reapplied.length === 0,
      reapply: () => {
        reapplied.push(240)
      },
    })

    expect(reapplied).toEqual([240])
  })

  it('stops settling immediately once cancelled', async () => {
    let frames = 0
    await waitForLayoutSettled({
      readHeight: () => {
        frames += 1
        return frames
      },
      isCancelled: () => frames >= 2,
    })
    expect(frames).toBe(2)
  })
})
