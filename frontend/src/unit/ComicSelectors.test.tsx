import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
  ContinuityIssueRangeSelector,
  ContinuityIssueSelector,
  ContinuityThreadSelector,
} from '../components/continuity/ComicSelectors'
import type { Issue, Thread } from '../types'

const threads = [
  { id: 1, title: 'Alpha Flight', format: 'ongoing' },
  { id: 2, title: 'New Mutants', format: 'ongoing' },
] as Thread[]
const thread = threads[0]

const issues = [
  { id: 11, issue_number: 'Annual 1' },
  { id: 12, issue_number: '1/2' },
  { id: 13, issue_number: 'Omega' },
] as Issue[]

describe('continuity comic selectors', () => {
  it('searches threads by human-readable title and returns the selected thread object', () => {
    const onChange = vi.fn()
    render(<ContinuityThreadSelector threads={threads} value={null} onChange={onChange} />)

    const search = screen.getByRole('searchbox')
    fireEvent.change(search, { target: { value: 'mutants' } })

    expect(screen.queryByText('Alpha Flight')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('option', { name: /New Mutants/i }))
    expect(onChange).toHaveBeenCalledWith(threads[1])
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

    search.focus()
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
        error="Could not load comics"
      />,
    )
    expect(screen.getByText('Could not load comics')).toBeInTheDocument()

    rerender(
      <ContinuityThreadSelector threads={threads} value={null} onChange={onChange} disabled />,
    )
    expect(screen.getByRole('searchbox')).toBeDisabled()
  })

  it('syncs the thread search text when the selected value changes', () => {
    const { rerender } = render(
      <ContinuityThreadSelector threads={threads} value={threads[0]} onChange={vi.fn()} />,
    )
    expect(screen.getByRole('searchbox')).toHaveValue('Alpha Flight')

    rerender(<ContinuityThreadSelector threads={threads} value={threads[1]} onChange={vi.fn()} />)
    expect(screen.getByRole('searchbox')).toHaveValue('New Mutants')
  })

  it('selects arbitrary human-facing issue identifiers without numeric parsing', () => {
    const onChange = vi.fn()
    render(<ContinuityIssueSelector issues={issues} value={null} onChange={onChange} />)

    fireEvent.change(screen.getByRole('combobox'), { target: { value: '13' } })
    expect(onChange).toHaveBeenCalledWith(issues[2])
    expect(screen.getByRole('option', { name: '#Omega' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '#Annual 1' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '#1/2' })).toBeInTheDocument()
  })

  it('covers issue loading, empty, error, disabled, and cleared-selection states', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <ContinuityIssueSelector issues={issues} value={issues[0]} onChange={onChange} />,
    )
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith(null)

    rerender(<ContinuityIssueSelector issues={[]} value={null} onChange={onChange} isLoading />)
    expect(screen.getByText('Loading issues…')).toBeInTheDocument()

    rerender(
      <ContinuityIssueSelector issues={[]} value={null} onChange={onChange} error="Issue load failed" />,
    )
    expect(screen.getByText('Issue load failed')).toBeInTheDocument()

    rerender(<ContinuityIssueSelector issues={[]} value={null} onChange={onChange} />)
    expect(screen.getByText('No issues available')).toBeInTheDocument()

    rerender(<ContinuityIssueSelector issues={issues} value={null} onChange={onChange} disabled />)
    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  it('builds ordered ranges from issue labels and rejects reversed order without exposing positions', () => {
    const onChange = vi.fn()
    render(
      <ContinuityIssueRangeSelector
        thread={thread}
        issues={issues}
        value={null}
        onChange={onChange}
      />,
    )

    const [start, end] = screen.getAllByRole('combobox')
    fireEvent.change(start, { target: { value: '11' } })
    fireEvent.change(end, { target: { value: '13' } })

    expect(onChange).toHaveBeenLastCalledWith({
      thread,
      startIssue: issues[0],
      endIssue: issues[2],
    })
    expect(screen.queryByText(/position/i)).not.toBeInTheDocument()

    fireEvent.change(start, { target: { value: '13' } })
    fireEvent.change(end, { target: { value: '11' } })
    expect(screen.getByRole('alert')).toHaveTextContent('#Omega comes after #Annual 1')
    expect(onChange).toHaveBeenLastCalledWith(null)
  })

  it('publishes null for incomplete ranges and resyncs draft values from props', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <ContinuityIssueRangeSelector
        thread={thread}
        issues={issues}
        value={{ thread, startIssue: issues[0], endIssue: issues[2] }}
        onChange={onChange}
      />,
    )
    const [start, end] = screen.getAllByRole('combobox')
    expect(start).toHaveValue('11')
    expect(end).toHaveValue('13')

    fireEvent.change(end, { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith(null)

    rerender(
      <ContinuityIssueRangeSelector
        thread={thread}
        issues={issues}
        value={{ thread, startIssue: issues[1], endIssue: issues[2] }}
        onChange={onChange}
      />,
    )
    const [resyncedStart, resyncedEnd] = screen.getAllByRole('combobox')
    expect(resyncedStart).toHaveValue('12')
    expect(resyncedEnd).toHaveValue('13')
  })
})
