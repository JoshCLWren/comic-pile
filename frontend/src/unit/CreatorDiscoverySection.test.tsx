import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import CreatorDiscoverySection from '../components/CreatorDiscoverySection'
import type {
  CreatorDiscoveryEntry,
  CreatorDiscoveryResponse,
  CreatorDiscoveryView,
} from '../types/index'

function makeEntry(overrides: Partial<CreatorDiscoveryEntry> = {}): CreatorDiscoveryEntry {
  return {
    canonical_creator_key: 'creator:100',
    display_name: 'Brian K. Vaughan',
    normalized_roles: ['writer'],
    rated_issue_count: 3,
    average_rating: 5.0,
    median_rating: 5.0,
    rating_stddev: 0.0,
    rating_spread: 0.0,
    min_rating: 5.0,
    max_rating: 5.0,
    top_rating_rate: 1.0,
    top_rating_count: 3,
    unread_issue_count: 0,
    read_unrated_issue_count: 0,
    trend_direction: null,
    earlier_average_rating: null,
    recent_average_rating: null,
    trend_delta: null,
    trend_sample_count: 0,
    reasons: [
      {
        metric: 'average_rating',
        label: 'average rating',
        value: 5.0,
        threshold: 4.0,
        comparison: 'gte',
      },
      {
        metric: 'rating_stddev',
        label: 'rating standard deviation',
        value: 0.0,
        threshold: 0.5,
        comparison: 'lte',
      },
    ],
    ...overrides,
  }
}

function makeView(overrides: Partial<CreatorDiscoveryView> = {}): CreatorDiscoveryView {
  return {
    mode: 'consistently_loved',
    title: 'Most consistently loved',
    description: 'High personal average on a meaningful sample.',
    min_sample: 3,
    total: 1,
    truncated: false,
    max_entries: 10,
    entries: [makeEntry()],
    ...overrides,
  }
}

function makeResponse(overrides: Partial<CreatorDiscoveryResponse> = {}): CreatorDiscoveryResponse {
  return {
    views: [
      makeView(),
      makeView({
        mode: 'polarizing',
        title: 'Most polarizing',
        description: 'Wide rating spread on a meaningful sample.',
        entries: [],
      }),
    ],
    coverage: {
      rated_issues_total: 3,
      rated_issues_with_creator_metadata: 3,
      ratings_complete: true,
    },
    minimum_reliable_sample: 3,
    max_entries_per_view: 10,
    ...overrides,
  }
}

function renderSection(data: CreatorDiscoveryResponse) {
  return render(
    <MemoryRouter initialEntries={['/creators']}>
      <Routes>
        <Route path="*" element={<CreatorDiscoverySection data={data} />} />
        <Route path="/creators/:creatorKey" element={<div>creator detail</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CreatorDiscoverySection', () => {
  it('renders one tab per view and selects the first by default', () => {
    renderSection(makeResponse())

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Most consistently loved',
      'Most polarizing',
    ])
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tabpanel')).toHaveAccessibleName('Most consistently loved')
  })

  it('explains each creator with its supporting metrics and qualifying rules', () => {
    renderSection(makeResponse())

    expect(screen.getByRole('link', { name: 'Brian K. Vaughan' })).toHaveAttribute(
      'href',
      '/creators/creator%3A100',
    )
    expect(screen.getByText('3 rated issues')).toBeInTheDocument()
    expect(screen.getByText('5.0★')).toBeInTheDocument()
    expect(screen.getByText('average rating 5 ≥ 4')).toBeInTheDocument()
    expect(screen.getByText('rating standard deviation 0 ≤ 0.5')).toBeInTheDocument()
  })

  it('switches the panel when another discovery category is selected', () => {
    renderSection(makeResponse())

    fireEvent.click(screen.getByRole('tab', { name: 'Most polarizing' }))

    expect(screen.getByRole('tabpanel')).toHaveAccessibleName('Most polarizing')
    expect(screen.getByText(/No creators match this view yet/i)).toBeInTheDocument()
    expect(screen.queryByText('Brian K. Vaughan')).not.toBeInTheDocument()
  })

  it('names the minimum sample before a view ranks creators', () => {
    renderSection(makeResponse())

    expect(screen.getByText(/Ranked only from creators with at least 3 rated issues/i)).toBeInTheDocument()
  })

  it('describes a warmed or cooled trend with the halves that produced it', () => {
    const trend = makeResponse({
      views: [
        makeView({
          mode: 'moved_over_time',
          title: 'Warmed to / cooled on',
          description: 'Dated ratings that shifted over time.',
          min_sample: 6,
          entries: [
            makeEntry({
              canonical_creator_key: 'creator:200',
              display_name: 'Warming Writer',
              trend_direction: 'warmed',
              earlier_average_rating: 2.0,
              recent_average_rating: 5.0,
              trend_delta: 3.0,
              trend_sample_count: 6,
              reasons: [
                {
                  metric: 'trend_delta',
                  label: 'change in average',
                  value: 3.0,
                  threshold: 0.5,
                  comparison: 'gte',
                },
              ],
            }),
          ],
        }),
      ],
    })
    renderSection(trend)

    const trendSummary = screen.getByLabelText(/Warmed to Warming Writer/)
    expect(trendSummary).toHaveTextContent('+3★')
    expect(trendSummary).toHaveTextContent('(2.0 → 5.0)')
  })

  it('reports truncation and partial metadata as honest lower bounds', () => {
    const data = makeResponse({
      views: [
        makeView({ total: 25, truncated: true, entries: [makeEntry()] }),
        makeView({ mode: 'polarizing', title: 'Most polarizing', entries: [] }),
      ],
      coverage: {
        rated_issues_total: 9,
        rated_issues_with_creator_metadata: 7,
        ratings_complete: false,
      },
    })
    renderSection(data)

    expect(screen.getByText('Showing the top 1 of 25 qualifying creators.')).toBeInTheDocument()
    expect(screen.getByText(/Partial results: some rated issues are still missing/i)).toHaveTextContent(
      /lower bounds/i,
    )
    expect(screen.getByText(/not causes or statistically significant effects/i)).toBeInTheDocument()
  })

  it('navigates a discovery result to the canonical creator detail page', () => {
    renderSection(makeResponse())

    fireEvent.click(screen.getByRole('link', { name: 'Brian K. Vaughan' }))

    expect(screen.getByText('creator detail')).toBeInTheDocument()
  })
})
