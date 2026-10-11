import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { CreatorMetricDrilldownModal } from '../components/CreatorMetricDrilldownModal'
import { queryKeys } from '../query/queryKeys'
import type { CreatorMetricDrilldown } from '../types/index'

const DRILLDOWN: CreatorMetricDrilldown = {
  metric_type: 'average-rating',
  creator_key: 'creator:1',
  calculation: {
    formula: '9.0 total rating points ÷ 2 rated issues = 4.50★',
    numerator: '9.0 total rating points',
    denominator: '2 rated issues',
    percentage: '4.50★',
  },
  total_count: 2,
  included_issues: [
    {
      issue_id: 11,
      thread_id: 7,
      thread_title: 'Writer Book',
      issue_number: '1',
      status: 'read',
      effective_rating: 4.0,
      effective_rating_source: null,
      effective_rating_timestamp: null,
      creator_roles: ['writer'],
      exclusion_reason: null,
    },
  ],
  excluded_issues: [
    {
      issue_id: 12,
      thread_id: 7,
      thread_title: 'Writer Book',
      issue_number: '2',
      status: 'read',
      effective_rating: null,
      effective_rating_source: null,
      effective_rating_timestamp: null,
      creator_roles: ['writer'],
      exclusion_reason: 'No stored effective rating',
    },
  ],
  pagination: { page: 1, page_size: 50, next_page_token: null, total_pages: 1 },
}

function renderModal(drilldown: CreatorMetricDrilldown | undefined) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (drilldown) {
    queryClient.setQueryData(
      queryKeys.creators.metric('creator:1', 'average-rating', {}),
      drilldown,
    )
  }
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <CreatorMetricDrilldownModal
          isOpen
          onClose={vi.fn()}
          creatorKey="creator:1"
          metricType="average-rating"
          metricLabel="Average rating"
        />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('CreatorMetricDrilldownModal', () => {
  it('renders the calculation with supporting and excluded issues', () => {
    renderModal(DRILLDOWN)

    expect(screen.getByText('Average rating Details')).toBeInTheDocument()
    expect(
      screen.getByText('9.0 total rating points ÷ 2 rated issues = 4.50★'),
    ).toBeInTheDocument()
    expect(screen.getByText('Supporting Issues')).toBeInTheDocument()
    expect(screen.getByText('1 of 2 shown')).toBeInTheDocument()
    expect(screen.getByText('1 not included')).toBeInTheDocument()
  })

  it('shows a loading state while the drilldown is not cached', () => {
    renderModal(undefined)

    expect(screen.getByText('Loading Average rating...')).toBeInTheDocument()
  })

  it('hides pagination controls for a single page of evidence', () => {
    renderModal(DRILLDOWN)

    expect(screen.queryByText('Previous')).not.toBeInTheDocument()
    expect(screen.queryByText('Next')).not.toBeInTheDocument()
  })
})
