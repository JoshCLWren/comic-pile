/**
 * Issue #4822: History must show the actions that actually changed the die.
 *
 * The production defect showed a d6 roll followed by a d8 roll with no
 * intervening snooze, because History read legacy session summaries filtered to
 * session-linked rows. The native `GET /api/v2/activity` resource owns the
 * causal stream now; this test drives the real History page + activity hook
 * against the exact November 8, 2026 sequence (America/Chicago 09:42–10:01)
 * that the reader reported.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import type { ActivityItem } from '../services/api-activity'
import { issueCardsApi } from '../services/issueCardsApi'

const listMock = vi.hoisted(() => vi.fn())

vi.spyOn(issueCardsApi, 'fetchCards').mockResolvedValue([])

vi.mock('../services/api-activity', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-activity')>()
  return { ...actual, activityApi: { list: listMock } }
})

function item(overrides: Partial<ActivityItem> & Pick<ActivityItem, 'event_id' | 'type' | 'timestamp'>): ActivityItem {
  return {
    die_before: null,
    die_after: null,
    rating: null,
    issue_id: null,
    thread_id: null,
    thread_title: null,
    issue_number: null,
    ...overrides,
  }
}

/**
 * The logical actions the native resource returns for the reported production
 * sequence: the 09:46 snooze precedes the roll it caused even though the roll's
 * durable timestamp is slightly earlier, and the two rating rows are one action.
 */
const PRODUCTION_SEQUENCE: ActivityItem[] = [
  item({
    event_id: 1050511,
    type: 'roll',
    timestamp: '2026-11-08T15:42:35.028000Z',
    die_before: 6,
    issue_id: 1121330,
    thread_id: 3153,
    thread_title: 'Saga',
    issue_number: '4',
  }),
  item({
    event_id: 1050512,
    type: 'snooze',
    timestamp: '2026-11-08T15:46:25.515000Z',
    die_before: 6,
    die_after: 8,
    thread_id: 3153,
    thread_title: 'Saga',
  }),
  item({
    event_id: 1050513,
    type: 'roll',
    timestamp: '2026-11-08T15:46:25.467000Z',
    die_before: 8,
    issue_id: 25301,
    thread_id: 3469,
    thread_title: 'Paper Girls',
    issue_number: '7',
  }),
  item({
    event_id: 1050514,
    type: 'snooze',
    timestamp: '2026-11-08T15:46:34.105000Z',
    die_before: 8,
    die_after: 10,
    thread_id: 3469,
    thread_title: 'Paper Girls',
  }),
  item({
    event_id: 1050515,
    type: 'roll',
    timestamp: '2026-11-08T15:46:34.066000Z',
    die_before: 10,
    issue_id: 52329,
    thread_id: 8417,
    thread_title: 'Astro City: Astra',
    issue_number: '2',
  }),
  item({
    event_id: 1050517,
    type: 'rate',
    timestamp: '2026-11-08T16:01:54.388000Z',
    die_before: 10,
    die_after: 8,
    rating: 4.5,
    issue_id: 52329,
    thread_id: 8417,
    thread_title: 'Astro City: Astra',
    issue_number: '2',
  }),
]

function renderHistory() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  listMock.mockReset()
})

describe('History activity timeline (#4822)', () => {
  it('renders every logical action in causal order, including the snoozes', async () => {
    listMock.mockResolvedValue({ items: PRODUCTION_SEQUENCE, next_page_token: null })

    renderHistory()

    const list = await screen.findByRole('list', { name: 'Activity history' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(6)
    expect(listMock).toHaveBeenCalledTimes(1)
    expect(listMock).toHaveBeenCalledWith(null)

    expect(rows[0]).toHaveTextContent('Rolled · Saga #4')
    expect(rows[1]).toHaveTextContent('Snoozed · Saga')
    expect(rows[1]).toHaveTextContent('Die d6 → d8')
    expect(rows[2]).toHaveTextContent('Rolled · Paper Girls #7')
    expect(rows[3]).toHaveTextContent('Snoozed · Paper Girls')
    expect(rows[3]).toHaveTextContent('Die d8 → d10')
    expect(rows[4]).toHaveTextContent('Rolled · Astro City: Astra #2')
    expect(rows[5]).toHaveTextContent('Rated 4.5 · Astro City: Astra #2')
    expect(rows[5]).toHaveTextContent('Die d10 → d8')
  })

  it('shows the rating once and links the owned series to its thread', async () => {
    listMock.mockResolvedValue({ items: PRODUCTION_SEQUENCE, next_page_token: null })

    renderHistory()

    await screen.findByRole('list', { name: 'Activity history' })
    expect(screen.getAllByText('Rated 4.5')).toHaveLength(1)
    expect(screen.getAllByText('Snoozed')).toHaveLength(2)
    expect(screen.getAllByText('Rolled')).toHaveLength(3)

    const rows = within(await screen.findByRole('list', { name: 'Activity history' })).getAllByRole(
      'listitem',
    )
    const link = within(rows[5]).getByRole('link', { name: 'Astro City: Astra' })
    expect(link).toHaveAttribute('href', '/thread/8417')
  })

  it('appends the next page when Load more activity is pressed', async () => {
    const user = userEvent.setup()
    listMock
      .mockResolvedValueOnce({ items: PRODUCTION_SEQUENCE.slice(0, 5), next_page_token: 'page-2' })
      .mockResolvedValueOnce({
        items: [
          item({
            event_id: 1050517,
            type: 'rate',
            timestamp: '2026-11-08T16:01:54.388000Z',
            die_before: 10,
            die_after: 8,
            rating: 4.5,
            issue_id: 52329,
            thread_id: 8417,
            thread_title: 'Astro City: Astra',
            issue_number: '2',
          }),
        ],
        next_page_token: null,
      })

    renderHistory()

    const list = await screen.findByRole('list', { name: 'Activity history' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(5)

    await user.click(screen.getByRole('button', { name: 'Load more activity' }))

    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2))
    expect(listMock).toHaveBeenLastCalledWith('page-2')
    await waitFor(() =>
      expect(within(list).getAllByRole('listitem')).toHaveLength(6),
    )
    expect(within(list).getAllByRole('listitem')[5]).toHaveTextContent('Rated 4.5')
    expect(screen.queryByRole('button', { name: 'Load more activity' })).not.toBeInTheDocument()
  })

  it('offers an in-place Retry when the first page fails', async () => {
    const user = userEvent.setup()
    listMock
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ items: PRODUCTION_SEQUENCE, next_page_token: null })

    renderHistory()

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load activity')

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() =>
      expect(screen.getByRole('list', { name: 'Activity history' })).toBeInTheDocument(),
    )
    expect(listMock).toHaveBeenCalledTimes(2)
    expect(listMock).toHaveBeenLastCalledWith(null)
  })

  it('says the history is empty rather than showing a fabricated session', async () => {
    listMock.mockResolvedValue({ items: [], next_page_token: null })

    renderHistory()

    expect(await screen.findByText('No activity yet')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Activity history' })).not.toBeInTheDocument()
    expect(screen.queryByText(/session/i)).not.toBeInTheDocument()
  })

  it('names every logical action and renders legacy rows without a fabricated die', async () => {
    const ts = '2026-11-08T15:42:35.028000Z'
    listMock.mockResolvedValue({
      items: [
        item({ event_id: 1, type: 'unsnooze', timestamp: ts, die_before: 8, die_after: 10 }),
        item({ event_id: 2, type: 'manual_die', timestamp: ts }),
        item({ event_id: 3, type: 'reset_dice', timestamp: ts }),
        item({ event_id: 4, type: 'manual_die', timestamp: ts, die_after: 20 }),
        item({ event_id: 5, type: 'reset_dice', timestamp: ts, die_after: 6 }),
        item({ event_id: 6, type: 'dismiss', timestamp: ts }),
        item({ event_id: 7, type: 'undo', timestamp: ts }),
        item({ event_id: 8, type: 'rolled_but_skipped', timestamp: ts }),
        item({ event_id: 9, type: 'future_action', timestamp: ts, die_before: 6, die_after: 6 }),
        item({ event_id: 10, type: 'roll', timestamp: ts, thread_id: 42, die_before: 6, issue_number: '3' }),
      ],
      next_page_token: null,
    })

    renderHistory()

    const list = await screen.findByRole('list', { name: 'Activity history' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(10)
    expect(list).toHaveTextContent('Unsnoozed')
    expect(list).toHaveTextContent('Die d8 → d10')
    expect(list).toHaveTextContent('Set die')
    expect(list).toHaveTextContent('Set die to d20')
    expect(list).toHaveTextContent('Reset die')
    expect(list).toHaveTextContent('Reset die to d6')
    expect(list).toHaveTextContent('Die d20')
    expect(list).toHaveTextContent('Die d6')
    expect(list).toHaveTextContent('Dismissed the roll')
    expect(list).toHaveTextContent('Restored')
    expect(list).toHaveTextContent('Skipped')
    expect(list).toHaveTextContent('Future action')
    // A deleted series gets a historical label, never a fabricated link.
    expect(list).toHaveTextContent('Deleted series')
    expect(list).toHaveTextContent('#3')
  })

  it('normalizes a non-Error failure from the first page', async () => {
    listMock.mockRejectedValueOnce('offline')

    renderHistory()

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load activity')
  })

  it('normalizes a non-Error failure from a later page', async () => {
    const user = userEvent.setup()
    listMock
      .mockResolvedValueOnce({ items: PRODUCTION_SEQUENCE.slice(0, 1), next_page_token: 'page-2' })
      .mockRejectedValueOnce('offline')

    renderHistory()

    await screen.findByRole('list', { name: 'Activity history' })
    await user.click(screen.getByRole('button', { name: 'Load more activity' }))

    expect(await screen.findByText('Failed to load more activity')).toBeInTheDocument()
  })
})
