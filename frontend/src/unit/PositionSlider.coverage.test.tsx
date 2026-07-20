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

it('describes before, between, after, and fallback positions', () => {
  const current = { id: 2, title: 'Middle', queue_position: 2 }
  const list = [
    { id: 1, title: 'A very long title that should be truncated here', queue_position: 1 },
    current,
    { id: 3, title: 'Bottom', queue_position: 3 },
    { id: 4, title: 'Fourth', queue_position: 4 },
  ]
  const { unmount } = render(<PositionSlider threads={list} currentThread={current} onPositionSelect={vi.fn()} onCancel={vi.fn()} />)
  const slider = screen.getByRole('slider')
  fireEvent.change(slider, { target: { value: '2' } })
  expect(screen.getByText(/Before/)).toBeInTheDocument()
  unmount()
  const last = list[3]!
  render(<PositionSlider threads={list} currentThread={last} onPositionSelect={vi.fn()} onCancel={vi.fn()} />)
  const secondSlider = screen.getByRole('slider')
  fireEvent.change(secondSlider, { target: { value: '1' } })
  expect(screen.getByText(/Between/)).toBeInTheDocument()

})

it('handles a current thread absent from the list and a single-position queue', () => {
  render(<PositionSlider threads={[threads[0]!]} currentThread={{ id: 99, title: 'Missing', queue_position: 9 }} onPositionSelect={vi.fn()} onCancel={vi.fn()} />)
  expect(screen.getByRole('slider')).toHaveAttribute('aria-valuemax', '0')
  expect(screen.getByRole('slider')).toHaveAttribute('aria-valuenow', '0')
  expect(screen.getByText('Move to front of queue')).toBeInTheDocument()
})
