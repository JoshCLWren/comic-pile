import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueBulkReadOperations from '../pages/QueuePage/QueueBulkReadOperations'

interface DiscoveredOperation {
  threadId: number
  operation: { id: number; items: unknown[] }
}

// SAFETY: vi.hoisted fixtures run before imports; these typed literals mirror the mocked hook's operation and message contract.
const bulkMocks = vi.hoisted(() => ({
  operations: [] as DiscoveredOperation[],
  message: null as string | null,
  undo: vi.fn(async (_threadId: number, _operationId: number): Promise<void> => undefined),
}))

vi.mock('../hooks/useBulkReadOperations', () => ({
  useBulkReadOperations: () => ({
    operations: bulkMocks.operations,
    message: bulkMocks.message,
    undo: bulkMocks.undo,
  }),
}))

vi.mock('../services/api-issues', () => ({ issuesApi: {} }))

describe('QueueBulkReadOperations', () => {
  beforeEach(() => {
    bulkMocks.operations = []
    bulkMocks.message = null
    bulkMocks.undo.mockClear()
  })

  it('renders nothing when there is no operation and no message', () => {
    const { container } = render(<QueueBulkReadOperations />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a persisted reviewable operation and its undo message', () => {
    bulkMocks.operations = [{ threadId: 42, operation: { id: 7, items: [] } }]
    bulkMocks.message = 'Bulk read undone.'

    render(<QueueBulkReadOperations />)

    expect(screen.getByTestId('bulk-read-operations')).toBeInTheDocument()
    expect(screen.getByText('Reviewable bulk reads')).toBeInTheDocument()
    expect(screen.getByText(/Operation #7 · 0 issues · series 42/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Bulk read undone.')
  })

  it('uses the singular label for a single issue and undoes the exact operation', () => {
    bulkMocks.operations = [{ threadId: 42, operation: { id: 8, items: [{}] } }]

    render(<QueueBulkReadOperations />)

    expect(screen.getByText(/Operation #8 · 1 issue · series 42/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(bulkMocks.undo).toHaveBeenCalledWith(42, 8)
  })
})
