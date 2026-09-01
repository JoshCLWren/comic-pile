import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PlanReadinessPanel from '../components/PlanReadinessPanel'

describe('PlanReadinessPanel', () => {
  it('renders no standalone live readiness surface', () => {
    const { container } = render(<PlanReadinessPanel planId={7} refreshKey={2} />)
    expect(container).toBeEmptyDOMElement()
  })
})
