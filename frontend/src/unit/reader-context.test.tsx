import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ReaderContextResponse } from '../services/api-reader-context'
import { SeriesPanel } from '../pages/RollPage/components/SeriesPanel'
import { CrossoverAnalytics } from '../pages/RollPage/components/CrossoverAnalytics'

const unavailableSeries = {
  identity_source: 'unavailable' as const,
  canonical_series_id: null,
  series_name: null,
  average_rating: null,
  ratings_count: 0,
  previous_issue: null,
  recent_ratings: [],
  highest_rating: null,
  lowest_rating: null,
}

const thanosSeries = {
  identity_source: 'comicvine' as const,
  canonical_series_id: '20764',
  series_name: 'Thanos',
  average_rating: 3.71,
  ratings_count: 7,
  previous_issue: { issue_id: 23425, issue_number: '9', rating: 3.5 },
  recent_ratings: [
    { issue_id: 23426, issue_number: '10', rating: 4.0 },
    { issue_id: 23427, issue_number: '11', rating: 3.0 },
  ],
  highest_rating: 4.5,
  lowest_rating: 3.0,
}

describe('SeriesPanel', () => {
  it('renders unavailable state with honest message', () => {
    render(<SeriesPanel series={unavailableSeries} />)
    expect(screen.getByText('Canonical series history unavailable')).toBeInTheDocument()
    expect(screen.getByText('Series history')).toBeInTheDocument()
  })

  it('renders average rating with contributing count', () => {
    render(<SeriesPanel series={thanosSeries} />)
    expect(screen.getByText('3.71')).toBeInTheDocument()
    expect(screen.getByText('7 rated')).toBeInTheDocument()
    expect(screen.getByText('Thanos history')).toBeInTheDocument()
  })

  it('renders previous issue with rating', () => {
    render(<SeriesPanel series={thanosSeries} />)
    expect(screen.getByText('Previous:')).toBeInTheDocument()
    expect(screen.getByText('#9')).toBeInTheDocument()
  })

  it('renders recent ratings', () => {
    render(<SeriesPanel series={thanosSeries} />)
    expect(screen.getByText('Recent ratings')).toBeInTheDocument()
    expect(screen.getByText('#10')).toBeInTheDocument()
    expect(screen.getByText('#11')).toBeInTheDocument()
  })

  it('renders highest and lowest ratings', () => {
    render(<SeriesPanel series={thanosSeries} />)
    expect(screen.getByText('High:')).toBeInTheDocument()
    expect(screen.getByText('4.5')).toBeInTheDocument()
    expect(screen.getByText('Low:')).toBeInTheDocument()
    expect(screen.getByText('3.0')).toBeInTheDocument()
  })

  it('shows no-ratings message when average is null but identity is available', () => {
    const emptySeries = { ...thanosSeries, average_rating: null, ratings_count: 0 }
    render(<SeriesPanel series={emptySeries} />)
    expect(screen.getByText('No ratings yet')).toBeInTheDocument()
  })

  it('renders series name from identity when available', () => {
    const unnamed = { ...thanosSeries, series_name: null }
    render(<SeriesPanel series={unnamed} />)
    expect(screen.getByText('Series history')).toBeInTheDocument()
  })

  it('does not render recent ratings when empty', () => {
    const noRecent = { ...thanosSeries, recent_ratings: [] }
    render(<SeriesPanel series={noRecent} />)
    expect(screen.queryByText('Recent ratings')).not.toBeInTheDocument()
  })

  it('does not render high/low when both are null', () => {
    const noHL = { ...thanosSeries, highest_rating: null, lowest_rating: null }
    render(<SeriesPanel series={noHL} />)
    expect(screen.queryByText('High:')).not.toBeInTheDocument()
    expect(screen.queryByText('Low:')).not.toBeInTheDocument()
  })

  it('does not render previous issue when null', () => {
    const noPrev = { ...thanosSeries, previous_issue: null }
    render(<SeriesPanel series={noPrev} />)
    expect(screen.queryByText('Previous:')).not.toBeInTheDocument()
  })

  it('renders previous issue without rating when null', () => {
    const prevNoRating = {
      ...thanosSeries,
      previous_issue: { issue_id: 23425, issue_number: '9', rating: null },
    }
    render(<SeriesPanel series={prevNoRating} />)
    expect(screen.getByText('#9')).toBeInTheDocument()
  })

  it('has proper aria-labelledby on section', () => {
    render(<SeriesPanel series={thanosSeries} />)
    const section = screen.getByRole('region', { name: /Thanos history/i })
    expect(section).toBeInTheDocument()
  })

  it('has proper aria-labelledby on unavailable section', () => {
    render(<SeriesPanel series={unavailableSeries} />)
    const section = screen.getByRole('region', { name: /Series history/i })
    expect(section).toBeInTheDocument()
  })
})

describe('CrossoverAnalytics', () => {
  const applicableCrossover = {
    id: 3,
    name: 'Annihilation',
    applies_to_current_issue: true,
    membership_kind: 'issue',
    next_member: null,
    average_rating: 4.2,
    ratings_count: 5,
    read_count: 8,
  }

  const futureCrossover = {
    id: 4,
    name: 'Infinity Gauntlet',
    applies_to_current_issue: false,
    membership_kind: 'issue',
    next_member: { issue_id: 23430, issue_number: '15' },
    average_rating: 3.8,
    ratings_count: 3,
    read_count: 4,
  }

  it('renders nothing when no crossovers apply', () => {
    const { container } = render(
      <CrossoverAnalytics crossovers={[futureCrossover]} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing for empty array', () => {
    const { container } = render(<CrossoverAnalytics crossovers={[]} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders applicable crossover with stats', () => {
    render(<CrossoverAnalytics crossovers={[applicableCrossover]} />)
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
    expect(screen.getByText('4.20')).toBeInTheDocument()
    expect(screen.getByText('5 rated')).toBeInTheDocument()
    expect(screen.getByText('8 read')).toBeInTheDocument()
  })

  it('filters out non-applicable crossovers', () => {
    render(
      <CrossoverAnalytics
        crossovers={[futureCrossover, applicableCrossover]}
      />,
    )
    expect(screen.queryByText('Infinity Gauntlet')).not.toBeInTheDocument()
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
  })

  it('renders multiple applicable crossovers', () => {
    const second = { ...applicableCrossover, id: 5, name: 'Secret Invasion', ratings_count: 2, read_count: 3, average_rating: 3.5 }
    render(<CrossoverAnalytics crossovers={[applicableCrossover, second]} />)
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
    expect(screen.getByText('Secret Invasion')).toBeInTheDocument()
  })

  it('hides rated count when zero', () => {
    const zeroRated = { ...applicableCrossover, ratings_count: 0, average_rating: null }
    render(<CrossoverAnalytics crossovers={[zeroRated]} />)
    expect(screen.getByText('8 read')).toBeInTheDocument()
    expect(screen.queryByText('0 rated')).not.toBeInTheDocument()
  })

  it('hides read count when zero', () => {
    const zeroRead = { ...applicableCrossover, read_count: 0, ratings_count: 2 }
    render(<CrossoverAnalytics crossovers={[zeroRead]} />)
    expect(screen.getByText('2 rated')).toBeInTheDocument()
    expect(screen.queryByText('0 read')).not.toBeInTheDocument()
  })

  it('hides average when null but shows counts', () => {
    const nullAvg = { ...applicableCrossover, average_rating: null }
    render(<CrossoverAnalytics crossovers={[nullAvg]} />)
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
    expect(screen.getByText('5 rated')).toBeInTheDocument()
    expect(screen.getByText('8 read')).toBeInTheDocument()
  })

  it('does not render crossover with applies_to_current_issue true but all stats zero', () => {
    const emptyStats = {
      ...applicableCrossover,
      ratings_count: 0,
      read_count: 0,
      average_rating: null,
    }
    const { container } = render(
      <CrossoverAnalytics crossovers={[emptyStats]} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('has proper aria-labelledby on section', () => {
    render(<CrossoverAnalytics crossovers={[applicableCrossover]} />)
    const section = screen.getByRole('region', { name: /Crossovers/i })
    expect(section).toBeInTheDocument()
  })
})
