import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { ReadingListReader } from '../components/ReadingListReader'
import { customCBLApi, type ReadingListReader as ReaderView } from '../services/api-custom-cbl'
import { issuesApi } from '../services/api-issues'
import { queryKeys } from '../query/queryKeys'

vi.mock('../services/api-custom-cbl', () => ({ customCBLApi: { getReader: vi.fn() } }))
vi.mock('../services/api-issues', () => ({ issuesApi: { markRead: vi.fn(), markUnread: vi.fn() } }))
vi.mock('../services/api-tags', () => ({ tagsApi: { threadIssuesEffective: vi.fn().mockResolvedValue({ issues: [] }) } }))

const view: ReaderView = {
  list_id: 2, name: 'Julix', mode: 'strict', execution_mode: 'option_e', entries: [
    { id: 1, position: 1, issue_id: 10, thread_id: 1, series_name: 'The Dead Remembered', issue_number: '2', status: 'unread', gate: 'none', skipped: false, is_checkpoint: false, availability: 'available' },
    { id: 2, position: 2, issue_id: 20, thread_id: 2, series_name: 'King of Fear', issue_number: '1', status: 'unread', gate: 'none', is_checkpoint: false, availability: 'blocked', skipped: true,
      explanation: { is_blocked: true, blocking_reasons: [], blocking_dependencies: [
        { issue_id: 10, thread_id: 1, thread_title: 'The Dead Remembered', issue_number: '2', label: 'Strict order in Julix: waiting on The Dead Remembered #2' },
        { issue_id: 30, thread_id: 3, thread_title: 'Starman', issue_number: '55', label: 'Reader prerequisite: waiting on Starman #55' },
      ] } },
  ],
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><ReadingListReader listId={2} /></MemoryRouter></QueryClientProvider>)
  return client
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(customCBLApi.getReader).mockResolvedValue(structuredClone(view))
  vi.mocked(issuesApi.markRead).mockResolvedValue()
  vi.mocked(issuesApi.markUnread).mockResolvedValue()
})

it('shows every blocker, exact issue links and list-local skip without enabling blocked reads', async () => {
  mount()
  expect(await screen.findByText('Julix · Strict order')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open The Dead Remembered issue #2' })).toHaveAttribute('href', '/thread/1?issue=10#issue-10')
  expect(screen.getByRole('link', { name: 'Open Starman issue #55' })).toHaveTextContent('Reader prerequisite: waiting on Starman #55')
  expect(screen.getByText(/Skipped only in this list/)).toBeVisible()
  expect(screen.getAllByRole('button', { name: 'Mark read' })).toHaveLength(1)
})

it('marks the exact offered issue and refreshes the reader plus other eligibility surfaces', async () => {
  const client = mount()
  client.setQueryData(queryKeys.queue.activeCount(), 3)
  await userEvent.click(await screen.findByRole('button', { name: 'Mark read' }))
  await waitFor(() => expect(issuesApi.markRead).toHaveBeenCalledWith(10))
  await waitFor(() => expect(customCBLApi.getReader).toHaveBeenCalledTimes(2))
  expect(client.getQueryState(queryKeys.queue.activeCount())?.isInvalidated).toBe(true)
})

it('leaves the issue unread after a failed write and offers a retry', async () => {
  vi.mocked(issuesApi.markRead).mockRejectedValue(new Error('offline'))
  mount()
  await userEvent.click(await screen.findByRole('button', { name: 'Mark read' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to update this issue')
  expect(screen.getByRole('button', { name: 'Mark read' })).toBeEnabled()
  expect(customCBLApi.getReader).toHaveBeenCalledTimes(1)
})

it('distinguishes failed loads from an empty or inactive list', async () => {
  vi.mocked(customCBLApi.getReader).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ ...view, execution_mode: 'legacy', entries: [] })
  mount()
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load this Reading List')
  await userEvent.click(screen.getByRole('button', { name: 'Retry list' }))
  expect(await screen.findByText('This Reading List is empty.')).toBeVisible()
  expect(screen.getByText(/Reading List execution is not active yet/)).toBeVisible()
})
