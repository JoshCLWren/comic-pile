import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import DependencyFlowchart from '../components/DependencyFlowchart'

const makeThread = (id: number) => ({ id, title: `Thread ${id} with a long title`, format: 'Comic', issues_remaining: 1, total_issues: 2, next_unread_issue_id: null, reading_progress: null, queue_position: id, status: 'active', is_blocked: id === 2, blocking_reasons: [], collection_id: null, created_at: 'now' })

describe('DependencyFlowchart', () => {
  it('renders empty state and interactive graph controls', () => {
    const empty = render(<DependencyFlowchart threads={[]} dependencies={[]} blockedIds={new Set()} />)
    expect(empty.getByTestId('flowchart-empty')).toBeInTheDocument()
    empty.unmount()
    const view = render(<DependencyFlowchart threads={[makeThread(1), makeThread(2)] as never} dependencies={[{ id: 'd', source_id: 1, target_id: 2, created_at: 'now', isBlocking: true } as never]} blockedIds={new Set([2])} issueNodes={[]} />)
    const svg = view.getByTestId('flowchart-svg')
    fireEvent.wheel(svg, { deltaY: -100, clientX: 10, clientY: 10 })
    fireEvent.wheel(svg, { deltaY: 100, clientX: 10, clientY: 10 })
    fireEvent.mouseDown(svg, { clientX: 10, clientY: 10 }); fireEvent.mouseMove(svg, { clientX: 20, clientY: 30 }); fireEvent.mouseUp(svg)
    fireEvent.mouseEnter(view.getByTestId('flowchart-node-2'), { clientX: 20, clientY: 30 })
    expect(view.getByTestId('flowchart-tooltip')).toHaveTextContent('blocked')
    fireEvent.mouseLeave(view.getByTestId('flowchart-node-2'))
    fireEvent.click(view.getByRole('button', { name: 'Zoom in' }))
    fireEvent.click(view.getByRole('button', { name: 'Zoom out' }))
    fireEvent.click(view.getByRole('button', { name: 'Reset view' }))
    fireEvent.mouseDown(view.getByTestId('flowchart-node-1'), { clientX: 20, clientY: 20 })
    fireEvent.mouseMove(svg, { clientX: 30, clientY: 35 }); fireEvent.mouseUp(svg)
    expect(view.getByTestId('flowchart-edge-1-2')).toBeInTheDocument()
    fireEvent.mouseEnter(view.getByTestId('flowchart-node-1'), { clientX: 2, clientY: 3 })
    fireEvent.mouseDown(view.getByTestId('flowchart-node-1'), { clientX: 2, clientY: 3 })
    fireEvent.mouseLeave(view.getByTestId('flowchart-node-1'))
  })

  it('shows pagination for large graphs', () => {
    const threads = Array.from({ length: 101 }, (_, index) => makeThread(index + 1))
    render(<DependencyFlowchart threads={threads as never} dependencies={[]} blockedIds={new Set()} />)
    expect(screen.getByTestId('flowchart-warning')).toBeInTheDocument()
    expect(screen.getByText('1/3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(screen.getByText('2/3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Previous page' }))
    expect(screen.getByText('1/3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Previous page' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(screen.getByText('3/3')).toBeInTheDocument()
  })

  it('renders issue nodes and filters issue-level edges by parent visibility', () => {
    const issueNodes = [
      { id: -1, title: 'Source #1', x: 0, y: 0, isBlocked: false, isIssueNode: true, parentThreadId: 1 },
      { id: -2, title: 'Target #2', x: 0, y: 0, isBlocked: true, isIssueNode: true, parentThreadId: 2 },
      { id: -3, title: 'Hidden', x: 0, y: 0, isBlocked: false, isIssueNode: true, parentThreadId: 99 },
    ]
    const view = render(<DependencyFlowchart
      threads={[makeThread(1), makeThread(2)] as never}
      dependencies={[
        { id: 'issue', source_id: -1, target_id: -2, created_at: 'now', is_issue_level: true } as never,
        { id: 'missing', source_id: 1, target_id: 99, created_at: 'now' } as never,
      ]}
      blockedIds={new Set([2])}
      issueNodes={issueNodes as never}
    />)
    expect(view.getByTestId('flowchart-node--1')).toBeInTheDocument()
    expect(view.getByTestId('flowchart-node--2')).toBeInTheDocument()
    expect(view.queryByTestId('flowchart-node--3')).not.toBeInTheDocument()
    const svg = view.getByTestId('flowchart-svg')
    fireEvent.mouseDown(svg, { clientX: 1, clientY: 1 })
    fireEvent.mouseMove(svg, { clientX: 10, clientY: 20 })
    fireEvent.mouseUp(svg)
  })

  it('ignores issue-level edges without visible parent metadata and handles missing drag targets', () => {
    const view = render(<DependencyFlowchart
      threads={[makeThread(1)] as never}
      dependencies={[{ id: 'orphan', source_id: -10, target_id: -11, is_issue_level: true, created_at: 'now' } as never]}
      blockedIds={new Set()}
      issueNodes={[{ id: -10, title: 'Orphan', x: 0, y: 0, isBlocked: false, isIssueNode: true } as never]}
    />)
    const svg = view.getByTestId('flowchart-svg')
    fireEvent.mouseDown(svg, { clientX: 1, clientY: 1 })
    fireEvent.mouseMove(svg, { clientX: 2, clientY: 2 })
    fireEvent.mouseUp(svg)
    expect(view.queryByTestId('flowchart-edge--10--11')).not.toBeInTheDocument()
  })

  it('covers zoom limits, issue-node geometry, and drag cancellation paths', () => {
    const view = render(<DependencyFlowchart
      threads={[makeThread(1), makeThread(2)] as never}
      dependencies={[{
        id: 'issue-blocking', source_id: -1, target_id: -2, created_at: 'now',
        is_issue_level: true, isBlocking: true,
      } as never]}
      blockedIds={new Set([2])}
      issueNodes={[
        { id: -1, title: 'Prerequisite #1', x: 0, y: 0, isBlocked: false, isIssueNode: true, parentThreadId: 1 },
        { id: -2, title: 'Target #2', x: 0, y: 0, isBlocked: true, isIssueNode: true, parentThreadId: 2 },
      ] as never}
    />)
    const svg = view.getByTestId('flowchart-svg')
    for (let i = 0; i < 20; i += 1) fireEvent.click(view.getByRole('button', { name: 'Zoom in' }))
    for (let i = 0; i < 20; i += 1) fireEvent.click(view.getByRole('button', { name: 'Zoom out' }))
    fireEvent.mouseEnter(view.getByTestId('flowchart-node--1'), { clientX: 4, clientY: 5 })
    fireEvent.mouseDown(view.getByTestId('flowchart-node--1'), { clientX: 4, clientY: 5 })
    fireEvent.mouseMove(svg, { clientX: 40, clientY: 50 })
    fireEvent.mouseUp(svg)
    fireEvent.mouseDown(view.getByTestId('flowchart-node--1'), { clientX: 4, clientY: 5 })
    fireEvent.mouseLeave(view.getByTestId('flowchart-node--1'))
    expect(view.getByTestId('flowchart-edge--1--2')).toBeInTheDocument()
  })
})
