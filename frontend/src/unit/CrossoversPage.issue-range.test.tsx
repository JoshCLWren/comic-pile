import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import { dependencyGroupsApi } from '../services/api-dependency-groups'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    delete: vi.fn(),
    addIssueRange: vi.fn(),
  },
}))

const api = vi.mocked(dependencyGroupsApi)

const crossover = {
  id: 7,
  name: 'Annihilation',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [],
}
const secondCrossover = {
  id: 8,
  name: 'Secret Wars',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [],
}

function openRangeForm(name = /Annihilation.*0 members/) {
  fireEvent.click(screen.getByRole('button', { name }))
}

function fillRange(threadId: string, start: string, end: string) {
  fireEvent.change(screen.getByLabelText('Thread ID'), { target: { value: threadId } })
  fireEvent.change(screen.getByLabelText('Start position'), { target: { value: start } })
  fireEvent.change(screen.getByLabelText('End position'), { target: { value: end } })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue([crossover])
})

describe('CrossoversPage issue ranges', () => {
  it('rejects invalid range values before calling the API', async () => {
    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()

    fillRange('0', '3', '2')
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Enter a valid thread ID and an inclusive issue-position range.',
    )
    expect(api.addIssueRange).not.toHaveBeenCalled()
  })

  it('adds a range, refreshes membership totals, and clears the form', async () => {
    api.addIssueRange.mockResolvedValue({
      thread_id: 22,
      start_position: 3,
      end_position: 5,
      added_issue_ids: [31, 32],
      already_present_issue_ids: [33],
    })
    api.get.mockResolvedValue({
      ...crossover,
      memberships: [
        { id: 1, issue_id: 31, thread_id: null },
        { id: 2, issue_id: 32, thread_id: null },
        { id: 3, issue_id: 33, thread_id: null },
      ],
    })

    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    fillRange('22', '3', '5')
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    expect(await screen.findByRole('status')).toHaveTextContent('2 added, 1 already present.')
    expect(api.addIssueRange).toHaveBeenCalledWith(7, 22, 3, 5)
    expect(api.get).toHaveBeenCalledWith(7)
    expect(screen.getByText('3 issue memberships and 0 thread memberships.')).toBeInTheDocument()
    expect(screen.getByLabelText('Thread ID')).toHaveValue('')
    expect(screen.getByLabelText('Start position')).toHaveValue('')
    expect(screen.getByLabelText('End position')).toHaveValue('')
  })

  it('clears range state when expanding another crossover', async () => {
    api.list.mockResolvedValue([crossover, secondCrossover])
    render(<CrossoversPage />)
    await screen.findByText('Annihilation')

    openRangeForm()
    fillRange('22', '3', '5')
    openRangeForm(/Secret Wars.*0 members/)

    expect(screen.getByLabelText('Thread ID')).toHaveValue('')
    expect(screen.getByLabelText('Start position')).toHaveValue('')
    expect(screen.getByLabelText('End position')).toHaveValue('')
    expect(screen.getByRole('form', { name: 'Add issue range to Secret Wars' })).toBeInTheDocument()
  })

  it('prevents moving the pending request state to another crossover', async () => {
    api.list.mockResolvedValue([crossover, secondCrossover])
    api.addIssueRange.mockImplementation(() => new Promise(() => undefined))
    render(<CrossoversPage />)
    await screen.findByText('Annihilation')

    openRangeForm()
    fillRange('22', '3', '5')
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    const secondToggle = screen.getByRole('button', { name: /Secret Wars.*0 members/ })
    expect(secondToggle).toBeDisabled()
    fireEvent.click(secondToggle)
    expect(screen.getByRole('form', { name: 'Add issue range to Annihilation' })).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Add issue range to Secret Wars' })).not.toBeInTheDocument()
  })

  it('disables range controls while saving and reports API failures', async () => {
    let rejectRange: ((reason?: unknown) => void) | undefined
    api.addIssueRange.mockImplementation(
      () => new Promise((_resolve, reject) => { rejectRange = reject }),
    )

    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    fillRange('22', '3', '5')
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    expect(screen.getByRole('button', { name: 'Adding…' })).toBeDisabled()
    expect(screen.getByLabelText('Thread ID')).toBeDisabled()
    rejectRange?.(new Error('Range unavailable'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Range unavailable')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add range' })).toBeEnabled())
  })

  it('clears expanded range state when deleting the expanded crossover', async () => {
    api.delete.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    fillRange('22', '3', '5')
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(7))
    expect(screen.queryByText('Annihilation')).not.toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Add issue range to Annihilation' })).not.toBeInTheDocument()
  })
})
