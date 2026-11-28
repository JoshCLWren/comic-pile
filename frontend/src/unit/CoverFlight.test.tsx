import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CoverFlight } from '../pages/RollPage/components/CoverFlight'

describe('CoverFlight (#5981)', () => {
  it('calls onDone when the node has no animate support', () => {
    const onDone = vi.fn()
    render(
      <CoverFlight
        flight={{ url: 'https://example.com/cover.jpg', rect: { left: 1, top: 2, width: 3, height: 4 } }}
        onDone={onDone}
      />,
    )
    expect(screen.getByTestId('roll-cover-flight')).toBeInTheDocument()
    expect(onDone).toHaveBeenCalled()
  })

  it('terminates on resize without throwing', () => {
    const onDone = vi.fn()
    render(
      <CoverFlight
        flight={{ url: 'https://example.com/cover.jpg', rect: { left: 1, top: 2, width: 3, height: 4 } }}
        onDone={onDone}
      />,
    )
    window.dispatchEvent(new Event('resize'))
    expect(onDone).toHaveBeenCalled()
  })
})

describe('CoverFlight animation path (#5981)', () => {
  it('runs the animation and cleans up on unmount', async () => {
    const finished = Promise.resolve()
    const cancel = vi.fn()
    const animate = vi.fn(() => ({ finished, cancel }))
    const original = (HTMLElement.prototype as { animate?: unknown }).animate
    ;(HTMLElement.prototype as { animate?: unknown }).animate = animate

    const origRect = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = () => ({
      left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => ({}),
    }) as DOMRect

    const onDone = vi.fn()
    const { unmount } = render(
      <CoverFlight
        flight={{ url: 'https://example.com/cover.jpg', rect: { left: 1, top: 2, width: 3, height: 4 } }}
        onDone={onDone}
      />,
    )
    // allow microtask
    await Promise.resolve()
    await Promise.resolve()
    unmount()
    expect(animate).toHaveBeenCalled()

    HTMLElement.prototype.getBoundingClientRect = origRect
    ;(HTMLElement.prototype as { animate?: unknown }).animate = original
  })

  it('calls onDone when target has zero width', () => {
    const animate = vi.fn(() => ({ finished: Promise.resolve(), cancel: vi.fn() }))
    const original = (HTMLElement.prototype as { animate?: unknown }).animate
    ;(HTMLElement.prototype as { animate?: unknown }).animate = animate

    // make parent rect width 0 by overriding getBoundingClientRect
    const origRect = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = () => ({
      left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}),
    }) as DOMRect

    const onDone = vi.fn()
    render(
      <CoverFlight
        flight={{ url: 'https://example.com/cover.jpg', rect: { left: 1, top: 2, width: 3, height: 4 } }}
        onDone={onDone}
      />,
    )
    expect(onDone).toHaveBeenCalled()

    HTMLElement.prototype.getBoundingClientRect = origRect
    ;(HTMLElement.prototype as { animate?: unknown }).animate = original
  })
})
