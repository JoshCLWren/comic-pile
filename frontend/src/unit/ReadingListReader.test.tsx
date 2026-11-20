import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { ReadingListReader } from '../components/ReadingListReader'
import { customCBLApi, type ReadingListReader as ReaderView } from '../services/api-custom-cbl'
import { tagsApi } from '../services/api-tags'
import { issuesApi } from '../services/api-issues'
import { queueApi } from '../services/api-queue'
import { issueCardsApi, type IssueCard, type IssueReadRateResponse } from '../services/issueCardsApi'
import { queryKeys } from '../query/queryKeys'

vi.mock('../services/api-custom-cbl', () => ({ customCBLApi: { getReader: vi.fn() } }))
vi.mock('../services/api-issues', () => ({ issuesApi: { markRead: vi.fn(), markUnread: vi.fn() } }))
vi.mock('../services/api-tags', () => ({ tagsApi: { threadIssuesEffective: vi.fn().mockResolvedValue({ issues: [] }) } }))

const view: ReaderView = {
  list_id: 2, name: 'Julix', mode: 'strict', execution_mode: 'option_e', entries: [
    { id: 1, position: 1, issue_id: 10, thread_id: 1, series_name: 'The Dead Remembered', issue_number: '2', status: 'unread', gate: 'none', skipped: false, is_checkpoint: false, availability: 'available', checkpoint_target_issue_ids: [] },
    { id: 2, position: 2, issue_id: 20, thread_id: 2, series_name: 'King of Fear', issue_number: '1', status: 'unread', gate: 'none', is_checkpoint: false, availability: 'blocked', skipped: true, checkpoint_target_issue_ids: [],
      explanation: { is_blocked: true, blocking_reasons: [], blocking_dependencies: [
        { issue_id: 10, thread_id: 1, thread_title: 'The Dead Remembered', issue_number: '2', label: 'Strict order in Julix: waiting on The Dead Remembered #2' },
        { issue_id: 30, thread_id: 3, thread_title: 'Starman', issue_number: '55', label: 'Reader prerequisite: waiting on Starman #55' },
      ] } },
  ],
}
function cardFor(issueId: number): IssueCard {
  if (issueId === 30) {
    return {
      issue_id: 30, thread_id: 3, thread_title: 'Starman', issue_number: '55',
      status: 'unread', rating: null, mapping_state: 'confirmed',
      has_confirmed_identity: true,
      cover_image_url: 'https://comicvine.gamespot.com/starman-55.jpg',
    }
  }
  const entry = view.entries?.find((row) => row.issue_id === issueId) ?? view.entries?.[0]
  if (!entry) throw new Error('Missing fixture')
  return { issue_id: issueId, thread_id: entry.thread_id, thread_title: entry.series_name,
    issue_number: entry.issue_number, status: entry.status, rating: null,
    mapping_state: 'unmapped', has_confirmed_identity: false }
}
function receipt(issueId = 10, status = 'read'): IssueReadRateResponse {
  return { issue: { ...cardFor(issueId), status, rating: 3.5 },
    thread: { thread_id: cardFor(issueId).thread_id, status: 'active', issues_remaining: 1 },
    read_event_created: status === 'read', rating_event_created: status === 'read', replayed: false }
}
const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')
const patchIssue = vi.spyOn(issueCardsApi, 'patchIssue')
const moveToFront = vi.spyOn(queueApi, 'moveToFront')
function firstCard() {
  return within(screen.getAllByTestId('comic-issue-card')[0])
}
async function openFirstEditor() {
  await screen.findByText('Julix · Strict order')
  await userEvent.click(firstCard().getByRole('button', { name: 'Rate / Mark read' }))
}
function mount(backTo?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><ReadingListReader listId={2} backTo={backTo} /></MemoryRouter></QueryClientProvider>)
  return client
}
beforeEach(() => {
  vi.clearAllMocks()
  moveToFront.mockReset()
  moveToFront.mockResolvedValue(undefined)
  fetchCards.mockImplementation(async (ids) => ids.map(cardFor))
  patchIssue.mockImplementation(async (id, input) => receipt(id, input.status ?? 'read'))
  vi.mocked(tagsApi.threadIssuesEffective).mockResolvedValue({ thread_id: 1, issues: [] })
  vi.mocked(customCBLApi.getReader).mockResolvedValue(structuredClone(view))
  vi.mocked(issuesApi.markRead).mockResolvedValue()
  vi.mocked(issuesApi.markUnread).mockResolvedValue()
})

it('shows every blocker, exact issue links and list-local skip while keeping blocked reads actionable', async () => {
  mount()
  expect(await screen.findByText('Julix · Strict order')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open The Dead Remembered issue #2' })).toHaveAttribute('href', '/thread/1?issue=10#issue-10')
  expect(screen.getByRole('link', { name: 'Open Starman issue #55' })).toHaveTextContent('Reader prerequisite: waiting on Starman #55')
  expect(screen.getByText(/Skipped only in this list/)).toBeVisible()
  expect(screen.getAllByRole('button', { name: 'Rate / Mark read' })).toHaveLength(2)
  expect(screen.getAllByRole('button', { name: 'Read now' })).toHaveLength(2)
  expect(screen.getAllByRole('button', { name: 'Move to front' })).toHaveLength(1)
  await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([10, 20, 30]))
})

it('marks the exact offered issue and refreshes the reader plus other eligibility surfaces', async () => {
  const client = mount()
  client.setQueryData(queryKeys.queue.activeCount(), 3)
  await openFirstEditor()
  await userEvent.click(firstCard().getByRole('button', { name: 'Mark read & save' }))
  await waitFor(() => expect(patchIssue).toHaveBeenCalledWith(10, expect.objectContaining({ status: 'read', rating: 3.5, idempotencyKey: expect.any(String) })))
  await waitFor(() => expect(customCBLApi.getReader).toHaveBeenCalledTimes(2))
  expect(client.getQueryState(queryKeys.queue.activeCount())?.isInvalidated).toBe(true)
})

it('leaves the issue unread after a failed write and offers a retry', async () => {
  patchIssue.mockRejectedValueOnce(new Error('offline'))
  mount()
  await openFirstEditor()
  await userEvent.click(firstCard().getByRole('button', { name: 'Mark read & save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('offline')
  expect(firstCard().getByRole('button', { name: 'Mark read & save' })).toBeEnabled()
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

it('shows read, later, excluded and inactive states with manual reading available', async () => {
  const entry = entryFixture()
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, mode: 'loose', entries: [
    { ...entry, availability: 'read', status: 'read' },
    { ...entry, id: 3, issue_id: 30, availability: 'later' },
    { ...entry, id: 4, issue_id: 40, availability: 'excluded' },
    { ...entry, id: 5, issue_id: 50, availability: 'inactive' },
  ] })
  fetchCards.mockImplementation(async (ids) => ids.map((id) => ({ ...cardFor(id), status: id === 10 ? 'read' : 'unread' })))
  mount()
  expect(await screen.findByText('Julix · Loose order')).toBeVisible()
  expect(screen.getAllByText('Read').length).toBeGreaterThan(0)
  expect(screen.getByText('After earlier unread issues in this series')).toBeVisible()
  expect(screen.getByText('Excluded from your collection')).toBeVisible()
  expect(screen.getByText('Series is inactive')).toBeVisible()
  expect(screen.getAllByRole('button', { name: 'Rate / Mark read' }).length).toBeGreaterThan(0)
  expect(screen.getAllByRole('button', { name: 'Read now' })).toHaveLength(3)
  expect(screen.queryByRole('button', { name: 'Move to front' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
  await waitFor(() => expect(patchIssue).toHaveBeenCalledWith(10, expect.objectContaining({ status: 'unread' })))
  expect(issuesApi.markRead).not.toHaveBeenCalled()
})

it('keeps legacy unread members visible while withholding direct availability claims', async () => {
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, execution_mode: 'legacy', entries: [
    { ...entryFixture(), availability: 'legacy' },
  ] })
  mount()
  expect(await screen.findByText('Open series for current availability')).toBeVisible()
  expect(screen.getByRole('link', { name: 'The Dead Remembered #2' })).toHaveAttribute('href', '/thread/1')
  expect(screen.getAllByRole('button', { name: 'Rate / Mark read' }).length).toBeGreaterThan(0)
})

it('prevents duplicate progress writes while a mutation is pending', async () => {
  let finish: (() => void) | undefined
  patchIssue.mockImplementation(() => new Promise<IssueReadRateResponse>((resolve) => { finish = () => resolve(receipt()) }))
  mount()
  await openFirstEditor()
  await userEvent.click(firstCard().getByRole('button', { name: 'Mark read & save' }))
  const saving = screen.getByRole('button', { name: 'Saving…' })
  expect(saving).toBeDisabled()
  await userEvent.click(saving)
  expect(patchIssue).toHaveBeenCalledTimes(1)
  if (!finish) throw new Error('The write must have started')
  await act(async () => { finish?.() })
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Saving…' })).not.toBeInTheDocument())
})

it('keeps read state after a failed mark-unread action', async () => {
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, entries: [
    { ...entryFixture(), availability: 'read', status: 'read' },
  ] })
  fetchCards.mockResolvedValue([{ ...cardFor(10), status: 'read', rating: 4 }])
  patchIssue.mockRejectedValueOnce(new Error('offline'))
  mount()
  await userEvent.click(await screen.findByRole('button', { name: 'Mark unread' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('offline')
  expect(screen.getByRole('button', { name: 'Mark unread' })).toBeEnabled()
  expect(issuesApi.markRead).not.toHaveBeenCalled()
  expect(customCBLApi.getReader).toHaveBeenCalledTimes(1)
})

it('keeps progress usable when tags fail to load', async () => {
  vi.mocked(tagsApi.threadIssuesEffective).mockRejectedValue(new Error('tags offline'))
  mount()
  expect((await screen.findAllByText('Tags unavailable.')).length).toBeGreaterThan(0)
  expect(firstCard().getByRole('button', { name: 'Rate / Mark read' })).toBeEnabled()
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

it('retries moving the visible series to the front after an explicit queue write error', async () => {
  moveToFront.mockRejectedValueOnce(new Error('queue offline'))
  mount()
  const available = await screen.findByRole('button', { name: 'Move to front' })
  await userEvent.click(available)
  expect(await screen.findByRole('alert')).toHaveTextContent('queue offline')
  expect(moveToFront).toHaveBeenCalledExactlyOnceWith(1)
  expect(screen.getAllByRole('button', { name: 'Read now' })).toHaveLength(2)
  await userEvent.click(screen.getByRole('button', { name: 'Move to front' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Moved to front' })).toBeVisible())
  expect(moveToFront).toHaveBeenCalledTimes(2)
  expect(patchIssue).not.toHaveBeenCalled()
})

it('shows a safe default queue error for an unhelpful rejection without disabling the reader', async () => {
  moveToFront.mockRejectedValueOnce(new Error(''))
  mount()
  await userEvent.click(await screen.findByRole('button', { name: 'Move to front' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to move this series to the front.')
  expect(screen.getAllByRole('button', { name: 'Rate / Mark read' })).toHaveLength(2)
  expect(patchIssue).not.toHaveBeenCalled()
})

it('shows a single bounded card-load failure and restores issue-specific covers after retry', async () => {
  fetchCards.mockRejectedValueOnce(new Error('metadata offline')).mockResolvedValueOnce([
    { ...cardFor(10), cover_image_url: 'https://comicvine.gamespot.com/issue-10.jpg', rating: 4 },
    { ...cardFor(20), cover_image_url: 'https://comicvine.gamespot.com/issue-20.jpg' },
    cardFor(30),
  ])
  mount()
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load issue cards.')
  expect(fetchCards).toHaveBeenCalledExactlyOnceWith([10, 20, 30])
  expect(screen.getAllByRole('button', { name: 'Read now' })).toHaveLength(2)
  await userEvent.click(screen.getByRole('button', { name: 'Retry cards' }))
  await waitFor(() => expect(fetchCards).toHaveBeenCalledTimes(2))
  expect(await within(firstCard().getByTestId('comic-issue-cover')).findByRole('img', { name: 'Cover for The Dead Remembered #2' })).toHaveAttribute(
    'src', 'https://comicvine.gamespot.com/issue-10.jpg',
  )
  expect(screen.getByRole('img', { name: 'Cover for King of Fear #1' })).toHaveAttribute(
    'src', 'https://comicvine.gamespot.com/issue-20.jpg',
  )
})

it('does not guess an issue ID or fetch an issue cover for thread-only prerequisites', async () => {
  vi.mocked(customCBLApi.getReader).mockResolvedValue({
    ...view,
    entries: (view.entries ?? []).map((entry) => entry.issue_id !== 20 ? entry : {
      ...entry,
      explanation: {
        ...entry.explanation,
        is_blocked: true,
        blocking_reasons: [],
        blocking_dependencies: [
          { thread_id: 3, thread_title: 'Starman', issue_number: '55', label: 'Reader prerequisite: Starman #55' },
          { issue_id: 10, thread_id: 1, thread_title: 'The Dead Remembered', issue_number: '2', label: 'Strict order: The Dead Remembered #2' },
        ],
      },
    }),
  })
  mount('/queue')
  expect(await screen.findByText('Julix · Strict order')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open Starman' })).toHaveAttribute('href', '/thread/3')
  expect(screen.queryByRole('button', { name: 'Reading and mapping actions for Starman #55' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reading and mapping actions for The Dead Remembered #2' })).toBeEnabled()
  await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([10, 20]))
})

it('renders a safe empty list when a stale reader response omits entries', async () => {
  // Preserve the generated response type while modeling a stale server
  // payload that omitted `entries`. Do not weaken the runtime boundary.
  const missingEntries = Object.assign({}, view, { entries: undefined })
  vi.mocked(customCBLApi.getReader).mockResolvedValue(missingEntries)
  mount()
  expect(await screen.findByText('This Reading List is empty.')).toBeVisible()
  expect(screen.getByText('Julix · Strict order')).toBeVisible()
  expect(fetchCards).not.toHaveBeenCalled()
  expect(screen.queryByTestId('comic-issue-card')).not.toBeInTheDocument()
})
