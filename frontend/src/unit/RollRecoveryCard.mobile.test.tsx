import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
      source_label: 'Direct blocker #2',
      satisfaction_type: 'item_read',
      satisfied: false,
      causing_issue_ids: [20],
      causing_member_issue_ids: [],
      note: null,
    },
  ],
  readable_prerequisites: [
    { node_type: 'issue', node_id: 30, label: 'Transitive prerequisite #1' },
    { node_type: 'issue', node_id: 31, label: 'Alternate readable prerequisite #3' },
  ],
}

describe('RollRecoveryCard mobile', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 390,
    })
    window.dispatchEvent(new Event('resize'))
  })

  it('keeps the original roll, direct blocker, and ordered transitive recommendations usable on a phone viewport', () => {
    const onReadNow = vi.fn()
    render(<RollRecoveryCard recovery={recovery} onReadNow={onReadNow} />)

    const card = screen.getByLabelText('Blocked roll recovery')
    expect(card).toHaveClass('w-full', 'max-w-xl')
    expect(screen.getByText('Original Roll')).toBeVisible()
    expect(screen.getByText('Direct blocker #2')).toBeVisible()
    expect(screen.getByText('Transitive prerequisite #1')).toBeVisible()
    expect(screen.getByText('Alternate readable prerequisite #3')).toBeVisible()
    expect(screen.getByText('Recommended first')).toBeVisible()

    const readNowButtons = screen.getAllByRole('button')
    expect(readNowButtons).toHaveLength(2)
    fireEvent.click(readNowButtons[0])
    expect(onReadNow).toHaveBeenCalledWith(recovery.readable_prerequisites[0])
  })

  it('keeps the original roll visible on mobile when no readable leaf exists', () => {
    render(<RollRecoveryCard recovery={{ ...recovery, readable_prerequisites: [] }} />)

    expect(screen.getByText('Original Roll')).toBeVisible()
    expect(screen.getByText(/No readable prerequisite is available yet/)).toBeVisible()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('stacks the Read now CTA below the prerequisite title so they cannot overlap on a phone', () => {
    const onReadNow = vi.fn()
    render(<RollRecoveryCard recovery={recovery} onReadNow={onReadNow} />)

    const readNowRows = screen.getAllByRole('button')
    expect(readNowRows).toHaveLength(2)
    for (const row of readNowRows) {
      expect(row).toHaveClass('flex-col')
      expect(row).toHaveClass('sm:flex-row')
      expect(row).not.toHaveClass('justify-between')
    }

    for (const prerequisite of recovery.readable_prerequisites) {
      expect(screen.getByText(prerequisite.label)).toBeVisible()
    }
    expect(screen.getAllByText('Read now')).toHaveLength(2)
  })

  it('keeps each prerequisite label in its own wrapping region at phone widths', () => {
    const { container } = render(<RollRecoveryCard recovery={recovery} />)

    const labels = Array.from(
      container.querySelectorAll<HTMLSpanElement>('span.text-sm.font-black'),
    )
    expect(labels.map((label) => label.textContent)).toEqual([
      'Transitive prerequisite #1',
      'Alternate readable prerequisite #3',
    ])
    for (const label of labels) {
      expect(label.className).toContain('block')
    }
  })
})
