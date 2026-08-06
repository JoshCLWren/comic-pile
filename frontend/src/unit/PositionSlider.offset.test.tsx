import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import PositionSlider from '../components/PositionSlider'

it('shows the full signed offset for multi-position moves', () => {
  const current = { id: 4, title: 'Fourth', queue_position: 4 }
  const threads = [
    { id: 1, title: 'First', queue_position: 1 },
    { id: 2, title: 'Second', queue_position: 2 },
    { id: 3, title: 'Third', queue_position: 3 },
    current,
    { id: 5, title: 'Fifth', queue_position: 5 },
  ]

  render(
    <PositionSlider
      threads={threads}
      currentThread={current}
      onPositionSelect={vi.fn()}
      onCancel={vi.fn()}
    />,
  )

  const slider = screen.getByRole('slider')
  fireEvent.change(slider, { target: { value: '0' } })
  expect(screen.getByTestId('position-slider-offset')).toHaveTextContent('+3')

  fireEvent.change(slider, { target: { value: '4' } })
  expect(screen.getByTestId('position-slider-offset')).toHaveTextContent('-1')
})
