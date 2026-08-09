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
}

describe('RollRecoveryCard', () => {
  it('preserves the original roll while explaining the direct blocker and ordered readable leaves', () => {
    const onReadNow = vi.fn()
    render(<RollRecoveryCard recovery={recovery} onReadNow={onReadNow} />)

    expect(screen.getByText('Original Roll')).toBeInTheDocument()
    expect(screen.getByText('Prerequisite #2')).toBeInTheDocument()
    expect(screen.getByText('Deep prerequisite #1')).toBeInTheDocument()
    expect(screen.getByText('Event chapter')).toBeInTheDocument()
    expect(screen.getByText('Recommended first')).toBeInTheDocument()

    fireEvent.click(screen.getAllByText('Read now')[0])
    expect(onReadNow).toHaveBeenCalledWith(recovery.readable_prerequisites[0])
  })

  it('shows recommendations without a mutating action before safe replacement exists', () => {
    render(<RollRecoveryCard recovery={recovery} />)

    expect(screen.getByText('Original Roll')).toBeInTheDocument()
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

    expect(screen.getByText('Original Roll')).toBeInTheDocument()
    expect(screen.getByText(/No readable prerequisite is available yet/)).toBeInTheDocument()
  })
})
