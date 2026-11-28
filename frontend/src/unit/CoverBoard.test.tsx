import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CoverBoard } from '../pages/RollPage/components/CoverBoard'
import type { RollBootstrapThread } from '../types/rollBootstrap'

const pool: RollBootstrapThread[] = [
  { id: 1, title: 'Alpha', format: 'Comic', issue_id: 10 },
  { id: 2, title: 'Beta', format: 'Comic', issue_id: 20 },
  { id: 3, title: 'Gamma', format: 'Comic' },
  { id: 4, title: 'Delta', format: 'Comic' },
]

describe('CoverBoard (#5981)', () => {
  it('renders faces for a d4 pool with the die slot', () => {
    render(
      <CoverBoard
        pool={pool.slice(0, 4)}
        cardByIssueId={new Map()}
        dieSize={4}
        selectedThreadId={null}
        dieSlot={<div data-testid="die-slot" />}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByTestId('roll-cover-board')).toBeInTheDocument()
    expect(screen.getByTestId('die-slot')).toBeInTheDocument()
  })

  it('renders a single-item pool without empty rows', () => {
    render(
      <CoverBoard
        pool={pool.slice(0, 1)}
        cardByIssueId={new Map()}
        dieSize={6}
        selectedThreadId={1}
        dieSlot={<div data-testid="die-slot" />}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByTestId('roll-cover-board')).toBeInTheDocument()
  })

  it('renders a d20-sized board', () => {
    const big = Array.from({ length: 20 }, (_, i) => ({
      id: i + 1,
      title: `Book ${i + 1}`,
      format: 'Comic',
    }))
    render(
      <CoverBoard
        pool={big}
        cardByIssueId={new Map()}
        dieSize={20}
        selectedThreadId={null}
        dieSlot={<div data-testid="die-slot" />}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByTestId('roll-cover-board')).toBeInTheDocument()
  })
})
