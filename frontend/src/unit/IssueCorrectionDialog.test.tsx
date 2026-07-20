import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IssueCorrectionDialog from '../components/IssueCorrectionDialog'
import { issuesApi } from '../services/api-issues'
import type { Issue, IssueListResponse } from '../types'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
    create: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    move: vi.fn(),
  },
}))

const mockedIssuesApi = vi.mocked(issuesApi, { deep: true })

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
      {...props}
    />
  )

  return { onClose, onSuccess }
}

describe('IssueCorrectionDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedIssuesApi.markRead.mockResolvedValue(undefined)
    mockedIssuesApi.markUnread.mockResolvedValue(undefined)
    mockedIssuesApi.move.mockResolvedValue(undefined)
  })

  it('accepts an existing non-numeric issue identifier', async () => {
    const issues = [
      issue({ id: 1, issue_number: '1' }),
      issue({ id: 2, issue_number: 'Annual 1', status: 'read' }),
      issue({ id: 3, issue_number: '2' }),
    ]
    mockedIssuesApi.list
      .mockResolvedValueOnce(listResponse(issues))
      .mockResolvedValueOnce(listResponse(issues))

    const { onClose, onSuccess } = renderDialog()

    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, 'Annual 1')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))

    await waitFor(() => {
      expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(1)
    })
    expect(mockedIssuesApi.markUnread).toHaveBeenCalledWith(2)
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
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

    mockedIssuesApi.list
      .mockResolvedValueOnce(listResponse(initialIssues))
      .mockResolvedValueOnce(listResponse(updatedIssues))
    mockedIssuesApi.create.mockResolvedValueOnce(listResponse([createdIssue]))

    const { onSuccess } = renderDialog()

    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, 'Annual 1')
    await userEvent.selectOptions(screen.getByLabelText(/place new issue/i), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))

    await waitFor(() => {
      expect(mockedIssuesApi.create).toHaveBeenCalledWith(42, 'Annual 1', {
        insert_after_issue_id: 1,
      })
    })
    expect(mockedIssuesApi.move).not.toHaveBeenCalled()
    expect(onSuccess).toHaveBeenCalledOnce()
  })

  it('retries failed loads and reports update failures', async () => {
    mockedIssuesApi.list.mockRejectedValue(new Error('load failed'))
    const { onClose } = renderDialog({ currentIssueNumber: null })
    await waitFor(() => expect(screen.getByText(/multiple attempts/i)).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(mockedIssuesApi.list).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('inserts a numeric issue at the beginning and handles missing API results', async () => {
    const existing = [issue({ id: 1, issue_number: '1', status: 'read' })]
    mockedIssuesApi.list.mockResolvedValueOnce(listResponse(existing)).mockResolvedValueOnce(listResponse(existing))
    mockedIssuesApi.create.mockResolvedValueOnce(listResponse([]))
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
    mockedIssuesApi.list.mockImplementation(async () => {
      listCalls += 1
      return listResponse(listCalls === 1 ? existing : [existing[0]!, created])
    })
    mockedIssuesApi.create.mockResolvedValueOnce(listResponse([created]))

    renderDialog()
    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, '2')
    await userEvent.selectOptions(screen.getByLabelText(/place new issue/i), 'start')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))

    await waitFor(() => expect(mockedIssuesApi.move).toHaveBeenCalledWith(2, null))
    expect(screen.getByText(/failed to update issue/i)).toBeInTheDocument()
  })

  it('supports the numeric stepper boundaries and rejects blank submissions', async () => {
    mockedIssuesApi.list.mockResolvedValue(listResponse([issue({ id: 1, issue_number: '1' })]))
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

  it('reports a missing target after a successful create and stops propagation inside the dialog', async () => {
    const existing = [issue({ id: 1, issue_number: '1' })]
    mockedIssuesApi.list.mockResolvedValue(listResponse(existing))
    mockedIssuesApi.create.mockResolvedValue(listResponse([issue({ id: 2, issue_number: 'Other' })]))
    const { onClose } = renderDialog()
    const input = await screen.findByLabelText(/what issue are you currently on/i)
    await userEvent.clear(input)
    await userEvent.type(input, 'Missing')
    await userEvent.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(screen.getByText(/failed to update issue/i)).toBeInTheDocument())
    fireEvent.click(screen.getByText('Correct Issue Number'))
    expect(onClose).not.toHaveBeenCalled()
  })
})
