/**
 * Issue #4445: History items that name an exact owned issue must offer the
 * same shared covered action every other issue surface offers — never a
 * guessed issue, never a thread-only detour. Items without a canonical
 * `issue_id` (legacy/deleted events) render no issue action at all.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import type { ActivityItem } from '../services/api-activity'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'

const listMock = vi.hoisted(() => vi.fn())

vi.mock('../services/api-activity', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-activity')>()
  return { ...actual, activityApi: { list: listMock } }
})

vi.mock('../components/ComicIssueMappingAction', () => ({
  default: ({ issueId }: { issueId: number | null }) => <span data-testid="shared-map-action">{issueId}</span>,
}))

const sagaCard: IssueCard = {
  issue_id: 1121330,
  thread_id: 3153,
  thread_title: 'Saga',
  issue_number: '4',
  status: 'read',
  rating: 4.5,
  read_at: '2026-11-08T15:00:00Z',
  mapping_state: 'confirmed',
  has_confirmed_identity: true,
  comicvine_issue_id: '4000-4',
  cover_image_url: 'https://comicvine.gamespot.com/a/uploads/original/saga4.jpg',
}
const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')

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
  fetchCards.mockReset()
  fetchCards.mockResolvedValue([sagaCard])
})

describe('History exact-issue actions (#4445)', () => {
  it('batches one card projection for visible owned issue ids and renders the shared trigger', async () => {
    listMock.mockResolvedValue({
      items: [
        item({
          event_id: 1050511,
          type: 'roll',
          timestamp: '2026-11-08T15:42:35.028000Z',
          issue_id: 1121330,
          thread_id: 3153,
          thread_title: 'Saga',
          issue_number: '4',
        }),
        item({
          event_id: 1050512,
          type: 'snooze',
          timestamp: '2026-11-08T15:46:25.515000Z',
          thread_id: 3153,
          thread_title: 'Saga',
        }),
      ],
      next_page_token: null,
    })

    renderHistory()

    const list = await screen.findByRole('list', { name: 'Activity history' })
    await waitFor(() => expect(fetchCards).toHaveBeenCalledWith([1121330]))
    // Collapsed rows stay compact: no card body mounts until expansion.
    expect(screen.queryByTestId('comic-issue-card')).not.toBeInTheDocument()
    const rows = within(list).getAllByRole('listitem')
    // The snooze row has no canonical issue_id and gets no issue action.
    expect(within(rows[1]).queryByTestId('issue-card-trigger-1121330')).not.toBeInTheDocument()
    expect(within(rows[0]).getByTestId('issue-card-trigger-1121330')).toBeInTheDocument()
  })

  it('opens the shared card with the exact issue, cover and actions on activation', async () => {
    listMock.mockResolvedValue({
      items: [
        item({
          event_id: 1050511,
          type: 'rate',
          timestamp: '2026-11-08T15:42:35.028000Z',
          rating: 4.5,
          issue_id: 1121330,
          thread_id: 3153,
          thread_title: 'Saga',
          issue_number: '4',
        }),
      ],
      next_page_token: null,
    })

    renderHistory()

    const trigger = await screen.findByRole('button', { name: 'Reading and mapping actions for Saga #4' })
    await userEvent.click(trigger)
    const card = screen.getByTestId('comic-issue-card')
    expect(card).toHaveAttribute('aria-label', 'Issue Saga #4')
    expect(within(card).getByRole('img', { name: 'Cover for Saga #4' })).toHaveAttribute(
      'src',
      sagaCard.cover_image_url,
    )
    // The common direct action is present and never routes through Roll.
    expect(within(card).getByRole('button', { name: 'Edit rating' })).toBeEnabled()
    expect(within(card).getByRole('button', { name: 'Mark unread' })).toBeEnabled()
  })
})
