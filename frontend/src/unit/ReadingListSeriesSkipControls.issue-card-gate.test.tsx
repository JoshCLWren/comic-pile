/**
 * Issue #5904: a series skip group is a thread-level control over many owned
 * issues. It has no single canonical issue id, so it must not fabricate a
 * covered card from one representative issue number.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ReadingListSeriesSkipControls from '../components/ReadingListSeriesSkipControls'
import type { CustomCBLEntry } from '../services/api-custom-cbl'

const entries: CustomCBLEntry[] = [
  {
    id: 1,
    position: 1,
    issue_id: 11,
    thread_id: 5,
    series_name: 'Saga',
    issue_number: '1',
    status: 'unread',
    gate: 'none',
    skipped: false,
  },
  {
    id: 2,
    position: 2,
    issue_id: 12,
    thread_id: 5,
    series_name: 'Saga',
    issue_number: '2',
    status: 'unread',
    gate: 'none',
    skipped: true,
  },
]

describe('series skip controls issue-card gate (#5904)', () => {
  it('renders the series-level skip control without an invented exact issue card', () => {
    render(
      <ReadingListSeriesSkipControls
        entries={entries}
        disabled={false}
        onSeriesSkipChange={vi.fn()}
      />,
    )

    expect(screen.getByText('Skip or restore a whole series')).toBeVisible()
    expect(screen.getByText('Saga')).toBeVisible()
    expect(screen.getByText('1 of 2 skipped in this list')).toBeVisible()
    expect(document.querySelector('[data-testid^="issue-card-trigger-"]')).toBeNull()
  })
})
