import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ComicVineMappingHealth } from '../types/comic-vine'
import { MappingHealthSummary, MappingStatusBadge, MappingStatusIndicator } from '../components/MappingStatus'

const fullyMapped: ComicVineMappingHealth = {
  status: 'fully_mapped',
  tracked_issue_count: 6,
  confirmed_issue_count: 6,
  needs_mapping_count: 0,
  needs_review_count: 0,
}

const partial: ComicVineMappingHealth = {
  status: 'partial',
  tracked_issue_count: 3,
  confirmed_issue_count: 1,
  needs_mapping_count: 2,
  needs_review_count: 0,
}

const needsReview: ComicVineMappingHealth = {
  status: 'needs_review',
  tracked_issue_count: 6,
  confirmed_issue_count: 3,
  needs_mapping_count: 2,
  needs_review_count: 1,
}

describe('MappingStatusBadge', () => {
  it('renders nothing without mapping data', () => {
    const { container } = render(<MappingStatusBadge mapping={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows a fully mapped series', () => {
    render(<MappingStatusBadge mapping={fullyMapped} />)
    expect(screen.getByText('Fully mapped')).toBeVisible()
  })

  it('shows details when requested', () => {
    render(<MappingStatusBadge mapping={partial} showDetails />)
    expect(screen.getByText('Partially mapped')).toBeVisible()
    expect(screen.getByText('(1/3 mapped)')).toBeVisible()
  })
})

describe('MappingStatusIndicator', () => {
  it('renders nothing for null status', () => {
    const { container } = render(<MappingStatusIndicator status={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the count when positive', () => {
    render(<MappingStatusIndicator status="unresolved" count={2} />)
    expect(screen.getByText('Needs mapping')).toBeVisible()
    expect(screen.getByText('(2)')).toBeVisible()
  })

  it('hides a zero count', () => {
    render(<MappingStatusIndicator status="partial" count={0} />)
    expect(screen.queryByText('(0)')).not.toBeInTheDocument()
  })
})

describe('MappingHealthSummary', () => {
  it('renders nothing without mapping', () => {
    const { container } = render(<MappingHealthSummary mapping={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('reports needs-mapping and needs-review counts', () => {
    render(<MappingHealthSummary mapping={needsReview} />)
    expect(screen.getByText('2 need mapping')).toBeVisible()
    expect(screen.getByText('1 need review')).toBeVisible()
    expect(screen.getByText('3 mapped')).toBeVisible()
  })

  it('stays quiet for fully mapped series', () => {
    render(<MappingHealthSummary mapping={fullyMapped} />)
    expect(screen.queryByText(/need mapping/)).not.toBeInTheDocument()
    expect(screen.getByText('6 mapped')).toBeVisible()
  })
})
