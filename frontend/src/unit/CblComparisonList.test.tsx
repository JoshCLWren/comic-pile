import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { CblComparisonList } from '../components/CblComparisonList'
import type { CBLSourceComparisonMatch } from '../services/api-cbl-sources'

function candidate(
  overrides: Partial<CBLSourceComparisonMatch> = {},
): CBLSourceComparisonMatch {
  return {
    list_id: 7,
    list_name: 'Ultimate Reading Order',
    source_path: 'Marvel/Ultimate.cbl',
    source_repository: 'JoshCLWren/CBL-ReadingLists',
    source_ref: 'JoshCLWren/CBL-ReadingLists:Marvel/Ultimate.cbl',
    revision_sha: 'abcdef1234567890',
    declared_issue_count: 3,
    entries_total: 3,
    distinct_source_issues: 3,
    matched_input_count: 3,
    input_total: 3,
    matched_occurrence_count: 3,
    duplicate_match_count: 0,
    source_only_issue_count: 0,
    input_coverage_percentage: 100,
    source_coverage_percentage: 100,
    order_status: 'same_order',
    order_pair_count: 3,
    order_disagreement_count: 0,
    matched_input_ids: ['4000-1', '4000-2', '4000-3'],
    missing_input_ids: [],
    score: 100,
    ...overrides,
  }
}

function renderList(candidates: CBLSourceComparisonMatch[]) {
  return render(
    <MemoryRouter>
      <CblComparisonList
        candidates={candidates}
        inputTotal={3}
        emptyMessage="No CBL source covers these confirmed comics."
        backTo="/thread/3"
        backLabel="Series"
        testIdPrefix="cbl-check"
      />
    </MemoryRouter>,
  )
}

describe('CblComparisonList', () => {
  it('renders the empty message instead of an empty ranked list', () => {
    renderList([])
    expect(screen.getByText('No CBL source covers these confirmed comics.')).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('describes same-order, reordered, duplicate, and source-only evidence', () => {
    renderList([
      candidate(),
      candidate({
        list_id: 8,
        list_name: 'Reordered Source',
        order_status: 'reordered',
        order_pair_count: 3,
        order_disagreement_count: 2,
        score: 87,
      }),
      candidate({
        list_id: 9,
        list_name: 'Duplicate Source',
        distinct_source_issues: 2,
        matched_input_count: 2,
        matched_occurrence_count: 4,
        duplicate_match_count: 2,
        source_only_issue_count: 2,
        input_coverage_percentage: 67,
        order_status: 'not_comparable',
        order_pair_count: 1,
        order_disagreement_count: 0,
        score: 42,
      }),
    ])

    expect(screen.getByTestId('cbl-check-order-7')).toHaveTextContent('Same relative order')
    expect(screen.getByTestId('cbl-check-order-8')).toHaveTextContent(
      'Reordered: 2 of 3 comic pairs differ',
    )
    expect(screen.getByTestId('cbl-check-order-9')).toHaveTextContent('Order not comparable')
    const duplicate = screen.getByTestId('cbl-check-9')
    expect(duplicate).toHaveTextContent('Coverage: 2 of 3 comics (67%)')
    expect(duplicate).toHaveTextContent('2 duplicate source positions count once')
    expect(duplicate).toHaveTextContent('2 source comics are not in this list')
    expect(screen.getByTestId('cbl-check-7').querySelector('h5')).toHaveTextContent(
      'Ultimate Reading Order',
    )
  })

  it('falls back to the list name and singular notes when the source has no display title', () => {
    renderList([
      candidate({
        list_id: 10,
        list_name: 'Untitled Source',
        source_path: '',
        distinct_source_issues: 1,
        matched_input_count: 1,
        matched_occurrence_count: 2,
        source_only_issue_count: 1,
        order_status: 'not_comparable',
        order_pair_count: 0,
        score: 80,
      }),
    ])

    const row = screen.getByTestId('cbl-check-10')
    expect(row.querySelector('h5')).toHaveTextContent('Untitled Source')
    expect(row).toHaveTextContent('1 duplicate source position counts once')
    expect(row).toHaveTextContent('1 source comic is not in this list')
    expect(row).toHaveTextContent('Order not comparable')
  })
})
