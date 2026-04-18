import { render, screen, waitFor } from '@testing-library/react'
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
})
