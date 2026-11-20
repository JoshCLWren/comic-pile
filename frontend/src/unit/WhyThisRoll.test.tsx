import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { WhyThisRoll } from '../pages/RollPage/components/WhyThisRoll'

describe('WhyThisRoll', () => {
  it('renders nothing when there is no explanation (e.g. explicit override)', () => {
    const { container } = render(<WhyThisRoll explanation={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('is collapsed by default and expands on click for a weighted (momentum) roll', () => {
    render(<WhyThisRoll explanation="Weighted by your recent reading momentum" />)

    const toggle = screen.getByRole('button', { name: /why this/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('region', { name: /why this roll/i })).toBeNull()

    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(
      screen.getByRole('region', { name: /why this roll/i }),
    ).toHaveTextContent('Weighted by your recent reading momentum')
  })

  it('explains a pure random selection after expansion', () => {
    render(<WhyThisRoll explanation="Pure random selection" />)

    fireEvent.click(screen.getByRole('button', { name: /why this/i }))

    expect(screen.getByRole('region', { name: /why this roll/i })).toHaveTextContent(
      'Pure random selection',
    )
  })
})
