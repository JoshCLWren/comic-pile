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
})
