import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import CreatorTeamChemistrySection from '../components/CreatorTeamChemistrySection'
import type { CreatorTeamChemistryResponse, CreatorTeamPair } from '../types/index'

function makeMember(
  canonical_creator_key: string,
  display_name: string,
  overrides: Partial<{
    roles: string[]
    baseline_rated_count: number
    baseline_average_rating: number | null
    difference_from_baseline: number | null
  }> = {},
): CreatorTeamChemistryResponse['pairs'][number]['creators'][number] {
  return {
    canonical_creator_key,
    display_name,
    roles: ['writer'],
    baseline_rated_count: 6,
    baseline_average_rating: 3.5,
    difference_from_baseline: 0.5,
    ...overrides,
  }
}

function makePair(overrides: Partial<CreatorTeamPair> = {}): CreatorTeamPair {
  return {
    pair_key: 'creator:1|creator:2',
    creators: [makeMember('creator:1', 'Writer One'), makeMember('creator:2', 'Artist Two')],
    shared_rated_issue_count: 3,
    shared_average_rating: 4.33,
    shared_median_rating: 4.0,
    shared_rating_distribution: { '5': 1, '4': 1, '3': 1 },
    shared_series: [
      { thread_id: 11, thread_title: 'Team Run', shared_issue_count: 3 },
    ],
    shared_issue_refs: [
      {
        issue_id: 101,
        thread_id: 11,
        thread_title: 'Team Run',
        issue_number: '3',
        effective_rating: 5.0,
        status: 'read',
      },
    ],
    max_shared_issue_refs: 5,
    ...overrides,
  }
}

function makeResponse(overrides: Partial<CreatorTeamChemistryResponse> = {}): CreatorTeamChemistryResponse {
  return {
    pairs: [makePair()],
    pairs_total: 1,
    min_shared_team_sample: 3,
    max_ranked_pairs: 10,
    coverage: {
      rated_issues_total: 3,
      rated_issues_with_creator_metadata: 3,
      ratings_complete: true,
    },
    ...overrides,
  }
}

function renderSection(props: Parameters<typeof CreatorTeamChemistrySection>[0]) {
  return render(
    <MemoryRouter initialEntries={['/creators']}>
      <Routes>
        <Route path="*" element={<CreatorTeamChemistrySection {...props} />} />
        <Route path="/creator/:creatorKey" element={<div>creator detail</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CreatorTeamChemistrySection', () => {
  it('renders both creators with their canonical detail links', () => {
    renderSection({ data: makeResponse() })

    const writer = screen.getByRole('link', { name: 'Writer One' })
    expect(writer).toHaveAttribute('href', '/creators/creator%3A1')
    const artist = screen.getByRole('link', { name: 'Artist Two' })
    expect(artist).toHaveAttribute('href', '/creators/creator%3A2')
  })

  it('carries explainable sample and baseline context for every member', () => {
    renderSection({ data: makeResponse() })

    expect(screen.getByText('3 shared rated issues'))
    expect(screen.getAllByText('6 rated in your library')).toHaveLength(2)
    expect(screen.getAllByLabelText(/baseline average rating 3\.5 out of 5/).length).toBe(2)
    expect(screen.getAllByLabelText(/together this pair averages 4\.33 out of 5/i).length).toBe(2)
    expect(screen.getAllByText(/\+0\.50 vs baseline/).length).toBe(2)
  })

  it('links every drilldown issue ref to its thread without implying causation', () => {
    renderSection({ data: makeResponse() })

    const issueLink = screen.getByRole('link', { name: /Team Run issue 3, rated 5 out of 5/ })
    // The shared-issue ref deep-links to that exact canonical issue (#3626).
    expect(issueLink).toHaveAttribute('href', '/thread/11?issue=101#issue-101')

    const note = screen.getByText(
      /Descriptive context from your own ratings/i,
    )
    expect(note).toHaveTextContent(/not causes or statistically significant/i)
  })

  it('scopes to one creator from creator detail and hides unrelated teams', () => {
    const data = makeResponse({
      pairs: [
        makePair({ pair_key: 'creator:1|creator:2' }),
        makePair({
          pair_key: 'creator:5|creator:6',
          creators: [
            makeMember('creator:5', 'Writer Five'),
            makeMember('creator:6', 'Artist Six'),
          ],
        }),
      ],
    })
    renderSection({ data, forCreatorKey: 'creator:1' })

    expect(screen.getByRole('link', { name: 'Writer One' }))
    expect(screen.queryByRole('link', { name: 'Writer Five' })).not.toBeInTheDocument()
  })

  it('shows an empty state that names the minimum shared sample', () => {
    const data = makeResponse({
      pairs: [],
      pairs_total: 0,
      coverage: {
        rated_issues_total: 2,
        rated_issues_with_creator_metadata: 2,
        ratings_complete: true,
      },
    })
    renderSection({ data })

    expect(screen.getByText(/No recurring creator teams yet/i)).toHaveTextContent(
      /at least 3 issues/,
    )
  })

  it('reports partial metadata as a lower bound instead of negative evidence', () => {
    const data = makeResponse({
      coverage: {
        rated_issues_total: 9,
        rated_issues_with_creator_metadata: 7,
        ratings_complete: false,
      },
    })
    renderSection({ data })

    expect(screen.getByText(/Partial results: some rated issues are still missing/i)).toHaveTextContent(
      /lower bounds/i,
    )
  })
})
