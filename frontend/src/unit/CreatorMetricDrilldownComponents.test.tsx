import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { CalculationDisplay } from '../components/CalculationDisplay'
import { DrilldownIssueList } from '../components/DrilldownIssueList'
import { ExclusionExplanation } from '../components/ExclusionExplanation'
import type { CreatorMetricCalculation, CreatorMetricIssue } from '../types/index'

function makeCalculation(overrides?: Partial<CreatorMetricCalculation>): CreatorMetricCalculation {
  return {
    formula: '9.0 total rating points ÷ 2 rated issues = 4.50★',
    numerator: '9.0 total rating points',
    denominator: '2 rated issues',
    percentage: '4.50★',
    ...overrides,
  }
}

function makeIssue(overrides?: Partial<CreatorMetricIssue>): CreatorMetricIssue {
  return {
    issue_id: 11,
    thread_id: 7,
    thread_title: 'Writer Book',
    issue_number: '1',
    status: 'read',
    effective_rating: 4.5,
    effective_rating_source: null,
    effective_rating_timestamp: null,
    creator_roles: ['writer'],
    exclusion_reason: null,
    ...overrides,
  }
}

describe('CalculationDisplay', () => {
  it('renders the formula with numerator, denominator, and result', () => {
    render(<CalculationDisplay calculation={makeCalculation()} />)

    expect(screen.getByText('Calculation')).toBeInTheDocument()
    expect(
      screen.getByText('9.0 total rating points ÷ 2 rated issues = 4.50★'),
    ).toBeInTheDocument()
    expect(screen.getByText('Numerator')).toBeInTheDocument()
    expect(screen.getByText('Denominator')).toBeInTheDocument()
    expect(screen.getByText('Result')).toBeInTheDocument()
    expect(screen.getByText('4.50★')).toBeInTheDocument()
  })

  it('renders each formula line when the formula spans lines', () => {
    render(
      <CalculationDisplay
        calculation={makeCalculation({
          formula: '2 rated issues sorted by rating\nmiddle value (#1) = 4.0★',
        })}
      />,
    )

    expect(screen.getByText('2 rated issues sorted by rating')).toBeInTheDocument()
    expect(screen.getByText('middle value (#1) = 4.0★')).toBeInTheDocument()
  })

  it('omits denominator and result sections when they are absent', () => {
    render(
      <CalculationDisplay
        calculation={makeCalculation({ denominator: null, percentage: null })}
      />,
    )

    expect(screen.queryByText('Denominator')).not.toBeInTheDocument()
    expect(screen.queryByText('Result')).not.toBeInTheDocument()
    expect(screen.getByText('Numerator')).toBeInTheDocument()
  })
})

describe('DrilldownIssueList', () => {
  it('explains an empty metric instead of rendering rows', () => {
    render(
      <MemoryRouter>
        <DrilldownIssueList issues={[]} />
      </MemoryRouter>,
    )

    expect(screen.getByText('No issues found for this metric.')).toBeInTheDocument()
  })

  it('links each issue to its thread with rating and role context', () => {
    render(
      <MemoryRouter>
        <DrilldownIssueList
          issues={[
            makeIssue(),
            makeIssue({
              issue_id: 12,
              issue_number: '2',
              status: 'unread',
              effective_rating: null,
              creator_roles: [],
              exclusion_reason: 'No stored effective rating',
            }),
          ]}
        />
      </MemoryRouter>,
    )

    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(2)
    expect(links[0].getAttribute('href')).toBe('/thread/7')
    expect(screen.getByText('4.5★')).toBeInTheDocument()
    expect(screen.getByText('writer')).toBeInTheDocument()
    expect(screen.getByText('Read')).toBeInTheDocument()
    expect(screen.getByText('Unread')).toBeInTheDocument()
    expect(screen.getByText('No stored effective rating')).toBeInTheDocument()
  })
})

describe('ExclusionExplanation', () => {
  it('renders nothing when every issue is included', () => {
    const { container } = render(<ExclusionExplanation excludedIssues={[]} totalExcluded={0} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('groups excluded issues by reason and reveals them on toggle', () => {
    render(
      <ExclusionExplanation
        excludedIssues={[
          makeIssue({ issue_id: 12, exclusion_reason: 'No stored effective rating' }),
          makeIssue({ issue_id: 13, exclusion_reason: 'No stored effective rating' }),
          makeIssue({
            issue_id: 14,
            exclusion_reason: 'Creator only credited in a non-headline role',
          }),
        ]}
        totalExcluded={3}
      />,
    )

    expect(screen.getByText('3 not included')).toBeInTheDocument()
    expect(screen.getByText('No stored effective rating')).toBeInTheDocument()
    expect(
      screen.getByText('Creator only credited in a non-headline role'),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Show excluded issues' }))
    expect(screen.getByRole('button', { name: 'Hide excluded issues' })).toBeInTheDocument()
  })
})
