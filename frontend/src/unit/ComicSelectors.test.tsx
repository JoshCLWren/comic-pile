import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  ContinuityIssueRangeSelector,
  ContinuityIssueSelector,
  ContinuityThreadSelector,
} from '../components/continuity'
import type { Issue, Thread } from '../types'

const threads: Thread[] = [
  {
    id: 1,
    title: 'Alpha Flight',
    format: 'single issues',
    issues_remaining: 3,
    total_issues: 3,
    queue_position: 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-08-09T00:00:00Z',
  },
  {
    id: 2,
    title: 'New Mutants',
    format: 'single issues',
    issues_remaining: 3,
    total_issues: 3,
    queue_position: 2,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-08-09T00:00:00Z',
  },
]

const issues: Issue[] = [
  { id: 11, thread_id: 1, issue_number: '0', status: 'unread', read_at: null, created_at: '2026-08-09T00:00:00Z' },
  { id: 12, thread_id: 1, issue_number: 'Annual 1', status: 'unread', read_at: null, created_at: '2026-08-09T00:00:00Z' },
  { id: 13, thread_id: 1, issue_number: '½', status: 'unread', read_at: null, created_at: '2026-08-09T00:00:00Z' },
]

describe('continuity comic selectors', () => {
  it('searches threads by human-readable title and returns the selected thread object', () => {
    const onChange = vi.fn()
    render(<ContinuityThreadSelector threads={threads} value={null} onChange={onChange} />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'mutants' } })

    expect(screen.queryByText('Alpha Flight')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('option', { name: /New Mutants/i }))
    expect(onChange).toHaveBeenLastCalledWith(threads[1])
  })

  it('moves keyboard focus from search to the first matching result', () => {
    render(<ContinuityThreadSelector threads={threads} value={null} onChange={vi.fn()} />)

    const search = screen.getByRole('searchbox')
    fireEvent.keyDown(search, { key: 'ArrowDown' })

    expect(screen.getByRole('option', { name: /Alpha Flight/i })).toHaveFocus()
  })

  it('handles current-value editing, exclusions, empty results, loading, errors, and disabled state', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <ContinuityThreadSelector
        threads={threads}
        value={threads[0]}
        onChange={onChange}
        excludeThreadId={2}
      />,
    )

    const search = screen.getByRole('searchbox')
    expect(search).toHaveValue('Alpha Flight')
    expect(screen.queryByText('New Mutants')).not.toBeInTheDocument()

    fireEvent.change(search, { target: { value: 'no match' } })
    expect(onChange).toHaveBeenLastCalledWith(null)
    expect(screen.getByText('No matching comics found.')).toBeInTheDocument()
    fireEvent.keyDown(search, { key: 'ArrowDown' })
    expect(search).toHaveFocus()

    rerender(
      <ContinuityThreadSelector
        threads={threads}
        value={null}
        onChange={onChange}
        isLoading
      />,
    )
    expect(screen.getByText('Loading comics…')).toBeInTheDocument()

    rerender(
      <ContinuityThreadSelector
        threads={threads}
        value={null}
        onChange={onChange}
        error="Search failed"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Search failed')

    rerender(
      <ContinuityThreadSelector
        threads={threads}
        value={null}
        onChange={onChange}
        disabled
      />,
    )
    expect(screen.getByRole('searchbox')).toBeDisabled()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('syncs the thread search text when the selected value changes', () => {
    const { rerender } = render(
      <ContinuityThreadSelector threads={threads} value={null} onChange={vi.fn()} />,
    )

    rerender(<ContinuityThreadSelector threads={threads} value={threads[1]} onChange={vi.fn()} />)
    expect(screen.getByRole('searchbox')).toHaveValue('New Mutants')
  })

  it('selects arbitrary human-facing issue identifiers without numeric parsing', () => {
    const onChange = vi.fn()
    render(<ContinuityIssueSelector issues={issues} value={null} onChange={onChange} />)

    const select = screen.getByRole('combobox', { name: 'Issue' })
    expect(screen.getByRole('option', { name: '#Annual 1' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '#½' })).toBeInTheDocument()

    fireEvent.change(select, { target: { value: '13' } })
    expect(onChange).toHaveBeenLastCalledWith(issues[2])
  })

  it('covers issue loading, empty, error, disabled, and cleared-selection states', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <ContinuityIssueSelector issues={[]} value={null} onChange={onChange} emptyMessage="Nothing here" />,
    )
    expect(screen.getByRole('combobox')).toBeDisabled()
    expect(screen.getByRole('option', { name: 'Nothing here' })).toBeInTheDocument()

    rerender(<ContinuityIssueSelector issues={issues} value={null} onChange={onChange} isLoading />)
    expect(screen.getByRole('combobox')).toBeDisabled()
    expect(screen.getByRole('option', { name: 'Loading issues…' })).toBeInTheDocument()

    rerender(
      <ContinuityIssueSelector
        issues={issues}
        value={issues[0]}
        onChange={onChange}
        error="Issues failed"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Issues failed')
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith(null)

    rerender(<ContinuityIssueSelector issues={issues} value={null} onChange={onChange} disabled />)
    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  it('builds ordered ranges from issue labels and explains reversed order without exposing positions', () => {
    const onChange = vi.fn()
    render(
      <ContinuityIssueRangeSelector
        thread={threads[0]}
        issues={issues}
        value={null}
        onChange={onChange}
      />,
    )

    const first = screen.getByRole('combobox', { name: 'First issue' })
    const last = screen.getByRole('combobox', { name: 'Last issue' })

    fireEvent.change(first, { target: { value: '13' } })
    fireEvent.change(last, { target: { value: '11' } })

    expect(screen.getByRole('alert')).toHaveTextContent('#½ comes after #0 in Alpha Flight')
    expect(screen.queryByText(/position/i)).not.toBeInTheDocument()
    expect(onChange).toHaveBeenLastCalledWith({
      thread: threads[0],
      startIssue: issues[2],
      endIssue: issues[0],
    })
  })

  it('publishes null for incomplete ranges and resyncs draft values from props', () => {
    const onChange = vi.fn()
    const initialRange = { thread: threads[0], startIssue: issues[0], endIssue: issues[1] }
    const { rerender } = render(
      <ContinuityIssueRangeSelector
        thread={threads[0]}
        issues={issues}
        value={initialRange}
        onChange={onChange}
      />,
    )

    expect(screen.getByRole('combobox', { name: 'First issue' })).toHaveValue('11')
    expect(screen.getByRole('combobox', { name: 'Last issue' })).toHaveValue('12')

    fireEvent.change(screen.getByRole('combobox', { name: 'First issue' }), { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith(null)

    rerender(
      <ContinuityIssueRangeSelector
        thread={threads[0]}
        issues={issues}
        value={{ thread: threads[0], startIssue: issues[1], endIssue: issues[2] }}
        onChange={onChange}
        error="Range failed"
        disabled
      />,
    )
    expect(screen.getByRole('combobox', { name: 'First issue' })).toHaveValue('12')
    expect(screen.getByRole('combobox', { name: 'Last issue' })).toHaveValue('13')
    expect(screen.getByRole('alert')).toHaveTextContent('Range failed')
    expect(screen.getByRole('group')).toBeDisabled()
  })
})
