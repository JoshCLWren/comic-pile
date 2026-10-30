import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { ReadingListReader } from '../components/ReadingListReader'
import { customCBLApi, type ReadingListReader as ReaderView } from '../services/api-custom-cbl'
import { tagsApi } from '../services/api-tags'
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
  vi.mocked(tagsApi.threadIssuesEffective).mockResolvedValue({ thread_id: 1, issues: [] })
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
  expect(screen.getAllByRole('button', { name: 'Read now' })).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: 'Move to front' })).toHaveLength(1)
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

function entryFixture() {
  const entry = view.entries?.[0]
  if (!entry) throw new Error('Reader fixture must contain an issue')
  return entry
}

it('shows read, later, excluded and inactive states without offering unavailable reads', async () => {
  const entry = entryFixture()
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, mode: 'loose', entries: [
    { ...entry, availability: 'read', status: 'read' },
    { ...entry, id: 3, issue_id: 30, availability: 'later' },
    { ...entry, id: 4, issue_id: 40, availability: 'excluded' },
    { ...entry, id: 5, issue_id: 50, availability: 'inactive' },
  ] })
  mount()
  expect(await screen.findByText('Julix · Loose order')).toBeVisible()
  expect(screen.getByText('Read')).toBeVisible()
  expect(screen.getByText('After earlier unread issues in this series')).toBeVisible()
  expect(screen.getByText('Excluded from your collection')).toBeVisible()
  expect(screen.getByText('Series is inactive')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Mark read' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Read now' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Move to front' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
  await waitFor(() => expect(issuesApi.markUnread).toHaveBeenCalledWith(10))
  expect(issuesApi.markRead).not.toHaveBeenCalled()
})

it('keeps legacy unread members visible while withholding direct availability claims', async () => {
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, execution_mode: 'legacy', entries: [
    { ...entryFixture(), availability: 'legacy' },
  ] })
  mount()
  expect(await screen.findByText('Open series for current availability')).toBeVisible()
  expect(screen.getByRole('link', { name: 'The Dead Remembered #2' })).toHaveAttribute('href', '/thread/1')
  expect(screen.queryByRole('button', { name: 'Mark read' })).not.toBeInTheDocument()
})

it('prevents duplicate progress writes while a mutation is pending', async () => {
  let finish: (() => void) | undefined
  vi.mocked(issuesApi.markRead).mockImplementation(() => new Promise<void>((resolve) => { finish = resolve }))
  mount()
  await userEvent.click(await screen.findByRole('button', { name: 'Mark read' }))
  const saving = screen.getByRole('button', { name: 'Saving…' })
  expect(saving).toBeDisabled()
  await userEvent.click(saving)
  expect(issuesApi.markRead).toHaveBeenCalledTimes(1)
  if (!finish) throw new Error('The write must have started')
  await act(async () => { finish?.() })
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Saving…' })).not.toBeInTheDocument())
})

it('keeps read state after a failed mark-unread action', async () => {
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, entries: [
    { ...entryFixture(), availability: 'read', status: 'read' },
  ] })
  vi.mocked(issuesApi.markUnread).mockRejectedValue(new Error('offline'))
  mount()
  await userEvent.click(await screen.findByRole('button', { name: 'Mark unread' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to update this issue')
  expect(screen.getByRole('button', { name: 'Mark unread' })).toBeEnabled()
  expect(issuesApi.markRead).not.toHaveBeenCalled()
  expect(customCBLApi.getReader).toHaveBeenCalledTimes(1)
})

it('keeps progress usable when tags fail to load', async () => {
  vi.mocked(tagsApi.threadIssuesEffective).mockRejectedValue(new Error('tags offline'))
  mount()
  expect((await screen.findAllByText('Tags unavailable.')).length).toBeGreaterThan(0)
  expect(screen.getByRole('button', { name: 'Mark read' })).toBeEnabled()
})

it('shows inherited tags and lets readers inspect their source', async () => {
  const tag = { id: 9, name: 'Physical', normalized_name: 'physical', scope: 'private' as const, owner_user_id: 1, color: '#3B82F6', created_at: '', updated_at: '' }
  vi.mocked(tagsApi.threadIssuesEffective).mockResolvedValue({ thread_id: 1, issues: [{
    target_type: 'Issue', target_id: 10, direct_tags: [], effective_tags: [{
      tag, direct: false, sources: [{ target_type: 'Thread', target_id: 1, display_name: 'The Dead Remembered' }],
    }],
  }] })
  mount()
  expect(await screen.findByText('Physical')).toBeVisible()
  expect(screen.getByText('Inherited')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Show sources for inherited tag Physical' }))
  expect(screen.getByRole('link', { name: 'Open Thread: The Dead Remembered' })).toHaveAttribute('href', '/thread/1?tagEditor=thread')
})
