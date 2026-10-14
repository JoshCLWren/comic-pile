import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TagSummaryChips } from '../components/Tags/TagSummaryChips'
import type { RollTagSummary } from '../types/rollBootstrap'

const PHYSICAL: RollTagSummary = { id: 11, name: 'Physical', color: '#ff0000', scope: 'global' }
const TRADE: RollTagSummary = {
  id: 12,
  name: 'Trade paperback',
  color: '#0000ff',
  scope: 'private',
}

describe('TagSummaryChips', () => {
  it('renders each visible tag name inside a labelled group', () => {
    render(<TagSummaryChips tags={[PHYSICAL, TRADE]} label="Tags for Spider-Man" />)

    const group = screen.getByRole('list', { name: 'Tags for Spider-Man' })
    expect(group).toBeInTheDocument()
    expect(screen.getByText('Physical')).toBeInTheDocument()
    expect(screen.getByText('Trade paperback')).toBeInTheDocument()
  })

  it('paints each chip with the tag identity color', () => {
    const { container } = render(<TagSummaryChips tags={[PHYSICAL]} label="Tags for Spider-Man" />)

    const dot = container.querySelector('span[aria-hidden="true"]')
    expect(dot).toHaveStyle({ backgroundColor: PHYSICAL.color })
  })

  it('renders nothing at all for an untagged series instead of an empty box', () => {
    const { container } = render(<TagSummaryChips tags={[]} label="Tags for Batman" />)

    expect(container).toBeEmptyDOMElement()
  })

  it('exposes no interactive control, because these rows are themselves click targets', () => {
    render(<TagSummaryChips tags={[PHYSICAL]} label="Tags for Spider-Man" />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})