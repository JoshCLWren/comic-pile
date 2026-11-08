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
  it('keeps a Reading Plan header label while opening the same exact issue card', async () => {
    setup(<CompactIssueCardTrigger
      issueId={37} card={card} threadTitle="Hellboy" issueNumber="9"
      actionLabel="Read next issue" expandedVariant="featured"
    />)
    const next = screen.getByRole('button', { name: 'Read next issue' })
    expect(next).toHaveTextContent('Read next issue')
    await userEvent.click(next)
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('aria-label', 'Issue Hellboy #9')
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('data-variant', 'featured')
    expect(fetchCards).not.toHaveBeenCalled()
  })

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

  it('does not adopt a different issue returned from a mis-scoped card lookup', async () => {
    fetchCards.mockResolvedValue([{ ...card, issue_id: 999, rating: 5 }])
    setup(<CompactIssueCardTrigger
      issueId={37} threadTitle="B.P.R.D." issueNumber="Annual 1" status="unread"
    />)
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for B.P.R.D. #Annual 1' }))
    await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([37]))
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('aria-label', 'Issue B.P.R.D. #Annual 1')
    expect(screen.queryByRole('img', { name: 'Cover for Hellboy #9' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Read now' })).toBeEnabled()
  })

  it('discards a cached issue cover when a virtualized row changes its canonical issue id', async () => {
    fetchCards.mockResolvedValueOnce([card]).mockResolvedValueOnce([])
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const row = (issueId: number, title: string, number: string) => (
      <QueryClientProvider client={queryClient}>
        <CompactIssueCardTrigger issueId={issueId} threadTitle={title} issueNumber={number} />
      </QueryClientProvider>
    )
    const { rerender } = render(row(37, 'Hellboy', '9'))
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' }))
    expect((await screen.findAllByRole('img', { name: 'Cover for Hellboy #9' }))[0]).toHaveAttribute('src', card.cover_image_url)
    rerender(row(38, 'B.P.R.D.', 'Annual 2'))
    await waitFor(() => expect(fetchCards).toHaveBeenCalledWith([38]))
    expect(screen.getByRole('button', { name: 'Reading and mapping actions for B.P.R.D. #Annual 2' })).toBeEnabled()
    expect(screen.queryByRole('img', { name: 'Cover for Hellboy #9' })).not.toBeInTheDocument()
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('aria-label', 'Issue B.P.R.D. #Annual 2')
    expect(screen.getAllByTestId('comic-issue-cover-placeholder')).toHaveLength(2)
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
  it('rejects a batch card belonging to a different issue instead of borrowing its art or rating', async () => {
    setup(<CompactIssueCardTrigger
      issueId={38}
      card={card}
      threadTitle="B.P.R.D."
      issueNumber="Annual 2"
      status="unread"
      rating={null}
    />)
    const trigger = screen.getByRole('button', { name: 'Reading and mapping actions for B.P.R.D. #Annual 2' })
    expect(trigger).toHaveTextContent('Unread')
    expect(trigger).not.toHaveTextContent('Rated')
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toHaveAttribute(
      'aria-label', 'No cover for B.P.R.D. #Annual 2',
    )
    await userEvent.click(trigger)
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute(
      'aria-label', 'Issue B.P.R.D. #Annual 2',
    )
    expect(screen.getByRole('button', { name: 'Read now' })).toBeEnabled()
    await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([38]))
  })

  it('keeps exact fallback identity and a compact accessible action when batch names are blank', async () => {
    setup(<CompactIssueCardTrigger
      issueId={37}
      card={{ ...card, thread_title: '', issue_number: '', status: 'unread', rating: null, cover_image_url: null }}
      threadTitle="Hellboy"
      issueNumber="Winter Special"
      hideTitle
    />)
    const trigger = screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #Winter Special' })
    expect(trigger).not.toHaveTextContent('Hellboy #Winter Special')
    expect(trigger).toHaveTextContent('Read / Rate / Map')
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toHaveAttribute(
      'aria-label', 'No cover for Hellboy #Winter Special',
    )
    await userEvent.click(trigger)
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute(
      'aria-label', 'Issue Hellboy #Winter Special',
    )
    expect(fetchCards).not.toHaveBeenCalled()
  })

  it('expands a read issue for rating correction without generating a second read', async () => {
    setup(<CompactIssueCardTrigger
      issueId={37}
      card={{ ...card, status: 'read', rating: 2.5 }}
      threadTitle="Hellboy"
      issueNumber="9"
      status="unread"
    />)
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' }))
    expect(screen.queryByRole('button', { name: 'Read now' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Edit rating' }))
    expect(screen.getByRole('slider')).toHaveValue('2.5')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(patchIssue).not.toHaveBeenCalled()
    expect(fetchCards).not.toHaveBeenCalled()
  })

  it('shows the row-provided read state when the projection is missing and can still correct it', async () => {
    fetchCards.mockResolvedValue([])
    setup(<CompactIssueCardTrigger
      issueId={37} threadTitle="Hellboy" issueNumber="9" status="read"
    />)
    expect(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' })).toHaveTextContent('Read')
    await userEvent.click(screen.getByRole('button', { name: 'Reading and mapping actions for Hellboy #9' }))
    await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([37]))
    expect(screen.getByRole('button', { name: 'Mark unread' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Read now' })).not.toBeInTheDocument()
  })

})
