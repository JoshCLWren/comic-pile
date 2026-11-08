import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueNextIssueCard from '../pages/QueuePage/QueueNextIssueCard'
import { issuesApi } from '../services/api-issues'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'
import type { IssueListResponse } from '../types'

vi.mock('../components/ComicIssueCard', () => ({
  ComicIssueCard: ({
    issueId, threadTitle, issueNumber, card, onMutated,
  }: {
    issueId: number
    threadTitle: string
    issueNumber: string
    card?: IssueCard | null
    onMutated?: () => void
  }) => (
    <article data-testid="shared-queue-card" data-issue-id={issueId}>
      {threadTitle} #{issueNumber} {card?.cover_image_url ?? 'No cover'}
      <button type="button" onClick={onMutated}>Simulate direct save</button>
    </article>
  ),
}))

const list = vi.spyOn(issuesApi, 'list')
const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')
const card: IssueCard = {
  issue_id: 37, thread_id: 42, thread_title: 'Hellboy', issue_number: '9',
  status: 'unread', rating: null, mapping_state: 'confirmed',
  has_confirmed_identity: true, cover_image_url: 'https://comicvine.gamespot.com/a/hellboy9.jpg',
}

function issueList(id: number | null): IssueListResponse {
  return {
    issues: id == null ? [] : [{
      id, issue_number: id === 37 ? '9' : '10', status: 'unread',
    }] as IssueListResponse['issues'],
    total_count: id == null ? 0 : 1,
    next_page_token: null,
  }
}

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const Wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  return render(<QueueNextIssueCard threadId={42} threadTitle="Hellboy" />, { wrapper: Wrapper })
}

beforeEach(() => {
  list.mockReset()
  fetchCards.mockReset()
  list.mockResolvedValue(issueList(37))
  fetchCards.mockResolvedValue([card])
})

describe('Queue exact-issue shared actions', () => {
  it('resolves an owned issue ID on demand instead of guessing from a thread number', async () => {
    setup()
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    expect(screen.getByTestId('shared-queue-card')).toHaveTextContent('Hellboy #9')
    await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([37]))
    expect(list).toHaveBeenCalledExactlyOnceWith(42, { status: 'unread', page_size: 1 })
    expect(screen.getByText(/Direct reading does not change/)).toBeVisible()
  })

  it('advances to the next canonical issue after a direct read without mutating Roll', async () => {
    list.mockResolvedValueOnce(issueList(37)).mockResolvedValueOnce(issueList(38))
    fetchCards.mockImplementation(async (ids) => [ids[0] === 37 ? card : {
      ...card, issue_id: 38, issue_number: '10',
    }])
    setup()
    await screen.findByTestId('shared-queue-card')
    fireEvent.click(screen.getByRole('button', { name: 'Simulate direct save' }))
    await waitFor(() => expect(screen.getByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '38'))
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('reports lookup failure with a retry and never fabricates an issue card', async () => {
    list.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(issueList(37))
    setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.queryByTestId('shared-queue-card')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry issue lookup' }))
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
  })

  it('keeps manual actions when card metadata fails and reports no unread issue truthfully', async () => {
    fetchCards.mockRejectedValueOnce(new Error('cover offline'))
    const view = setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('cover offline')
    expect(screen.getByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    view.unmount()
    list.mockResolvedValue(issueList(null))
    setup()
    expect(await screen.findByText('No tracked unread issues remain for this series.')).toBeVisible()
  })
})
