import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { ReadingListReader } from '../components/ReadingListReader'
import { customCBLApi, type ReadingListReader as ReaderView } from '../services/api-custom-cbl'
import { tagsApi } from '../services/api-tags'
import { queryKeys } from '../query/queryKeys'
import type { IssueReadRateResponse } from '../services/issueCardsApi'

const { patchIssueSpy, fetchCardsSpy } = vi.hoisted(() => ({
  patchIssueSpy: vi.fn(),
  fetchCardsSpy: vi.fn(),
}))

vi.mock('../services/api-custom-cbl', () => ({ customCBLApi: { getReader: vi.fn() } }))
vi.mock('../services/issueCardsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/issueCardsApi')>()
  return { ...actual, issueCardsApi: { fetchCards: fetchCardsSpy, patchIssue: patchIssueSpy } }
})
vi.mock('../services/api-tags', () => ({ tagsApi: { threadIssuesEffective: vi.fn().mockResolvedValue({ issues: [] }) } }))
vi.mock('../services/api-comicvine', () => ({
  comicVineApi: {
    searchSeries: vi.fn().mockResolvedValue({ results: [] }),
    getSeriesIssues: vi.fn().mockResolvedValue({ comicvine_volume_id: 42, series_name: '', issues: [] }),
    getIssueIntelligence: vi.fn().mockResolvedValue(null),
    getIssueIdentity: vi.fn().mockResolvedValue({
      issue_id: 10, thread_id: 1, thread_title: 'The Dead Remembered',
      has_confirmed_identity: false, comicvine_issue_id: null,
      confirmed_mappings: [], candidate_mappings: [], has_unresolved: false,
    }),
    confirmIdentity: vi.fn(), replaceIdentity: vi.fn(), removeIdentity: vi.fn(), refreshMetadata: vi.fn(),
  },
}))

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

function writeResponse(issueId: number): IssueReadRateResponse {
  return {
    issue: {
      issue_id: issueId, thread_id: 1, thread_title: 'The Dead Remembered', issue_number: '2',
      status: 'read', read_at: '2026-10-01T00:00:00.000Z', rating: 3.5,
      has_confirmed_identity: false, mapping_state: 'unmapped', comicvine_issue_id: null, cover_image_url: null,
    },
    thread: { thread_id: 1, status: 'active', issues_remaining: 5, next_unread_issue_id: null, reading_progress: null, last_rating: 3.5 },
    read_event_created: true, rating_event_created: true, replayed: false, final_rating: 3.5, die_after: null,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(tagsApi.threadIssuesEffective).mockResolvedValue({ thread_id: 1, issues: [] })
  vi.mocked(customCBLApi.getReader).mockResolvedValue(structuredClone(view))
  fetchCardsSpy.mockResolvedValue([])
  patchIssueSpy.mockImplementation(async (issueId: number) => writeResponse(issueId))
})

it('shows every blocker, exact issue links and list-local skip; blocked reads stay actionable', async () => {
  mount()
  expect(await screen.findByText('Julix · Strict order')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open The Dead Remembered issue #2' })).toHaveAttribute('href', '/thread/1?issue=10#issue-10')
  expect(screen.getByRole('link', { name: 'Open Starman issue #55' })).toHaveTextContent('Reader prerequisite: waiting on Starman #55')
  expect(screen.getByText(/Skipped only in this list/)).toBeVisible()
  // The blocked entry keeps the same direct controls; availability is advisory.
  expect(screen.getAllByRole('button', { name: 'Read now' })).toHaveLength(2)
  expect(screen.getAllByRole('button', { name: 'Move to front' })).toHaveLength(1)
})

it('marks the exact offered issue and refreshes the reader plus other eligibility surfaces', async () => {
  const client = mount()
  client.setQueryData(queryKeys.queue.activeCount(), 3)
  const card = await screen.findByLabelText('Issue The Dead Remembered #2')
  await userEvent.click(within(card).getByRole('button', { name: 'Read now' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Mark read & save' }))
  await waitFor(() => expect(patchIssueSpy).toHaveBeenCalledWith(10, expect.objectContaining({ status: 'read' })))
  await waitFor(() => expect(customCBLApi.getReader).toHaveBeenCalledTimes(2))
  expect(client.getQueryState(queryKeys.queue.activeCount())?.isInvalidated).toBe(true)
})

it('leaves the issue unread after a failed write and offers a retry', async () => {
  patchIssueSpy.mockRejectedValueOnce(new Error('offline'))
  mount()
  const card = await screen.findByLabelText('Issue The Dead Remembered #2')
  await userEvent.click(within(card).getByRole('button', { name: 'Read now' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Mark read & save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('offline')
  expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled()
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

it('shows read, later, excluded and inactive states with advisory-only availability', async () => {
  const entry = entryFixture()
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, mode: 'loose', entries: [
    { ...entry, availability: 'read', status: 'read' },
    { ...entry, id: 3, issue_id: 30, availability: 'later' },
    { ...entry, id: 4, issue_id: 40, availability: 'excluded' },
    { ...entry, id: 5, issue_id: 50, availability: 'inactive' },
  ] })
  mount()
  expect(await screen.findByText('Julix · Loose order')).toBeVisible()
  const explanations = screen.getAllByTestId('eligibility-explanation')
  expect(explanations.map((el) => el.textContent)).toContainEqual(expect.stringContaining('Read'))
  expect(explanations.map((el) => el.textContent)).toContainEqual(expect.stringContaining('After earlier unread issues in this series'))
  expect(explanations.map((el) => el.textContent)).toContainEqual(expect.stringContaining('Excluded from your collection'))
  expect(explanations.map((el) => el.textContent)).toContainEqual(expect.stringContaining('Series is inactive'))
  // Every owned issue keeps its direct controls, even when unavailable.
  expect(screen.getAllByRole('button', { name: 'Read now' })).toHaveLength(3)
  expect(screen.queryByRole('button', { name: 'Move to front' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
  await waitFor(() => expect(patchIssueSpy).toHaveBeenCalledWith(10, expect.objectContaining({ status: 'unread' })))
})

it('keeps legacy unread members visible with the same direct controls', async () => {
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, execution_mode: 'legacy', entries: [
    { ...entryFixture(), availability: 'legacy' },
  ] })
  mount()
  expect(await screen.findByText('Open series for current availability')).toBeVisible()
  expect(screen.getByRole('link', { name: 'The Dead Remembered #2' })).toHaveAttribute('href', '/thread/1')
  expect(screen.getByRole('button', { name: 'Read now' })).toBeEnabled()
})

it('prevents duplicate progress writes while a mutation is pending', async () => {
  let finish: (() => void) | undefined
  patchIssueSpy.mockImplementation(() => new Promise<IssueReadRateResponse>((resolve) => { finish = () => resolve(writeResponse(10)) }))
  mount()
  const card = await screen.findByLabelText('Issue The Dead Remembered #2')
  await userEvent.click(within(card).getByRole('button', { name: 'Read now' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Mark read & save' }))
  const saving = screen.getByRole('button', { name: 'Saving…' })
  expect(saving).toBeDisabled()
  await userEvent.click(saving)
  expect(patchIssueSpy).toHaveBeenCalledTimes(1)
  if (!finish) throw new Error('The write must have started')
  await act(async () => { finish?.() })
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Saving…' })).not.toBeInTheDocument())
})

it('keeps read state after a failed mark-unread action', async () => {
  vi.mocked(customCBLApi.getReader).mockResolvedValue({ ...view, entries: [
    { ...entryFixture(), availability: 'read', status: 'read' },
  ] })
  patchIssueSpy.mockRejectedValue(new Error('offline'))
  mount()
  await userEvent.click(await screen.findByRole('button', { name: 'Mark unread' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('offline')
  expect(screen.getByRole('button', { name: 'Mark unread' })).toBeEnabled()
  expect(patchIssueSpy).toHaveBeenCalledWith(10, expect.objectContaining({ status: 'unread' }))
  expect(customCBLApi.getReader).toHaveBeenCalledTimes(1)
})

it('keeps progress usable when tags fail to load', async () => {
  vi.mocked(tagsApi.threadIssuesEffective).mockRejectedValue(new Error('tags offline'))
  mount()
  expect((await screen.findAllByText('Tags unavailable.')).length).toBeGreaterThan(0)
  const card = await screen.findByLabelText('Issue The Dead Remembered #2')
  expect(within(card).getByRole('button', { name: 'Read now' })).toBeEnabled()
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

it('reads one batched card projection for the visible entries', async () => {
  mount()
  await screen.findByText('Julix · Strict order')
  await waitFor(() => expect(fetchCardsSpy).toHaveBeenCalledWith([10, 20]))
})
