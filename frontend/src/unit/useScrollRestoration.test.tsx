import { act, render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useScrollRestoration } from '../hooks/useScrollRestoration'

function TestScreen() {
  useScrollRestoration()
  return <div data-testid="screen">screen</div>
}

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Routes>
        <Route path="*" element={<TestScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

const SCROLL_KEY = 'comic-pile:scroll-positions'

describe('useScrollRestoration', () => {
  let scrollTo: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 0
    })
    vi.stubGlobal('cancelAnimationFrame', () => undefined)
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('restores the saved scroll position for a screen on return', async () => {
    sessionStorage.setItem(SCROLL_KEY, JSON.stringify({ '/': 240 }))
    renderAt('/')
    await act(async () => {
      await Promise.resolve()
    })
    expect(scrollTo).toHaveBeenCalledWith(0, 240)
  })

  it('starts a new screen at the top when nothing is saved', async () => {
    renderAt('/queue')
    await act(async () => {
      await Promise.resolve()
    })
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
  })

  it('captures the live scroll position as the user scrolls', async () => {
    renderAt('/')
    await act(async () => {
      await Promise.resolve()
    })

    const scrollGetter = vi.spyOn(window, 'scrollY', 'get').mockReturnValue(512)
    await act(async () => {
      window.dispatchEvent(new Event('scroll'))
      await Promise.resolve()
    })
    scrollGetter.mockRestore()

    const store = JSON.parse(sessionStorage.getItem(SCROLL_KEY) ?? '{}')
    expect(store['/']).toBe(512)
  })

  it('persists the position across a reload so the user returns to the same place', async () => {
    sessionStorage.setItem(SCROLL_KEY, JSON.stringify({ '/': 120 }))
    renderAt('/')
    await act(async () => {
      await Promise.resolve()
    })
    expect(scrollTo).toHaveBeenCalledWith(0, 120)
  })

  it('re-applies the saved position after deferred content settles without a fixed timeout', async () => {
    // Deferred data renders grow the page after the first restore pass, which
    // the browser may have clamped. The settle contract must re-apply the
    // saved offset once layout stabilizes — driven by layout frames, not by
    // waiting out a guessed delay.
    sessionStorage.setItem(SCROLL_KEY, JSON.stringify({ '/': 240 }))
    const heights = [800, 1600, 1600, 1600, 1600, 1600]
    Object.defineProperty(document.documentElement, 'scrollHeight', {
      configurable: true,
      get: () => heights.shift() ?? 1600,
    })

    renderAt('/')
    await act(async () => {
      await Promise.resolve()
    })
    // Restore the original descriptor so subsequent tests are unaffected.
    Reflect.deleteProperty(document.documentElement, 'scrollHeight')

    expect(scrollTo).toHaveBeenCalledWith(0, 240)
    // Initial restore plus at least one re-apply once deferred layout grew.
    expect(scrollTo.mock.calls.length).toBeGreaterThan(1)
    for (const call of scrollTo.mock.calls) {
      expect(call).toEqual([0, 240])
    }
  })

  it('leaves the viewport alone once the user scrolls during the settle window', async () => {
    // Queue layout frames manually so a user gesture can land mid-settle.
    // Without cancellation every frame would re-apply (jsdom scrollY never
    // reaches the target); the wheel gesture must end the watch instead.
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      frames.push(cb)
      return frames.length
    })
    sessionStorage.setItem(SCROLL_KEY, JSON.stringify({ '/': 240 }))
    renderAt('/')
    await act(async () => {
      frames.shift()?.(0)
    })
    expect(scrollTo).toHaveBeenCalledWith(0, 240)
    const callsAfterFirstRestore = scrollTo.mock.calls.length

    await act(async () => {
      window.dispatchEvent(new Event('wheel'))
    })
    await act(async () => {
      while (frames.length > 0) {
        frames.shift()?.(0)
      }
    })

    // The initial restore still applies; the settle watch ends on the user
    // gesture instead of re-applying over an intentional scroll.
    expect(scrollTo.mock.calls.length).toBe(callsAfterFirstRestore)
  })
})
