/**
 * History page regressions that are independent of the exact activity payload.
 *
 * The session-summary assertions that used to live here were retired with the
 * #4822 cutover: History now renders the owner-scoped `GET /api/v2/activity`
 * stream. The causal Nov 8 sequence itself is covered by
 * `HistoryPage.activity.test.tsx`; this file keeps the still-applicable empty,
 * bounded-loading and recovery contracts (#3572, #3429) pointed at the real
 * page and service rather than a stale session mock.
 */
import { render, screen, waitFor } from '@testing-library/react'
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

const rolled: ActivityItem = {
  event_id: 9001,
  type: 'roll',
  timestamp: '2026-11-08T15:42:35.028000Z',
  die_before: 6,
  die_after: null,
  rating: null,
  issue_id: 1121330,
  thread_id: 3153,
  thread_title: 'Saga',
  issue_number: '4',
}

const snoozed: ActivityItem = {
  event_id: 9002,
  type: 'snooze',
  timestamp: '2026-11-08T15:46:25.515000Z',
  die_before: 6,
  die_after: 8,
  rating: null,
  issue_id: null,
  thread_id: 3153,
  thread_title: 'Saga',
  issue_number: null,
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

function expectNoExportSummary() {
  expect(screen.queryByRole('link', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByText(/export summary/i)).not.toBeInTheDocument()

  const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'))
  expect(hrefs).not.toContain('/admin/export/summary/')
  expect(hrefs).not.toContain('/api/admin/export/summary/')
  expect(hrefs.filter((href) => (href ?? '').includes('/export/'))).toEqual([])
}

beforeEach(() => {
  listMock.mockReset()
})

describe('History page contracts', () => {
  it('renders the empty activity state without an Export Summary control (issue #3572)', async () => {
    listMock.mockResolvedValue({ items: [], next_page_token: null })

    renderHistory()

    expect(await screen.findByText('No activity yet')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'History' })).toBeInTheDocument()
    expect(screen.getByText('Your reading activity')).toBeInTheDocument()
    expectNoExportSummary()
  })

  it('renders the activity list without an Export Summary control (issue #3572)', async () => {
    listMock.mockResolvedValue({ items: [rolled, snoozed], next_page_token: null })

    renderHistory()

    const list = await screen.findByRole('list', { name: 'Activity history' })
    expect(list).toBeInTheDocument()
    expect(list.querySelectorAll('[role="listitem"]')).toHaveLength(2)
    expect(screen.getByText('Snoozed')).toBeInTheDocument()
    expectNoExportSummary()
  })

  it('holds a bare spinner before any initial attempt has failed (issue #3429)', () => {
    listMock.mockReturnValue(new Promise(() => undefined))

    renderHistory()

    expect(screen.getByText('Loading...', { exact: true })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    expect(screen.queryByText(/still loading/i)).not.toBeInTheDocument()
  })

  it('keeps bounded recovery copy visible while the first page retries (issue #3429)', async () => {
    const user = userEvent.setup()
    listMock
      .mockRejectedValueOnce(new Error('network down'))
      .mockReturnValue(new Promise(() => undefined))

    renderHistory()

    expect(await screen.findByText('Failed to load activity')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/still loading your history/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.queryByText('Loading...', { exact: true })).not.toBeInTheDocument()
  })

  it('offers an in-place retry when a later activity page fails', async () => {
    const user = userEvent.setup()
    listMock
      .mockResolvedValueOnce({ items: [rolled], next_page_token: 'page-2' })
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ items: [snoozed], next_page_token: null })

    renderHistory()

    await screen.findByRole('list', { name: 'Activity history' })
    await user.click(screen.getByRole('button', { name: 'Load more activity' }))

    expect(await screen.findByText('Failed to load more activity')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(3))
    await waitFor(() =>
      expect(
        screen.getByRole('list', { name: 'Activity history' }).querySelectorAll('[role="listitem"]'),
      ).toHaveLength(2),
    )
    expect(listMock).toHaveBeenLastCalledWith('page-2')
  })

  it('shows a bounded indicator while a later activity page is loading', async () => {
    const user = userEvent.setup()
    listMock
      .mockResolvedValueOnce({ items: [rolled], next_page_token: 'page-2' })
      .mockReturnValue(new Promise(() => undefined))

    renderHistory()

    await screen.findByRole('list', { name: 'Activity history' })
    await user.click(screen.getByRole('button', { name: 'Load more activity' }))

    expect(await screen.findByText('Loading more...')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Load more activity' })).not.toBeInTheDocument()
  })
})
