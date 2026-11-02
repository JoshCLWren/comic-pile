import { fireEvent, render, screen } from '@testing-library/react'
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
  id: 24, title: 'Planetary', format: 'Comic', issue_number: '7',
}

describe('Retired Roll exclusion details (#4441)', () => {
  it('never renders excluded thread titles, dependency details or navigable links', () => {
    mount()

    for (const text of [
      /series waiting for earlier issues/i,
      /series you haven't opened recently/i,
      /series out of the roll pool/i,
      /Locked By Earlier Issue/i,
      /Read Saga #5 first/i,
      /Completed Vol. 2/i,
    ]) {
      expect(screen.queryByText(text)).not.toBeInTheDocument()
    }
    expect(screen.queryByRole('link', { name: /Saga/i })).not.toBeInTheDocument()
  })

  it('preserves direct actions on real eligible die faces', () => {
    const onThreadClick = vi.fn()
    mount({ pool: [eligible], onThreadClick })

    fireEvent.click(screen.getByRole('button', { name: /Die face 1: Planetary/i }))
    expect(onThreadClick).toHaveBeenCalledWith(eligible)
  })

  it('offers queue navigation for snoozed-only state without an exclusion report', () => {
    mount({ snoozedThreads: [{ id: 2, title: 'Paused', format: 'Comic' }] })

    expect(screen.getByText('Every series is snoozed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go to Queue' })).toBeInTheDocument()
    expect(screen.queryByText('Completed Vol. 2')).not.toBeInTheDocument()
  })

  it('retains keyboard access to eligible issue selection', () => {
    const onThreadClick = vi.fn()
    mount({ pool: [eligible], onThreadClick })

    fireEvent.keyDown(screen.getByRole('button', { name: /Die face 1: Planetary/i }), {
      key: 'Enter',
    })
    expect(onThreadClick).toHaveBeenCalledWith(eligible)
  })
})
