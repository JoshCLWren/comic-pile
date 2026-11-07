import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CompactIssueCardTrigger from '../components/CompactIssueCardTrigger'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'

vi.mock('../components/ComicIssueMappingAction', () => ({
  default: ({ issueId }: { issueId: number | null }) => <span data-testid="shared-map-action">{issueId}</span>,
}))

const card: IssueCard = {
  issue_id: 37, thread_id: 10, thread_title: 'Hellboy', issue_number: '9',
  status: 'unread', rating: null, read_at: null,
  mapping_state: 'confirmed', has_confirmed_identity: true,
  comicvine_issue_id: '4000-9',
  cover_image_url: 'https://comicvine.gamespot.com/a/uploads/original/hellboy9.jpg',
}
const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')
const patchIssue = vi.spyOn(issueCardsApi, 'patchIssue')

function setup(node: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  fetchCards.mockReset()
  patchIssue.mockReset()
  fetchCards.mockResolvedValue([card])
})

describe('compact shared issue entry across dense lists', () => {
  it('uses the owning list batch, renders exact cover, and opens the shared card without a second request', async () => {
    setup(<CompactIssueCardTrigger
      issueId={37} card={card} threadTitle="stale title" issueNumber="1" status="unread"
    />)
    expect(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('img', { name: 'Cover for Hellboy #9' })).toHaveAttribute('src', card.cover_image_url)
    expect(fetchCards).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' }))
    expect(screen.getByTestId('comic-issue-card')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Read now' })).toBeEnabled()
    expect(screen.getByTestId('shared-map-action')).toHaveTextContent('37')
    expect(fetchCards).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' }))
    expect(screen.queryByTestId('comic-issue-card')).not.toBeInTheDocument()
  })

  it('loads one exact card lazily on demand instead of fetching for every collapsed row', async () => {
    setup(<CompactIssueCardTrigger issueId={37} threadTitle="Hellboy" issueNumber="9" />)
    expect(fetchCards).not.toHaveBeenCalled()
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' }))
    await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([37]))
    expect((await screen.findAllByRole('img', { name: 'Cover for Hellboy #9' }))[0]).toHaveAttribute('src', card.cover_image_url)
    expect(screen.getByRole('button', { name: 'Read now' })).toBeEnabled()
  })

  it('does not replace an issue with a different id when the server omits its projection', async () => {
    fetchCards.mockResolvedValue([])
    setup(<CompactIssueCardTrigger issueId={37} threadTitle="Fallback series" issueNumber="Annual 1" status="unread" />)
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Fallback series #Annual 1' }))
    await waitFor(() => expect(fetchCards).toHaveBeenCalledOnce())
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('aria-label', 'Issue Fallback series #Annual 1')
    expect(screen.getByRole('button', { name: 'Read now' })).toBeEnabled()
  })

  it('offers retry after a failed metadata batch but keeps manual action available', async () => {
    fetchCards.mockRejectedValueOnce(new Error('Metadata temporarily unavailable')).mockResolvedValueOnce([card])
    setup(<CompactIssueCardTrigger issueId={37} threadTitle="Hellboy" issueNumber="9" status="unread" />)
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Metadata temporarily unavailable')
    expect(screen.getByRole('button', { name: 'Read now' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect((await screen.findAllByRole('img', { name: 'Cover for Hellboy #9' }))[0]).toHaveAttribute('src', card.cover_image_url)
  })

  it('opens rating without writing; saving delegates to direct issue command', async () => {
    const onMutated = vi.fn()
    patchIssue.mockResolvedValue({
      issue: { ...card, status: 'read', rating: 3.5 },
      thread: { thread_id: 10, issues_remaining: 5, status: 'active' },
      read_event_created: true, rating_event_created: true, replayed: false,
    })
    setup(<CompactIssueCardTrigger issueId={37} card={card} threadTitle="Hellboy" issueNumber="9" onMutated={onMutated} />)
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' }))
    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))
    expect(patchIssue).not.toHaveBeenCalled()
    expect(screen.getByText('Direct read only — no die or queue change.')).toBeVisible()
    fireEvent.change(screen.getByRole('slider'), { target: { value: '3.5' } })
    await userEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
    await waitFor(() => expect(patchIssue).toHaveBeenCalledWith(37, expect.objectContaining({ status: 'read', rating: 3.5 })))
    await waitFor(() => expect(onMutated).toHaveBeenCalledOnce())
  })

  it('shows the canonical read state and effective rating from a saved card', () => {
    setup(<CompactIssueCardTrigger issueId={37} card={{ ...card, status: 'read', rating: 4.5 }} threadTitle="Wrong" issueNumber="1" status="unread" rating={1} />)
    expect(screen.getByText(/Read · Rated 4.5/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' })).toHaveAttribute('aria-expanded', 'false')
  })
})
