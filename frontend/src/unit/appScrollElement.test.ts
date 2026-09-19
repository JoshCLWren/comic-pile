import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  APP_SCROLL_ELEMENT_ID,
  getAppScrollElement,
  measureAppScrollMargin,
  observeAppScrollOffset,
  readAppScrollOffset,
  scrollAppToOffset,
} from '../scroll/appScrollElement'

describe('app page scroller (issue #2725)', () => {
  afterEach(() => {
    document.getElementById(APP_SCROLL_ELEMENT_ID)?.remove()
  })

  it('returns #root when the production shell is present', () => {
    const root = document.createElement('div')
    root.id = APP_SCROLL_ELEMENT_ID
    document.body.appendChild(root)

    expect(getAppScrollElement()).toBe(root)
  })

  it('returns null when the production shell is absent', () => {
    expect(getAppScrollElement()).toBeNull()
  })

  it('reads #root.scrollTop even when window.scrollY is 0', () => {
    const root = document.createElement('div')
    root.id = APP_SCROLL_ELEMENT_ID
    document.body.appendChild(root)
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true })
    root.scrollTop = 2400

    expect(readAppScrollOffset()).toBe(2400)
  })

  it('falls back to window.scrollY when #root is missing', () => {
    Object.defineProperty(window, 'scrollY', { value: 180, configurable: true })
    expect(readAppScrollOffset()).toBe(180)
  })

  it('keeps scrollMargin stable after the page scroller has moved', () => {
    const root = document.createElement('div')
    root.id = APP_SCROLL_ELEMENT_ID
    document.body.appendChild(root)
    const wrapper = document.createElement('div')
    root.appendChild(wrapper)

    vi.spyOn(root, 'getBoundingClientRect').mockReturnValue({ top: 0 } as DOMRect)
    vi.spyOn(wrapper, 'getBoundingClientRect').mockReturnValue({ top: 200 } as DOMRect)
    root.scrollTop = 0
    expect(measureAppScrollMargin(wrapper)).toBe(200)

    vi.spyOn(wrapper, 'getBoundingClientRect').mockReturnValue({ top: -2200 } as DOMRect)
    root.scrollTop = 2400
    expect(measureAppScrollMargin(wrapper)).toBe(200)
  })

  it('reports #root.scrollTop to observeAppScrollOffset subscribers', () => {
    const root = document.createElement('div')
    root.id = APP_SCROLL_ELEMENT_ID
    document.body.appendChild(root)
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true })
    root.scrollTop = 1200

    const offsets: number[] = []
    const unsubscribe = observeAppScrollOffset(
      // SAFETY: the observer ignores the virtualizer instance.
      {} as never,
      (offset) => {
        offsets.push(offset)
      },
    )
    expect(offsets).toEqual([1200])

    root.scrollTop = 3600
    root.dispatchEvent(new Event('scroll'))
    expect(offsets).toEqual([1200, 3600])
    if (typeof unsubscribe === 'function') {
      unsubscribe()
    }
  })

  it('scrolls #root instead of the window', () => {
    const root = document.createElement('div')
    root.id = APP_SCROLL_ELEMENT_ID
    document.body.appendChild(root)
    const windowScrollTo = vi.spyOn(window, 'scrollTo')
    const rootScrollTo = vi.fn()
    root.scrollTo = rootScrollTo as typeof root.scrollTo

    scrollAppToOffset(900, { adjustments: 50, behavior: 'auto' }, {} as never)

    expect(rootScrollTo).toHaveBeenCalledWith({ top: 950, behavior: 'auto' })
    expect(windowScrollTo).not.toHaveBeenCalled()
  })
})
