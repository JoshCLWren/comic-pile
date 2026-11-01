import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { RollBootstrapThread } from '../types/rollBootstrap'

type PoolProps = Parameters<typeof ThreadPool>[0]

const baseProps: PoolProps = {
  pool: [],
  dieSize: 6,
  isRatingView: false,
  selectedThreadId: null,
  snoozedThreads: [],
  snoozedExpanded: false,
  skippedThreads: [],
  skippedExpanded: false,
  onThreadClick: vi.fn(),
  onUnsnooze: vi.fn(),
  onUnskip: vi.fn(),
  onToggleSnoozed: vi.fn(),
  onToggleSkipped: vi.fn(),
  onShuffle: vi.fn(),
  unsnoozeIsPending: false,
  unskipIsPending: false,
  shuffleIsPending: false,
}

function mount(overrides: Partial<PoolProps> = {}) {
  return render(
    <MemoryRouter>
      <ThreadPool {...baseProps} {...overrides} />
    </MemoryRouter>,
  )
}

const eligible: RollBootstrapThread = {
  id: 8, title: 'Saga', format: 'Comic', issue_number: '2',
}

describe('Roll diagnostics removal (#4441)', () => {
  it('does not render blocked, stale or out-of-pool sections or pagination', () => {
    mount({ pool: [eligible] })

    expect(screen.getByRole('button', { name: /Die face 1: Saga/i })).toBeInTheDocument()
    for (const text of [
      /series waiting for earlier issues/i,
      /series you haven't opened recently/i,
      /series out of the roll pool/i,
      /load more/i,
      /try again/i,
    ]) {
      expect(screen.queryByText(text)).not.toBeInTheDocument()
    }
  })

  it('treats a zero eligible pool as empty without materializing out-of-pool rows', () => {
    mount({ emptyPoolReason: 'no_series' })

    expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add a Series/i })).toBeInTheDocument()
    expect(screen.queryByText(/out of the roll pool/i)).not.toBeInTheDocument()
  })

  it('continues to surface snoozed options without retired report panels', () => {
    mount({ snoozedThreads: [{ id: 12, title: 'On break', format: 'Comic' }], snoozedExpanded: true })

    expect(screen.getByText('On break')).toBeInTheDocument()
    expect(screen.getByText('Snoozed (1)')).toBeInTheDocument()
    expect(screen.queryByText(/out of the roll pool/i)).not.toBeInTheDocument()
  })
})
