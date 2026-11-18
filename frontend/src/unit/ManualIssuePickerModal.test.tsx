import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ManualIssuePickerModal from '../pages/RollPage/components/ManualIssuePickerModal'
import type { IssueCard, IssueReadRateResponse } from '../services/issueCardsApi'
import type { IssueListResponse, ThreadListItem, ThreadListResponse } from '../types'
import type { RollBootstrapThread } from '../types/rollBootstrap'
import { cast } from '../utils/cast'

const {
  listThreads,
  listCompleted,
  listExcluded,
  listIssues,
  fetchCards,
  patchIssue,
} = vi.hoisted(() => ({
  listThreads: vi.fn(),
  listCompleted: vi.fn(),
  listExcluded: vi.fn(),
  listIssues: vi.fn(),
  fetchCards: vi.fn(),
  patchIssue: vi.fn(),
}))

vi.mock('../services/api-threads', () => ({
  threadsApi: {
    list: listThreads,
    listCompleted,
    listExcluded,
  },
}))
vi.mock('../services/api-issues', () => ({ issuesApi: { list: listIssues } }))
vi.mock('../services/issueCardsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/issueCardsApi')>()
  return {
    ...actual,
    issueCardsApi: {
      ...actual.issueCardsApi,
      fetchCards,
      patchIssue,
    },
  }
})
vi.mock('../components/ComicIssueMappingAction', () => ({
  default: () => <button type="button">Map comic</button>,
}))

const activeThread = cast<ThreadListItem>({ id: 11, title: 'Active Saga', format: 'Comic', status: 'active' })
const completedThread = cast<ThreadListItem>({ id: 22, title: 'Completed Saga', format: 'Comic', status: 'completed' })
const excludedThread = cast<ThreadListItem>({ id: 33, title: 'Excluded Saga', format: 'Comic', status: 'excluded' })
const snoozedThread = cast<RollBootstrapThread>({ id: 44, title: 'Snoozed Saga', format: 'Comic' })
const issueTwo = {
  id: 92,
  thread_id: 22,
  issue_number: '2',
  status: 'unread' as const,
  position: 1,
  read_at: null,
  created_at: '2026-01-01T00:00:00Z',
}
const issueTen = { ...issueTwo, id: 91, issue_number: '10', position: 2 }
const cardTen: IssueCard = {
  issue_id: 91,
  thread_id: 22,
  thread_title: 'Completed Saga',
  issue_number: '10',
  status: 'unread',
  rating: null,
  mapping_state: 'unmapped',
  has_confirmed_identity: false,
}
const receipt: IssueReadRateResponse = {
  issue: { ...cardTen, status: 'read', rating: 3.5 },
  thread: { thread_id: 22, issues_remaining: 0, status: 'completed' },
  read_event_created: true,
  rating_event_created: true,
  replayed: false,
}

function threadPage(threads: ThreadListItem[]): ThreadListResponse {
  return cast<ThreadListResponse>({ threads, next_page_token: null })
}

function issuePage(issues: Array<typeof issueTwo>, nextPageToken: string | null = null): IssueListResponse {
  return { issues, total_count: issues.length, page_size: 100, next_page_token: nextPageToken }
}

function renderPicker() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ManualIssuePickerModal snoozedThreads={[snoozedThread]} onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listThreads.mockResolvedValue(threadPage([activeThread]))
  listCompleted.mockResolvedValue(threadPage([completedThread]))
  listExcluded.mockResolvedValue(threadPage([excludedThread]))
  listIssues.mockResolvedValue(issuePage([issueTwo, issueTen]))
  fetchCards.mockImplementation(async (issueIds: number[]) => issueIds.map((id) => (
    id === 91 ? cardTen : { ...cardTen, issue_id: id, issue_number: '2' }
  )))
  patchIssue.mockResolvedValue(receipt)
})

describe('Roll exact-issue manual picker (#4445 A38)', () => {
  it('searches every series on demand and opens the shared direct card for the exact issue', async () => {
    const user = userEvent.setup()
    renderPicker()

    const seriesSearch = await screen.findByRole('combobox', { name: 'Series' })
    await waitFor(() => expect(seriesSearch).toBeEnabled())
    expect(listThreads).toHaveBeenCalledExactlyOnceWith({ page_size: 200 }, null)
    expect(listCompleted).toHaveBeenCalledExactlyOnceWith(undefined, undefined, null, 200)
    expect(listExcluded).toHaveBeenCalledExactlyOnceWith(undefined, undefined, null, 200)
    expect(listIssues).not.toHaveBeenCalled()
    expect(fetchCards).not.toHaveBeenCalled()

    await user.click(seriesSearch)
    expect(screen.getByRole('option', { name: /Completed Saga \(Comic\).*Completed/ })).toBeVisible()
    expect(screen.getByRole('option', { name: /Excluded Saga \(Comic\).*Excluded/ })).toBeVisible()
    expect(screen.getByRole('option', { name: /Snoozed Saga \(Comic\).*Snoozed/ })).toBeVisible()
    await user.click(screen.getByRole('option', { name: /Completed Saga \(Comic\).*Completed/ }))
    expect(listIssues).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Find issues' }))
    await waitFor(() => expect(listIssues).toHaveBeenCalledExactlyOnceWith(22, { page_size: 100 }))
    await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([92, 91]))

    const filter = screen.getByRole('searchbox', { name: 'Filter loaded issues' })
    await user.type(filter, '10')
    expect(screen.queryByRole('button', { name: /Completed Saga #2/ })).not.toBeInTheDocument()
    const exactIssue = screen.getByRole('button', {
      name: 'Reading and mapping actions for Completed Saga #10',
    })
    expect(screen.queryByTestId('comic-issue-card')).not.toBeInTheDocument()

    await user.click(exactIssue)
    const sharedCard = await screen.findByTestId('comic-issue-card')
    expect(sharedCard).toHaveAttribute('aria-label', 'Issue Completed Saga #10')
    expect(patchIssue).not.toHaveBeenCalled()

    await user.click(within(sharedCard).getByRole('button', { name: 'Read now' }))
    await user.click(within(sharedCard).getByRole('button', { name: 'Mark read & save' }))
    await waitFor(() => expect(patchIssue).toHaveBeenCalledExactlyOnceWith(91, {
      status: 'read',
      rating: 3.5,
      idempotencyKey: expect.stringMatching(/^direct-[0-9a-f]{32}$/),
    }))
    // No Roll override/pending mutation is imported or called by this flow;
    // the shared receipt explicitly comes from the direct native issue command.
    expect(await within(sharedCard).findByRole('button', { name: 'Mark unread' })).toBeVisible()
  })

  it('loads later issue pages explicitly instead of draining the whole series', async () => {
    const user = userEvent.setup()
    listIssues
      .mockResolvedValueOnce({ ...issuePage([issueTwo], 'next-page'), total_count: 2 })
      .mockResolvedValueOnce({ ...issuePage([issueTen]), total_count: 2 })
    renderPicker()

    const seriesSearch = await screen.findByRole('combobox', { name: 'Series' })
    await waitFor(() => expect(seriesSearch).toBeEnabled())
    await user.click(seriesSearch)
    await user.click(screen.getByRole('option', { name: /Completed Saga/ }))
    await user.click(screen.getByRole('button', { name: 'Find issues' }))

    const loadMore = await screen.findByRole('button', { name: 'Load more issues (1 of 2)' })
    expect(listIssues).toHaveBeenCalledExactlyOnceWith(22, { page_size: 100 })
    await user.click(loadMore)
    await waitFor(() => expect(listIssues).toHaveBeenCalledTimes(2))
    expect(listIssues).toHaveBeenLastCalledWith(22, {
      page_size: 100,
      page_token: 'next-page',
    })
    expect(await screen.findByRole('button', {
      name: 'Reading and mapping actions for Completed Saga #10',
    })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Load more issues/ })).not.toBeInTheDocument()
  })
})
