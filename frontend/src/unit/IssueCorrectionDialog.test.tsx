import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IssueCorrectionDialog, {
  type IssueCorrectionIssuesApi,
} from '../components/IssueCorrectionDialog'
import type { Issue, IssueListResponse } from '../types'

// Injectable fakes passed through the real component props — no module mocking of the API.
const list = vi.fn<IssueCorrectionIssuesApi['list']>()
const create = vi.fn<IssueCorrectionIssuesApi['create']>()
const markRead = vi.fn<IssueCorrectionIssuesApi['markRead']>()
const markUnread = vi.fn<IssueCorrectionIssuesApi['markUnread']>()
const bulkMarkRead = vi.fn<IssueCorrectionIssuesApi['bulkMarkRead']>()
const bulkMarkUnread = vi.fn<IssueCorrectionIssuesApi['bulkMarkUnread']>()
const move = vi.fn<IssueCorrectionIssuesApi['move']>()
const issuesApi: IssueCorrectionIssuesApi = {
  list,
  create,
  markRead,
  markUnread,
  bulkMarkRead,
  bulkMarkUnread,
  move,
}

const issue = (overrides: Partial<Issue> & Pick<Issue, 'id' | 'issue_number'>): Issue => ({
  thread_id: 42,
  status: 'unread',
  read_at: null,
  created_at: '2026-04-17T00:00:00Z',
  ...overrides,
})

const listResponse = (issues: Issue[]): IssueListResponse => ({
  issues,
  total_count: issues.length,
  page_size: 100,
  next_page_token: null,
})

const renderDialog = (props: Partial<Parameters<typeof IssueCorrectionDialog>[0]> = {}) => {
  const onClose = vi.fn()
  const onSuccess = vi.fn()

  render(
    <IssueCorrectionDialog
      isOpen
      threadId={42}
      currentIssueNumber="1"
      totalIssues={3}
      threadTitle="Test Comic"
      onClose={onClose}
      onSuccess={onSuccess}
      issuesApi={issuesApi}
      {...props}
    />
  )

  return { onClose, onSuccess }
}

describe('IssueCorrectionDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    markRead.mockResolvedValue(undefined)
    markUnread.mockResolvedValue(undefined)
    bulkMarkRead.mockResolvedValue(undefined)
    bulkMarkUnread.mockResolvedValue(undefined)
    move.mockResolvedValue(undefined)
  })

  it('accepts an existing non-numeric issue identifier', async () => {
    const issues = [
      issue({ id: 1, issue_number: '1' }),
      issue({ id: 2, issue_number: 'Annual 1', status: 'read' }),
      issue({ id: 3, issue_number: '2' }),
    ]
    list
      .mockResolvedValueOnce(listResponse(issues))
      .mockResolvedValueOnce(listResponse(issues))

    const { onClose, onSuccess } = renderDialog()

    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, 'Annual 1')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))

    await waitFor(() => {
      expect(bulkMarkRead).toHaveBeenCalledWith([1])
    })
    expect(markUnread).toHaveBeenCalledWith(2)
    expect(create).not.toHaveBeenCalled()
    expect(onSuccess).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('creates a missing text issue at the selected position', async () => {
    const initialIssues = [
      issue({ id: 1, issue_number: '1', status: 'read' }),
      issue({ id: 2, issue_number: '2' }),
    ]
    const createdIssue = issue({ id: 3, issue_number: 'Annual 1' })
    const updatedIssues = [initialIssues[0], createdIssue, initialIssues[1]]

    list
      .mockResolvedValueOnce(listResponse(initialIssues))
      .mockResolvedValueOnce(listResponse(updatedIssues))
    create.mockResolvedValueOnce(listResponse([createdIssue]))

    const { onSuccess } = renderDialog()

    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, 'Annual 1')
    await userEvent.selectOptions(screen.getByLabelText(/place new issue/i), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))

    await waitFor(() => {
      expect(create).toHaveBeenCalledWith(42, 'Annual 1', {
        insert_after_issue_id: 1,
      })
    })
    expect(move).not.toHaveBeenCalled()
    expect(onSuccess).toHaveBeenCalledOnce()
  })

  it('retries failed loads and reports update failures', async () => {
    list.mockRejectedValue(new Error('load failed'))
    const { onClose } = renderDialog({ currentIssueNumber: null })
    await waitFor(() => expect(screen.getByText(/multiple attempts/i)).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(list).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Close modal' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('inserts a numeric issue at the beginning and handles missing API results', async () => {
    const existing = [issue({ id: 1, issue_number: '1', status: 'read' })]
    list.mockResolvedValueOnce(listResponse(existing)).mockResolvedValueOnce(listResponse(existing))
    create.mockResolvedValueOnce(listResponse([]))
    const { onSuccess } = renderDialog()
    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, '2')
    await userEvent.selectOptions(screen.getByLabelText(/place new issue/i), 'start')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(screen.getByText(/failed to update issue/i)).toBeInTheDocument())
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('moves a newly created issue to the beginning and marks prior unread issues read', async () => {
    const existing = [issue({ id: 1, issue_number: '1', status: 'unread' })]
    const created = issue({ id: 2, issue_number: '2', status: 'unread' })
    let listCalls = 0
    list.mockImplementation(async () => {
      listCalls += 1
      return listResponse(listCalls === 1 ? existing : [existing[0]!, created])
    })
    create.mockResolvedValueOnce(listResponse([created]))

    renderDialog()
    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, '2')
    await userEvent.selectOptions(screen.getByLabelText(/place new issue/i), 'start')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))

    await waitFor(() => expect(move).toHaveBeenCalledWith(2, null))
    expect(screen.getByText(/failed to update issue/i)).toBeInTheDocument()
  })

  it('supports the numeric stepper boundaries and rejects blank submissions', async () => {
    list.mockResolvedValue(listResponse([issue({ id: 1, issue_number: '1' })]))
    renderDialog({ currentIssueNumber: null, totalIssues: 1 })
    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))
    expect(screen.getByText(/please enter an issue identifier/i)).toBeInTheDocument()

    await userEvent.type(input, '1')
    await userEvent.click(screen.getByRole('button', { name: 'Increase issue number' }))
    expect(input).toHaveValue('1')
    await userEvent.click(screen.getByRole('button', { name: 'Decrease issue number' }))
    expect(input).toHaveValue('1')
  })

  it('paginates issue loading and leaves annual identifiers to text entry', async () => {
    list
      .mockResolvedValueOnce({ ...listResponse([issue({ id: 1, issue_number: '1' })]), next_page_token: 'next' })
      .mockResolvedValueOnce(listResponse([issue({ id: 2, issue_number: 'Annual 1' })]))
    renderDialog({ currentIssueNumber: null, totalIssues: null })
    await screen.findByLabelText(/what issue are you currently on/i)
    expect(list).toHaveBeenCalledTimes(2)
    const input = screen.getByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, 'Annual 1')
    await userEvent.click(screen.getByRole('button', { name: 'Increase issue number' }))
    expect(input).toHaveValue('Annual 1')
  })

  it('reports a missing target after a successful create and stops propagation inside the dialog', async () => {
    const existing = [issue({ id: 1, issue_number: '1' })]
    list.mockResolvedValue(listResponse(existing))
    create.mockResolvedValue(listResponse([issue({ id: 2, issue_number: 'Other' })]))
    const { onClose } = renderDialog()
    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, 'Missing')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(screen.getByText(/failed to update issue/i)).toBeInTheDocument())
    fireEvent.click(screen.getByText('Fix Issue Number'))
    expect(onClose).not.toHaveBeenCalled()
  })
})