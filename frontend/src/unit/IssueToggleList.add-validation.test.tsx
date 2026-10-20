import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type {
  IssueToggleListApi,
  IssueToggleListDependenciesApi,
  IssueToggleListHandle,
} from '../pages/QueuePage/IssueToggleList'
import type { Issue, IssueListResponse } from '../types'

/**
 * Regression coverage for #3586 (consolidating #3633): the Edit Series Add
 * box must reject input that is not an issue instead of staging a phantom
 * pending issue chip that is one Save away from becoming a real record.
 *
 * The Add box is shared by the Queue page Edit Series dialog and the thread
 * page Edit Series dialog, so covering the component covers both surfaces.
 */

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

const BASE_ISSUES: Issue[] = [
  {
    id: 1,
    thread_id: 99,
    issue_number: '1',
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  },
  {
    id: 2,
    thread_id: 99,
    issue_number: '2',
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  },
]

function buildListResponse(
  issues: Issue[] = BASE_ISSUES,
  nextPageToken: string | null = null
): IssueListResponse {
  return {
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: nextPageToken,
  }
}

async function renderDeferred() {
  const ref = createRef<IssueToggleListHandle>()
  render(
    <IssueToggleList
      ref={ref}
      threadId={99}
      deferred
      issuesApi={mockedIssuesApi}
      dependenciesApi={mockedIssueDependenciesApi}
    />,
  )
  await waitFor(() => {
    expect(screen.getAllByTestId(/issue-pill-/).length).toBeGreaterThan(0)
  })
  return ref
}

async function renderImmediate() {
  render(
    <IssueToggleList
      threadId={99}
      issuesApi={mockedIssuesApi}
      dependenciesApi={mockedIssueDependenciesApi}
    />,
  )
  await waitFor(() => {
    expect(screen.getAllByTestId(/issue-pill-/).length).toBeGreaterThan(0)
  })
}

beforeEach(() => {
  vi.clearAllMocks()

  mockedIssuesApi.list.mockResolvedValue(buildListResponse())
  mockedIssuesApi.create.mockResolvedValue(buildListResponse([]))
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssueDependenciesApi.listForThread.mockResolvedValue({
    thread_id: 99,
    issues: [],
  })
})

describe('IssueToggleList Add box validation (#3586)', () => {
  it.each([
    ['non-numeric garbage', 'abc'],
    ['a negative issue number', '-3'],
    ['a zero-width space', '\u200b'],
    ['a bare hyphen', '-'],
  ])('refuses to stage %s as a pending issue chip', async (_label, value) => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    expect(screen.queryByTestId('pending-creates')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(false)
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
    expect(screen.getByTestId('issue-add-validation-error')).toBeInTheDocument()
  })

  it('disables the Add button and explains why the entry is not an issue', async () => {
    await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: 'abc' } })

    expect(screen.getByTestId('issue-add-button')).toBeDisabled()
    const error = screen.getByTestId('issue-add-validation-error')
    expect(error).toHaveTextContent("'abc' is not a valid issue number")
    expect(error).toHaveTextContent('Enter an issue number or range')
  })

  it('associates the validation error with the entry field', async () => {
    await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: 'abc' } })

    expect(input).toHaveAttribute('aria-invalid', 'true')
    const describedBy = input.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(document.getElementById(describedBy!)).toHaveTextContent(
      "'abc' is not a valid issue number",
    )
  })

  it('clears the validation error once the entry becomes a valid issue', async () => {
    await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: 'abc' } })
    expect(screen.getByTestId('issue-add-validation-error')).toBeInTheDocument()

    fireEvent.change(input, { target: { value: '19-24' } })

    expect(screen.queryByTestId('issue-add-validation-error')).not.toBeInTheDocument()
    expect(screen.getByTestId('issue-add-button')).not.toBeDisabled()
  })

  it('never sends an invalid entry to the server in immediate mode', async () => {
    await renderImmediate()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: 'abc' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
    expect(screen.queryByTestId('pending-creates')).not.toBeInTheDocument()
  })

  it('ignores an invalid entry submitted with Enter', async () => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: 'abc' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(ref.current?.hasPendingMutations()).toBe(false)
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
    expect(screen.queryByTestId('pending-creates')).not.toBeInTheDocument()
  })

  it('stages a numeric range as a pending issue chip', async () => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: '19-24' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    expect(screen.getByTestId('pending-creates')).toHaveTextContent('19-24')
    expect(ref.current?.hasPendingMutations()).toBe(true)

    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.create).toHaveBeenCalledWith(99, '19-24')
  })

  it('stages a named issue such as Annual 1 as a pending issue chip', async () => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: 'Annual 1' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    expect(screen.getByTestId('pending-creates')).toHaveTextContent('Annual 1')

    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.create).toHaveBeenCalledWith(99, 'Annual 1')
  })

  it('keeps a whitespace-only entry from staging a chip', async () => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: '   ' } })

    expect(screen.getByTestId('issue-add-button')).toBeDisabled()
    expect(screen.queryByTestId('pending-creates')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(false)
  })

  it('discards the draft when the dialog closes without saving', async () => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: '19-24' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    expect(ref.current?.hasPendingMutations()).toBe(true)

    cleanup()

    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
  })
})
