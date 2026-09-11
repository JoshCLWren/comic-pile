import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingPathPanel } from '../pages/RollPage/components/ReadingPathPanel'
import type { ReaderContextResponse } from '../types'

const CURRENT_ISSUE_ID = 22947
const navigateSpy = vi.fn()

const baseContext: ReaderContextResponse = {
  issue_id: CURRENT_ISSUE_ID,
  series: {
    identity_source: 'comicvine',
    canonical_series_id: 'mm-1',
    series_name: 'Absolute Martian Manhunter',
    average_rating: null,
    ratings_count: 0,
    previous_issue: null,
    recent_ratings: [],
    highest_rating: null,
    lowest_rating: null,
  },
  crossovers: [],
  local_chain: {
    issues: [
      { issue_id: 22946, issue_number: '6', position: 1, status: 'read', relation: 'previous', rating: 4, crossover_memberships: [] },
      { issue_id: CURRENT_ISSUE_ID, issue_number: '7', position: 2, status: 'unread', relation: 'current', rating: null, crossover_memberships: [] },
      { issue_id: 22948, issue_number: '8', position: 3, status: 'unread', relation: 'next', rating: null, crossover_memberships: [] },
      { issue_id: 22949, issue_number: '9', position: 4, status: 'unread', relation: 'future', rating: null, crossover_memberships: [] },
    ],
    edges: [
      {
        id: 944,
        kind: 'continuity',
        source_issue_id: 22946,
        target_issue_id: 22950,
        source_thread_id: 3160,
        target_thread_id: 3161,
        source_label: 'Absolute Martian Manhunter #6',
        target_label: 'Absolute Evil #1',
        source_status: 'read',
        target_status: 'unread',
        note: null,
        explanation: 'Absolute Martian Manhunter #6 must be read before Absolute Evil #1',
      },
      {
        id: 945,
        kind: 'continuity',
        source_issue_id: 22950,
        target_issue_id: CURRENT_ISSUE_ID,
        source_thread_id: 3161,
        target_thread_id: 3160,
        source_label: 'Absolute Evil #1',
        target_label: 'Absolute Martian Manhunter #7',
        source_status: 'unread',
        target_status: 'unread',
        note: null,
        explanation: 'Absolute Evil #1 must be read before Absolute Martian Manhunter #7',
      },
      {
        id: 949,
        kind: 'continuity',
        source_issue_id: 22949,
        target_issue_id: 22902,
        source_thread_id: 3160,
        target_thread_id: 3153,
        source_label: 'Absolute Martian Manhunter #9',
        target_label: 'Absolute Superman #17',
        source_status: 'unread',
        target_status: 'unread',
        note: null,
        explanation: 'Future continuity',
      },
    ],
  },
}

beforeEach(() => {
  navigateSpy.mockClear()
})

describe('ReadingPathPanel', () => {
  it('renders factual prerequisite context without a readiness verdict', async () => {
    const user = userEvent.setup()
    render(
      <ReadingPathPanel
        context={baseContext}
        fallbackAnchorLabel="Absolute Martian Manhunter #7"
        onOpenThread={navigateSpy}
      />,
    )

    expect(screen.getByTestId('reading-path-anchor')).toBeInTheDocument()
    expect(screen.getByText('You are here')).toBeInTheDocument()
    expect(screen.getByLabelText('Current issue: Absolute Martian Manhunter #7')).toBeInTheDocument()
    expect(screen.getByText('Before this issue')).toBeInTheDocument()
    expect(screen.getByText('Absolute Martian Manhunter #6')).toBeInTheDocument()
    expect(screen.getByText('Absolute Evil #1')).toBeInTheDocument()
    expect(screen.getByText('Already read')).toBeInTheDocument()
    expect(screen.getByText('Not read yet')).toBeInTheDocument()

    expect(screen.queryByText(/Caught up/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Not yet/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/readiness/i)).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-path-readable')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-path-blocked')).not.toBeInTheDocument()

    const buttons = screen.getAllByRole('button', { name: /Open series for/ })
    await user.click(buttons[0])
    expect(navigateSpy).toHaveBeenCalled()
  })

  it('subordinates future continuity rather than presenting it as a gate', () => {
    render(
      <ReadingPathPanel
        context={baseContext}
        fallbackAnchorLabel="Absolute Martian Manhunter #7"
        onOpenThread={vi.fn()}
      />,
    )
    expect(screen.getByText('Later continuity')).toBeInTheDocument()
    const laterSection = screen.getByLabelText('Later continuity')
    expect(laterSection.textContent).toContain('Absolute Martian Manhunter #9')
    expect(laterSection.textContent).toContain('Absolute Superman #17')
    expect(screen.getByText(/These unlock after your current read/)).toBeInTheDocument()
  })

  it('renders truthful empty state when no edges touch the neighborhood', () => {
    const context = { ...baseContext, local_chain: { ...baseContext.local_chain, edges: [] } }
    render(
      <ReadingPathPanel
        context={context}
        fallbackAnchorLabel="Absolute Martian Manhunter #7"
        onOpenThread={vi.fn()}
      />,
    )
    expect(screen.getByText(/No continuity prerequisites are recorded around/)).toBeInTheDocument()
  })

  it('falls back to the provided label when series identity or current marker is unavailable', () => {
    const context: ReaderContextResponse = {
      ...baseContext,
      series: { ...baseContext.series, series_name: null },
      local_chain: {
        ...baseContext.local_chain,
        issues: baseContext.local_chain.issues.map((issue) => ({ ...issue, relation: 'previous' as const })),
        edges: [],
      },
    }
    render(
      <ReadingPathPanel context={context} fallbackAnchorLabel="Fallback #99" onOpenThread={vi.fn()} />,
    )
    expect(screen.getByLabelText('Current issue: Fallback #99')).toBeInTheDocument()
    expect(screen.getByText('Fallback #99')).toBeInTheDocument()
  })

  it('renders non-navigable endpoints and null-status steps without marks', () => {
    const context: ReaderContextResponse = {
      ...baseContext,
      local_chain: {
        ...baseContext.local_chain,
        edges: [
          {
            id: 1000,
            kind: 'dependency',
            source_issue_id: 9001,
            target_issue_id: CURRENT_ISSUE_ID,
            source_thread_id: null,
            target_thread_id: null,
            source_label: null,
            target_label: null,
            source_status: null,
            target_status: null,
            note: null,
            explanation: null,
          },
        ],
      },
    }
    render(
      <ReadingPathPanel
        context={context}
        fallbackAnchorLabel="Absolute Martian Manhunter #7"
        onOpenThread={vi.fn()}
      />,
    )
    expect(screen.getAllByText('a missing issue').length).toBeGreaterThan(0)
    expect(screen.queryByText('Already read')).not.toBeInTheDocument()
    expect(screen.queryByText('Not read yet')).not.toBeInTheDocument()
    expect(screen.getByText('Before this issue')).toBeInTheDocument()
  })

  it('renders downstream facts and both dependency and continuity arrows', () => {
    const context: ReaderContextResponse = {
      ...baseContext,
      local_chain: {
        ...baseContext.local_chain,
        edges: [
          {
            id: 950,
            kind: 'dependency',
            source_issue_id: CURRENT_ISSUE_ID,
            target_issue_id: 9999,
            source_thread_id: 3160,
            target_thread_id: 3200,
            source_label: 'Absolute Martian Manhunter #7',
            target_label: 'Future #1',
            source_status: null,
            target_status: null,
            note: null,
            explanation: null,
          },
          {
            id: 951,
            kind: 'continuity',
            source_issue_id: CURRENT_ISSUE_ID,
            target_issue_id: 9998,
            source_thread_id: 3160,
            target_thread_id: 3201,
            source_label: 'Absolute Martian Manhunter #7',
            target_label: 'Future #2',
            source_status: null,
            target_status: null,
            note: null,
            explanation: 'Unlocks later',
          },
        ],
      },
    }
    render(
      <ReadingPathPanel
        context={context}
        fallbackAnchorLabel="Absolute Martian Manhunter #7"
        onOpenThread={vi.fn()}
      />,
    )
    expect(screen.getByText('After you read this')).toBeInTheDocument()
    expect(screen.getAllByText('→').length).toBeGreaterThan(0)
    expect(screen.getAllByText('↝').length).toBeGreaterThan(0)
    expect(screen.getByText('Unlocks later')).toBeInTheDocument()
  })
})
