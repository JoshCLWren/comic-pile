import { useState } from 'react'
import { fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollViewport } from '../pages/RollPage/useRollViewport'

function Harness({ navType = 'PUSH' }: { navType?: 'POP' | 'PUSH' | 'REPLACE' }) {
  const [isRatingView, setIsRatingView] = useState(false)
  const [pulse, setPulse] = useState(0)
  const { mainDieRef, ratingViewTopRef } = useRollViewport({ isRatingView, navType })
  return (
    <div>
      <div data-testid="die-anchor" ref={mainDieRef} />
      <div data-testid="rating-top-anchor" ref={ratingViewTopRef} />
      <button type="button" onClick={() => setIsRatingView((value) => !value)}>
        toggle rating
      </button>
      <button type="button" onClick={() => setPulse((value) => value + 1)}>
        pulse
      </button>
      <output data-testid="pulse">{pulse}</output>
    </div>
  )
}

describe('useRollViewport (issue #2286)', () => {
  let scrollIntoView: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    scrollIntoView = vi.spyOn(Element.prototype, 'scrollIntoView').mockClear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('anchors to the rating surface start when entering rating mode from a non-zero scroll offset', () => {
    // The reader previously scrolled the Roll page (retained offset) when the
    // roll completes; the anchor must move the viewport to the result start.
    const scrollY = vi.spyOn(window, 'scrollY', 'get').mockReturnValue(400)
    const { getByRole, getByTestId } = render(<Harness />)
    fireEvent.click(getByRole('button', { name: 'toggle rating' }))

    expect(scrollIntoView).toHaveBeenCalledTimes(1)
    expect(scrollIntoView.mock.instances[0]).toBe(getByTestId('rating-top-anchor'))
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })

    scrollY.mockRestore()
  })

  it('leaves the rating view by returning the viewport to the die', () => {
    const { getByRole, getByTestId } = render(<Harness />)
    fireEvent.click(getByRole('button', { name: 'toggle rating' }))
    scrollIntoView.mockClear()

    fireEvent.click(getByRole('button', { name: 'toggle rating' }))
    expect(scrollIntoView).toHaveBeenCalledTimes(1)
    expect(scrollIntoView.mock.instances[0]).toBe(getByTestId('die-anchor'))
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
  })

  it('re-anchors to the result start on every fresh entry, including re-entry after cancelling', () => {
    const { getByRole, getByTestId } = render(<Harness />)
    fireEvent.click(getByRole('button', { name: 'toggle rating' }))
    fireEvent.click(getByRole('button', { name: 'toggle rating' }))
    fireEvent.click(getByRole('button', { name: 'toggle rating' }))

    const ratingTopCalls = scrollIntoView.mock.instances.filter(
      (instance: Element) => instance === getByTestId('rating-top-anchor'),
    )
    expect(ratingTopCalls).toHaveLength(2)
  })

  it('does not override scroll restoration on POP back/forward or reload', () => {
    const { getByRole } = render(<Harness navType="POP" />)
    fireEvent.click(getByRole('button', { name: 'toggle rating' }))

    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('does not re-anchor when async reader-context data re-renders the rating view', () => {
    const { getByRole } = render(<Harness />)
    fireEvent.click(getByRole('button', { name: 'toggle rating' }))
    scrollIntoView.mockClear()

    fireEvent.click(getByRole('button', { name: 'pulse' }))
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('uses an instant anchor when the reader prefers reduced motion', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: true }) as unknown as MediaQueryList),
    )
    const { getByRole } = render(<Harness />)
    fireEvent.click(getByRole('button', { name: 'toggle rating' }))

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' })
  })

  it('keeps the full transition pairing when the die and rating targets are present', () => {
    const { container } = render(<Harness />)
    expect(container.querySelector('[data-testid="die-anchor"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="rating-top-anchor"]')).not.toBeNull()
  })
})