import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RollRecoveryCard } from '../pages/RollPage/components/RollRecoveryCard'
import type { RollRecoveryInfo } from '../types/rollBootstrap'

const recovery: RollRecoveryInfo = {
  original_thread_id: 10,
  original_thread_title: 'Original Roll',
  direct_blockers: [
    {
      rule_id: 1,
      source_type: 'issue',
      source_id: 20,
      source_label: 'Prerequisite #2',
      satisfaction_type: 'item_read',
      satisfied: false,
      causing_issue_ids: [20],
      causing_member_issue_ids: [],
      note: null,
    },
  ],
  readable_prerequisites: [
    { node_type: 'issue', node_id: 30, label: 'Deep prerequisite #1' },
    { node_type: 'crossover', node_id: 40, label: 'Event chapter' },
  ],
  chains: [
    [
      { node_type: 'crossover', node_id: 25, label: 'Event Alpha', is_readable: false },
      { node_type: 'issue', node_id: 30, label: 'Deep prerequisite #1', is_readable: true },
    ],
    [
      { node_type: 'issue', node_id: 35, label: 'Parallel branch', is_readable: false },
      { node_type: 'crossover', node_id: 40, label: 'Event chapter', is_readable: true },
    ],
  ],
}

describe('RollRecoveryCard', () => {
  it('preserves the original roll while explaining the direct blocker and ordered readable leaves', () => {
    const onReadNow = vi.fn()
    render(<RollRecoveryCard recovery={recovery} onReadNow={onReadNow} />)

    expect(screen.getByRole('heading', { name: 'Original Roll' })).toBeInTheDocument()
    expect(screen.getByText('Prerequisite #2')).toBeInTheDocument()
    expect(screen.getByText('Deep prerequisite #1')).toBeInTheDocument()
    expect(screen.getByText('Event chapter')).toBeInTheDocument()
    expect(screen.getByText('Recommended first')).toBeInTheDocument()

    fireEvent.click(screen.getAllByText('Read now')[0])
    expect(onReadNow).toHaveBeenCalledWith(recovery.readable_prerequisites[0])
  })

  it('expands branching dependency paths with node kinds and readable leaves', () => {
    render(<RollRecoveryCard recovery={recovery} />)

    fireEvent.click(screen.getByText(/Why is this blocked\? \(2 paths\)/))

    expect(screen.getByRole('list', { name: 'Dependency path 1' })).toHaveTextContent('Event Alpha')
    expect(screen.getByRole('list', { name: 'Dependency path 2' })).toHaveTextContent('Parallel branch')
    expect(screen.getAllByText('Readable now')).toHaveLength(2)
    expect(screen.getAllByText('crossover')).toHaveLength(2)
  })

  it('shows traversal diagnostics instead of failing on an invalid continuity plan', () => {
    render(
      <RollRecoveryCard
        recovery={{
          ...recovery,
          chains: [],
          diagnostics: [
            { code: 'cycle_detected', node_type: 'issue', node_id: 30 },
          ],
        }}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('contains a cycle')
  })

  it('shows recommendations without a mutating action before safe replacement exists', () => {
    render(<RollRecoveryCard recovery={recovery} />)

    expect(screen.getByRole('heading', { name: 'Original Roll' })).toBeInTheDocument()
    expect(screen.getAllByText('Read now')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: /Deep prerequisite #1/i })).not.toBeInTheDocument()
  })

  it('keeps the blocked roll visible when traversal has no readable leaf', () => {
    render(
      <RollRecoveryCard
        recovery={{ ...recovery, readable_prerequisites: [] }}
        onReadNow={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Original Roll' })).toBeInTheDocument()
    expect(screen.getByText(/No readable prerequisite is available yet/)).toBeInTheDocument()
  })

  it('shows a non-destructive loading state while recovery guidance is being resolved', () => {
    render(<RollRecoveryCard isLoading />)

    expect(screen.getByLabelText('Blocked roll recovery')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByText(/Checking what needs to be read first/)).toBeInTheDocument()
  })

  it('preserves the original roll when recovery guidance fails to load', () => {
    render(<RollRecoveryCard errorMessage="Could not load prerequisite guidance." />)

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load prerequisite guidance.')
    expect(screen.getByText('Your original roll is still preserved.')).toBeInTheDocument()
  })

  it('renders nothing when there is no recovery state to explain', () => {
    const { container } = render(<RollRecoveryCard />)

    expect(container).toBeEmptyDOMElement()
  })
})
