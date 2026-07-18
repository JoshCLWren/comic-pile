import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import PositionSlider from '../components/PositionSlider'

const threads = [
  { id: 1, title: 'A very long title that should be truncated here', queue_position: 3 },
  { id: 2, title: 'Middle', queue_position: 1 },
  { id: 3, title: 'Bottom', queue_position: 2 },
]

it('sorts threads, shows the current state, and cancels', () => {
  const onCancel = vi.fn()
  render(<PositionSlider threads={threads} currentThread={threads[0]} onPositionSelect={vi.fn()} onCancel={onCancel} />)
  expect(screen.getByText('Current position (no change)')).toBeInTheDocument()
  fireEvent.click(screen.getByTestId('position-slider-cancel'))
  expect(onCancel).toHaveBeenCalled()
})

it('reports front, middle and back destinations and confirms', () => {
  const onPositionSelect = vi.fn()
  render(<PositionSlider threads={threads} currentThread={threads[2]} onPositionSelect={onPositionSelect} onCancel={vi.fn()} />)
  const slider = screen.getByRole('slider')
  fireEvent.change(slider, { target: { value: '0' } })
  expect(screen.getByText('Move to front of queue')).toBeInTheDocument()
  fireEvent.click(screen.getByTestId('position-slider-confirm'))
  expect(onPositionSelect).toHaveBeenCalledWith(1)
  fireEvent.change(slider, { target: { value: '2' } })
  expect(screen.getByText('Move to back of queue')).toBeInTheDocument()
})
