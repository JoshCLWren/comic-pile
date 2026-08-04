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

it('fills a stretched grid row and strictly clips swipe actions behind the card', () => {
  const { wrapper, slidingCard } = renderSwipeable()

  expect(wrapper).toHaveClass('overflow-hidden')
  expect(slidingCard).toHaveClass('h-full')
  expect(slidingCard.style.touchAction).toBe('pan-y')
})

it('does not reveal actions on vertical scroll when direction resolves to vertical', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 205, y: 200 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 205, y: 200 }))
  })

  expect(slidingCard.style.transform).toBe('translateX(0px)')
})

it('does not reveal actions when both axes are within the larger intent threshold', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 218, y: 118 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 218, y: 118 }))
  })

  expect(slidingCard.style.transform).toBe('translateX(0px)')
})

it('locks diagonal mobile scrolling vertically unless horizontal movement is dominant', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  // A common diagonal scroll gesture exceeds the threshold on both axes, but
  // horizontal movement is not 1.5x the vertical movement.
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 165, y: 130 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 120, y: 180 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 120, y: 180 }))
  })

  expect(slidingCard.style.transform).toBe('translateX(0px)')
})

it('reveals actions only after deliberate horizontal intent passes the swipe threshold', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  // Swipe left 150px with minimal vertical drift: horizontal intent is clear
  // and the movement passes SWIPE_THRESHOLD(64).
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 50, y: 105 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 50, y: 105 }))
  })

  expect(slidingCard.style.transform).toBe('translateX(-192px)')
})

it('snaps closed when deliberate horizontal swipe is released before SWIPE_THRESHOLD', () => {
  const { slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchmove', { x: 170, y: 105 }))
  })
  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchend', { x: 170, y: 105 }))
  })

  expect(slidingCard.style.transform).toBe('translateX(0px)')
})

it('fires onCardClick when card is tapped without swiping', () => {
  const { onCardClick, slidingCard } = renderSwipeable()

  act(() => {
    slidingCard.dispatchEvent(createTouchEvent('touchstart', { x: 200, y: 100 }))
  })
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
