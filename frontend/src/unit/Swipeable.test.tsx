import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import Swipeable from '../components/Swipeable'

afterEach(() => vi.useRealTimers())

function renderSwipeable() {
  const onCardClick = vi.fn()
  const onAction = vi.fn()

  render(
    <Swipeable
      data-testid="swipeable-card"
      onCardClick={onCardClick}
      actions={[
        { icon: '📖', label: 'Read', onClick: onAction, color: 'bg-amber-600/30 text-amber-300' },
      ]}
    >
      <p>Card content</p>
    </Swipeable>,
  )

  const wrapper = screen.getByTestId('swipeable-card')
  // The sliding card div is the last child of the wrapper (after the action panel)
  const slidingCard = wrapper.lastElementChild as HTMLElement

  return { onCardClick, onAction, wrapper, slidingCard }
}

function createTouchEvent(type: string, options: { x: number; y: number }) {
  const event = new TouchEvent(type, { bubbles: true, cancelable: true })
  const touch = { clientX: options.x, clientY: options.y }

  // jsdom does not reliably set touches/changedTouches from the TouchEventInit
  // dictionary, so we define them directly on the instance.
  Object.defineProperty(event, 'touches', {
    value: type === 'touchend' ? [] : [touch],
    configurable: true,
  })
  Object.defineProperty(event, 'changedTouches', {
    value: [touch],
    configurable: true,
  })

  return event
}

it('does not reveal actions on vertical scroll when dx is locked by direction threshold', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  // Move vertically: dx=5 (< 12 threshold), dy=100 (large) → direction resolves to vertical
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 205, y: 200 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 205, y: 200 }))
  })

  // Card must remain closed
  expect(slidingCard.style.transform).toBe('translateX(0px)')
})

it('does not reveal actions when both axes are within direction-lock threshold (tiny jitter)', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  // Both dx and dy are < 12 → early return before direction is resolved
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 208, y: 108 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 208, y: 108 }))
  })

  expect(slidingCard.style.transform).toBe('translateX(0px)')
})

it('reveals actions on horizontal swipe past threshold', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  // Swipe left 150px: dx=-150, dy=5 → horizontal → past SWIPE_THRESHOLD(64)
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 50, y: 105 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 50, y: 105 }))
  })

  // Card should stay open at -ACTION_WIDTH
  expect(slidingCard.style.transform).toBe('translateX(-192px)')
})

it('snaps closed when horizontal swipe is released before SWIPE_THRESHOLD', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  // Swipe left only 30px: dx=-30, dy=5 → horizontal but < SWIPE_THRESHOLD(64)
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 170, y: 105 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 170, y: 105 }))
  })

  // Card should snap back closed
  expect(slidingCard.style.transform).toBe('translateX(0px)')
})

it('fires onCardClick when card is tapped without swiping', () => {
  const { onCardClick, slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  // Move within direction-lock threshold — acting as a tap
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 203, y: 103 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 203, y: 103 }))
  })
  act(() => {
    slidingCard.click()
  })

  expect(onCardClick).toHaveBeenCalledTimes(1)
})

it('closes an open card on click and clears the swipe timeout on repeated touch ends', async () => {
  vi.useFakeTimers()
  const { onCardClick, slidingCard } = renderSwipeable()
  await act(async () => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 50, y: 105 }))
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 50, y: 105 }))
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 50, y: 105 }))
  })
  await act(async () => { await Promise.resolve() })
  act(() => slidingCard.click())
  expect(slidingCard.style.transform).toBe('translateX(0px)')
  expect(onCardClick).not.toHaveBeenCalled()
  act(() => vi.advanceTimersByTime(50))
})
