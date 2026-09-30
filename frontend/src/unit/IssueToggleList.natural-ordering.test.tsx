/**
 * Edit Series must place newly added issues in natural order instead of always
 * appending, while still persisting through the existing create/reorder paths.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type { IssueToggleListApi, IssueToggleListDependenciesApi } from '../pages/QueuePage/IssueToggleList'
import type { Issue, IssueListResponse } from '../types'

const mockedIssuesApi = {
  list: vi.fn<IssueToggleListApi['list']>(),
  create: vi.fn<IssueToggleListApi['create']>(),
  markRead: vi.fn<IssueToggleListApi['markRead']>(),
  markUnread: vi.fn<IssueToggleListApi['markUnread']>(),
  delete: vi.fn<IssueToggleListApi['delete']>(),
  reorder: vi.fn<IssueToggleListApi['reorder']>(),
}

const mockedIssueDependenciesApi = {
  listForThread: vi.fn<IssueToggleListDependenciesApi['listForThread']>(),
}

const issue = (id: number, issueNumber: string): Issue => ({
  id,
  thread_id: 1,
  issue_number: issueNumber,
  status: 'unread',
  read_at: null,
  created_at: '2023-01-01T00:00:00Z',
})

function buildListResponse(issues: Issue[]): IssueListResponse {
  return {
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: null,
  }
}

function mockThread(issues: Issue[]): void {
  mockedIssuesApi.list.mockResolvedValue(buildListResponse(issues))
}

async function renderList(): Promise<void> {
  render(
    <IssueToggleList
      threadId={1}
      issuesApi={mockedIssuesApi}
      dependenciesApi={mockedIssueDependenciesApi}
    />,
  )
  await screen.findByTestId('issue-add-input')
}

async function addIssues(issueRange: string): Promise<void> {
  fireEvent.change(screen.getByTestId('issue-add-input'), { target: { value: issueRange } })
  fireEvent.click(screen.getByTestId('issue-add-button'))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedIssuesApi.create.mockResolvedValue(buildListResponse([]))
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssueDependenciesApi.listForThread.mockResolvedValue({ thread_id: 1, issues: [] })
})

describe('IssueToggleList natural issue ordering', () => {
  it('creates the reported #2 ahead of #33, #34, #35 without a stray append', async () => {
    mockThread([issue(1, '33'), issue(2, '34'), issue(3, '35')])
    mockedIssuesApi.create.mockResolvedValue(buildListResponse([issue(4, '2')]))

    await renderList()
    await addIssues('2')

    await waitFor(() => expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, '2'))
    // The create contract appends, so the canonical reorder path moves it to the top.
    await waitFor(() =>
      expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(1, [4, 1, 2, 3]),
    )
  })

  it('anchors an unambiguous addition between surrounding issue numbers', async () => {
    mockThread([issue(1, '1'), issue(2, '3')])
    mockedIssuesApi.create.mockResolvedValue(buildListResponse([issue(3, '2')]))

    await renderList()
    await addIssues('2')

    await waitFor(() =>
      expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, '2', { insert_after_issue_id: 1 }),
    )
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
  })

  it('places a natural-order range deterministically regardless of typed order', async () => {
    mockThread([issue(1, '1'), issue(2, '2'), issue(3, '3')])

    await renderList()
    await addIssues('5, 4')

    await waitFor(() =>
      expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, '5, 4', { insert_after_issue_id: 3 }),
    )
  })

  it('does not anchor on issue numbers that already exist in the thread', async () => {
    mockThread([issue(1, '1'), issue(2, '2'), issue(3, '3')])

    await renderList()
    await addIssues('2-5')

    await waitFor(() =>
      expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, '2-5', { insert_after_issue_id: 3 }),
    )
  })

  it('appends an irregular identifier and leaves the manual reorder control to the reader', async () => {
    mockThread([issue(1, '1'), issue(2, '2')])
    mockedIssuesApi.create.mockResolvedValue(buildListResponse([issue(3, 'Annual 1')]))

    await renderList()
    await addIssues('Annual 1')

    await waitFor(() => expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, 'Annual 1'))
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
  })

  it('appends issue 0 rather than faking numeric order for it', async () => {
    mockThread([issue(1, '1'), issue(2, '2')])

    await renderList()
    await addIssues('0')

    await waitFor(() => expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, '0'))
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
  })

  it('supports a manual non-numeric reorder through the accessible move controls', async () => {
    // A reader who wants an intentional non-numeric order places the run by hand.
    mockThread([issue(1, '1'), issue(2, '2'), issue(3, '3')])

    await renderList()
    fireEvent.click(screen.getByTestId('issue-move-up-3'))

    await waitFor(() => expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(1, [1, 3, 2]))
    await waitFor(() => expect(screen.getByText('Moved issue #3 up.')).toBeInTheDocument())
  })

  it('exposes the reorder controls on narrow viewports as well as desktop', async () => {
    mockThread([issue(1, '33'), issue(2, '34'), issue(3, '35')])

    await renderList()

    // Reordering must not depend on precision drag gestures, so the up/down
    // controls are present at every breakpoint rather than only from `md` up.
    expect(screen.getByRole('button', { name: 'Move issue #34 up' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Move issue #33 up' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move issue #35 down' })).toBeDisabled()

    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    await waitFor(() => expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(1, [2, 1, 3]))
    await waitFor(() => expect(screen.getByTestId('issue-move-down-1')).toHaveFocus())
  })

  it('surfaces an invalid range without issuing a create request', async () => {
    mockThread([issue(1, '1')])

    await renderList()
    await addIssues('5-2')

    await waitFor(() =>
      expect(screen.getByText(/cannot exceed/i)).toBeInTheDocument(),
    )
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
  })
})
