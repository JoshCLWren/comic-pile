import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ContinuityReadinessSummary } from '../pages/RollPage/components/ContinuityReadinessSummary'

describe('ContinuityReadinessSummary', () => {
  it('renders no second readiness gate for a Roll-selected issue', () => {
    const { container } = render(<ContinuityReadinessSummary issueId={42} />)
    expect(container).toBeEmptyDOMElement()
  })
})
