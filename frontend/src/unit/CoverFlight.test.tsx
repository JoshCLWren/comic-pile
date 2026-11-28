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
