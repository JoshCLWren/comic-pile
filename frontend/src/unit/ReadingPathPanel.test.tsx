import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingPathPanel } from '../pages/RollPage/components/ReadingPathPanel'
import type { ReaderContextResponse } from '../types'
import type { ContinuityReadinessState } from '../hooks/useContinuityReadiness'

const navigateSpy = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

const baseContext: ReaderContextResponse = {
  issue_id: 22947,
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
      { issue_id: 22947, issue_number: '7', position: 2, status: 'unread', relation: 'current', rating: null, crossover_memberships: [] },
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
        source_issue_number: '6',
        target_issue_number: '1',
        source_thread_title: 'Absolute Martian Manhunter',
        target_thread_title: 'Absolute Evil',
      } as any,
      {
        id: 945,
        kind: 'continuity',
        source_issue_id: 22950,
        target_issue_id: 22947,
        source_thread_id: 3161,
        target_thread_id: 3160,
        source_label: 'Absolute Evil #1',
        target_label: 'Absolute Martian Manhunter #7',
        source_status: 'unread',
        target_status: 'unread',
        note: null,
        explanation: 'Absolute Evil #1 must be read before Absolute Martian Manhunter #7',
        source_issue_number: '1',
        target_issue_number: '7',
        source_thread_title: 'Absolute Evil',
        target_thread_title: 'Absolute Martian Manhunter',
      } as any,
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
        source_issue_number: '9',
        target_issue_number: '17',
        source_thread_title: 'Absolute Martian Manhunter',
        target_thread_title: 'Absolute Superman',
      } as any,
    ],
  },
}

function readiness(overrides: Partial<ContinuityReadinessState> = {}): ContinuityReadinessState {
  return {
    readiness: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  navigateSpy.mockClear()
})

describe('ReadingPathPanel regression (issue #1916)', () => {
  it('anchors on the current issue and subordinates the future edge as downstream context', async () => {
    const user = userEvent.setup()
    render(
      <ReadingPathPanel
        context={baseContext}
        readinessState={readiness({
          readiness: {
            is_readable: false,
            blockers: [
              {
                target_label: 'Absolute Martian Manhunter #7',
                source_label: 'Absolute Evil #1',
                unread_issue_details: [{ label: 'Absolute Evil #1', issue_id: 22950, issue_number: '1', thread_id: 3161 }],
              } as any,
            ],
          } as any,
        })}
        fallbackAnchorLabel="Absolute Martian Manhunter #7"
        onOpenThread={navigateSpy as any}
      />,
    )

    // Current issue must be unmistakable
    expect(screen.getByTestId('reading-path-anchor')).toBeInTheDocument()
    expect(screen.getByText('You are here')).toBeInTheDocument()
    expect(screen.getByLabelText('Current issue: Absolute Martian Manhunter #7')).toBeInTheDocument()

    // Prerequisite path into current should be visible without interpreting arrow direction
    expect(screen.getByText('Before this issue')).toBeInTheDocument()
    expect(screen.getByText('Absolute Martian Manhunter #6')).toBeInTheDocument()
    expect(screen.getByText('Absolute Evil #1')).toBeInTheDocument()

    // Future edge must be in Later continuity, not competing as equally relevant
    expect(screen.getByText('Later continuity')).toBeInTheDocument()
    const laterSection = screen.getByLabelText('Later continuity')
    expect(laterSection.textContent).toContain('Absolute Martian Manhunter #9')
    expect(laterSection.textContent).toContain('Absolute Superman #17')
    // Should indicate it does not block current
    expect(screen.getByText(/These unlock after your current read/)).toBeInTheDocument()

    // Readiness copy names the blocker
    expect(screen.getByTestId('reading-path-blocked')).toHaveTextContent('Absolute Evil #1')

    // Thread endpoints are navigable
    const buttons = screen.getAllByRole('button', { name: /Open thread for/ })
    expect(buttons.length).toBeGreaterThan(0)
    await user.click(buttons[0])
  })

  it('says Caught up when prerequisites are satisfied and future continuity remains subordinate', () => {
    render(
      <ReadingPathPanel
        context={baseContext}
        readinessState={readiness({ readiness: { is_readable: true, blockers: [] } as any })}
        fallbackAnchorLabel="Absolute Martian Manhunter #7"
        onOpenThread={vi.fn()}
      />,
    )
    expect(screen.getByTestId('reading-path-readable')).toBeInTheDocument()
    expect(screen.getByText(/Caught up — you can read Absolute Martian Manhunter #7 now\./)).toBeInTheDocument()
    expect(screen.getByText('Later continuity')).toBeInTheDocument()
  })

  it('renders truthful empty state when no edges touch the neighborhood', () => {
    const ctx = { ...baseContext, local_chain: { ...baseContext.local_chain, edges: [] } }
    render(
      <ReadingPathPanel context={ctx} readinessState={readiness()} fallbackAnchorLabel="Absolute Martian Manhunter #7" onOpenThread={vi.fn()} />,
    )
    expect(screen.getByText(/No continuity prerequisites are recorded around/)).toBeInTheDocument()
  })
})
