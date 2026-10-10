import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import QueueMappingHealthIndicator from './QueueMappingHealthIndicator'

describe('QueueMappingHealthIndicator', () => {
  it('is quiet for fully_mapped', () => {
    const { container } = render(
      <QueueMappingHealthIndicator
        mapping={{ status: 'fully_mapped', tracked_issue_count: 5, confirmed_issue_count: 5, needs_mapping_count: 0, needs_review_count: 0 }}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('is quiet for not_applicable', () => {
    const { container } = render(
      <QueueMappingHealthIndicator
        mapping={{ status: 'not_applicable', tracked_issue_count: 0, confirmed_issue_count: 0, needs_mapping_count: 0, needs_review_count: 0 }}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows unresolved count and Map series button', () => {
    render(
      <QueueMappingHealthIndicator
        mapping={{ status: 'unresolved', tracked_issue_count: 4, confirmed_issue_count: 0, needs_mapping_count: 4, needs_review_count: 0 }}
        onMapSeries={vi.fn()}
      />,
    )
    expect(screen.getByText('4 issues need mapping')).toBeInTheDocument()
    expect(screen.getByTestId('queue-map-series-btn')).toBeInTheDocument()
  })

  it('shows partial count without button when callback omitted', () => {
    render(
      <QueueMappingHealthIndicator
        mapping={{ status: 'partial', tracked_issue_count: 10, confirmed_issue_count: 3, needs_mapping_count: 7, needs_review_count: 0 }}
      />,
    )
    expect(screen.getByText('3 of 10 mapped')).toBeInTheDocument()
    expect(screen.queryByTestId('queue-map-series-btn')).toBeNull()
  })

  it('distinguishes needs_review with review text', () => {
    render(
      <QueueMappingHealthIndicator
        mapping={{ status: 'needs_review', tracked_issue_count: 2, confirmed_issue_count: 1, needs_mapping_count: 0, needs_review_count: 1 }}
        onMapSeries={vi.fn()}
      />,
    )
    expect(screen.getByText('1 issue needs review')).toBeInTheDocument()
  })

  it('calls onMapSeries when button clicked', () => {
    const onMapSeries = vi.fn()
    render(
      <QueueMappingHealthIndicator
        mapping={{ status: 'unresolved', tracked_issue_count: 1, confirmed_issue_count: 0, needs_mapping_count: 1, needs_review_count: 0 }}
        onMapSeries={onMapSeries}
      />,
    )
    screen.getByTestId('queue-map-series-btn').click()
    expect(onMapSeries).toHaveBeenCalledTimes(1)
  })
})
