import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MarqueeTitle } from '../components/MarqueeTitle'

afterEach(() => {
  vi.unstubAllGlobals()
})

it('keeps a fitting title truncated when ResizeObserver is unavailable', () => {
  vi.stubGlobal('ResizeObserver', undefined)

  render(<MarqueeTitle title="Compact title" className="custom-title" />)

  const heading = screen.getByRole('heading', { name: 'Compact title' })
  expect(heading).toHaveClass('truncate', 'custom-title')
  expect(screen.getAllByText('Compact title')).toHaveLength(1)
})

it('starts and stops the marquee as observed dimensions change', () => {
  let resizeCallback: ResizeObserverCallback | undefined
  const observe = vi.fn()
  const disconnect = vi.fn()

  class ResizeObserverMock {
    constructor(callback: ResizeObserverCallback) {
      resizeCallback = callback
    }

    observe = observe
    disconnect = disconnect
    unobserve = vi.fn()
  }

  vi.stubGlobal('ResizeObserver', ResizeObserverMock)

  const { container, unmount } = render(
    <MarqueeTitle title="A deliberately long comic title" />
  )
  const wrapper = container.firstElementChild as HTMLDivElement
  const heading = screen.getByRole('heading', { name: 'A deliberately long comic title' })

  Object.defineProperty(wrapper, 'clientWidth', { configurable: true, value: 120 })
  Object.defineProperty(heading, 'scrollWidth', { configurable: true, value: 240 })

  act(() => {
    resizeCallback?.([], {} as ResizeObserver)
  })

  expect(observe).toHaveBeenCalledWith(wrapper)
  expect(observe).toHaveBeenCalledWith(heading)
  expect(heading).toHaveClass('marquee-runner')
  expect(screen.getAllByText('A deliberately long comic title')).toHaveLength(2)
  expect(screen.getAllByText('A deliberately long comic title')[1]).toHaveAttribute(
    'aria-hidden',
    'true'
  )

  Object.defineProperty(heading, 'scrollWidth', { configurable: true, value: 80 })
  act(() => {
    resizeCallback?.([], {} as ResizeObserver)
  })

  expect(heading).toHaveClass('truncate')
  expect(screen.getAllByText('A deliberately long comic title')).toHaveLength(1)

  unmount()
  expect(disconnect).toHaveBeenCalledOnce()
})
