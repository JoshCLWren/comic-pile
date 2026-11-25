import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from './testingLibrary'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueNextIssueCard from '../pages/QueuePage/QueueNextIssueCard'
import { DirectReadIssuePanel } from '../components/DirectReadIssuePanel'
import { issuesApi } from '../services/api-issues'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'
import type { IssueListResponse } from '../types'
import { injectModuleDoubles } from './injectModuleDoubles'

await injectModuleDoubles(await import('../components/ComicIssueCard'), () => ({
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

await injectModuleDoubles(await import('../pages/RollPage/components/ComicIdentity'), () => ({
  ComicIdentity: ({ issueId }: { issueId: number | null | undefined }) => (
    <div data-testid="direct-read-comic-identity">{issueId}</div>
  ),
}))

await injectModuleDoubles(await import('../hooks/useComicVineIssueIntelligence'), () => ({
  useComicVineIssueIntelligence: () => ({
    metadata: { image_url: 'https://comicvine.gamespot.com/a/hellboy9.jpg' },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

await injectModuleDoubles(await import('../components/Tags/TagSection'), () => ({
  TagSection: ({ targetType, targetId, targetLabel }: {
    targetType: string
    targetId: number
    targetLabel: string
  }) => (
    <div data-testid="direct-read-tag-section" data-target={`${targetType}:${targetId}`}>
      {targetLabel}
    </div>
  ),
}))


const list = vi.spyOn(issuesApi, 'list')
const get = vi.spyOn(issuesApi, 'get')
const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')
const card: IssueCard = {
  issue_id: 37, thread_id: 42, thread_title: 'Hellboy', issue_number: '9',
  status: 'unread', rating: null, mapping_state: 'confirmed',
  has_confirmed_identity: true, cover_image_url: 'https://comicvine.gamespot.com/a/hellboy9.jpg',
}

function issueList(id: number | null): IssueListResponse {
  return {
    // SAFETY: this test fixture deliberately supplies only the id, issue number,
    // and status fields consumed by QueueNextIssueCard; other issue fields are
    // irrelevant to the on-demand resolver assertion below.
    issues: id == null ? [] : [{
      id, thread_id: 42, issue_number: id === 37 ? '9' : '10', status: 'unread',
    }] as IssueListResponse['issues'],
    total_count: id == null ? 0 : 1,
    page_size: 1,
    next_page_token: null,
  }
}

function setup(preferredIssueId?: number, issuesRemaining?: number, onMigrate?: () => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const Wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  const ui = preferredIssueId == null
    ? <QueueNextIssueCard threadId={42} threadTitle="Hellboy" issuesRemaining={issuesRemaining} onMigrate={onMigrate} />
    : <DirectReadIssuePanel threadId={42} threadTitle="Hellboy" preferredIssueId={preferredIssueId} />
  return render(ui, { wrapper: Wrapper })
}

beforeEach(() => {
  list.mockReset()
  get.mockReset()
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
    expect(screen.getByText(/pending Roll and die are preserved/)).toBeVisible()
  })

  it('opens the same provider details and tags a roll would show for the exact issue (#5751)', async () => {
    setup()
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    // The read surface reuses the post-roll provider identity (cover, summary,
    // creators, story arcs) and that exact issue's tag editor so a reader can
    // map or inspect credits without rolling first.
    expect(screen.getByTestId('direct-read-comic-identity')).toHaveTextContent('37')
    const tags = screen.getByTestId('direct-read-tag-section')
    expect(tags).toHaveAttribute('data-target', 'Issue:37')
    expect(tags).toHaveTextContent('Hellboy #9')
    expect(within(screen.getByTestId('direct-read-comic-details')).getAllByTestId('direct-read-comic-identity')).toHaveLength(1)
  })

  it('chooses an alternate owned issue without altering the pending automatic Roll offer', async () => {
    list.mockImplementation(async (_threadId, options) => {
      if (options?.status === 'unread') return issueList(37)
      // SAFETY: the abbreviated owned-issue fixtures contain the exact fields
      // consumed by DirectReadIssuePanel and intentionally omit unrelated metadata.
      return {
        ...issueList(37),
        issues: [
          { id: 37, thread_id: 42, issue_number: '9', status: 'unread' },
          { id: 38, thread_id: 42, issue_number: '10', status: 'unread' },
        ],
        page_size: 50,
        total_count: 2,
      } as IssueListResponse
    })
    fetchCards.mockImplementation(async (ids) => [ids[0] === 37 ? card : {
      ...card, issue_id: 38, issue_number: '10',
    }])
    setup()
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    fireEvent.click(screen.getByRole('button', { name: 'Choose another owned issue' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Hellboy #10 (unread)' }))
    await waitFor(() => expect(screen.getByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '38'))
    expect(list).toHaveBeenCalledWith(42, { page_size: 50, page_token: undefined })
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
    expect(await screen.findByText(/No unread tracked issue remains\./)).toBeVisible()
  })


  it('uses the exact Roll-offered issue without consulting the Queue frontier', async () => {
    get.mockResolvedValue(issueList(37).issues[0]!)
    setup(37)
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    expect(get).toHaveBeenCalledExactlyOnceWith(37)
    expect(list).not.toHaveBeenCalled()
  })

  it('refuses a preferred issue that does not belong to the selected series', async () => {
    get.mockResolvedValue({ ...issueList(37).issues[0]!, thread_id: 999 })
    setup(37)
    expect(await screen.findByRole('alert')).toHaveTextContent('does not belong to the selected series')
    expect(screen.queryByTestId('shared-queue-card')).not.toBeInTheDocument()
    expect(list).not.toHaveBeenCalled()
    expect(fetchCards).toHaveBeenCalledExactlyOnceWith([37])
  })

  it('reports a failed optional issue browse and retries without losing the current card', async () => {
    let attempts = 0
    list.mockImplementation(async (_threadId, options) => {
      if (options?.status === 'unread') return issueList(37)
      if (attempts++ === 0) throw new Error('browse temporarily unavailable')
      return { ...issueList(37), page_size: 50 }
    })
    setup()
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    fireEvent.click(screen.getByRole('button', { name: 'Choose another owned issue' }))
    const picker = await screen.findByTestId('direct-read-issue-picker')
    expect(await within(picker).findByRole('alert')).toHaveTextContent('browse temporarily unavailable')
    expect(screen.getByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    fireEvent.click(within(picker).getByRole('button', { name: 'Retry' }))
    expect(await within(picker).findByRole('button', { name: 'Hellboy #9 (unread)' })).toBeVisible()
    expect(attempts).toBe(2)
  })

  it('paginates the manual owned-issue picker without falling back to automatic eligibility', async () => {
    const first = issueList(37).issues[0]!
    const second = { ...first, id: 38, issue_number: '10' }
    const third = { ...first, id: 39, issue_number: '11' }
    list.mockImplementation(async (_threadId, options) => {
      if (options?.status === 'unread') return issueList(37)
      if (options?.page_token === 'next-owned-page') {
        return { ...issueList(39), issues: [third], total_count: 3, page_size: 50 }
      }
      return {
        ...issueList(37),
        issues: [first, second],
        total_count: 3,
        page_size: 50,
        next_page_token: 'next-owned-page',
      }
    })
    fetchCards.mockImplementation(async (ids) => [ids[0] === 39
      ? { ...card, issue_id: 39, issue_number: '11' }
      : card])
    setup()
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    fireEvent.click(screen.getByRole('button', { name: 'Choose another owned issue' }))
    const picker = await screen.findByTestId('direct-read-issue-picker')
    fireEvent.click(await within(picker).findByRole('button', { name: 'Load more issues' }))
    fireEvent.click(await within(picker).findByRole('button', { name: 'Hellboy #11 (unread)' }))
    await waitFor(() => expect(screen.getByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '39'))
    expect(list).toHaveBeenCalledWith(42, { page_size: 50, page_token: 'next-owned-page' })
  })

  it('disables a second page request while manual issue browsing is still loading', async () => {
    const first = issueList(37).issues[0]!
    const second = { ...first, id: 38, issue_number: '10' }
    let releaseNextPage: (page: IssueListResponse) => void = () => {
      throw new Error('Next page request has not started')
    }
    list.mockImplementation(async (_threadId, options) => {
      if (options?.status === 'unread') return issueList(37)
      if (options?.page_token === 'next-page') {
        return new Promise<IssueListResponse>((resolve) => {
          releaseNextPage = resolve
        })
      }
      return {
        ...issueList(37),
        issues: [first],
        page_size: 50,
        next_page_token: 'next-page',
      }
    })
    setup()
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    fireEvent.click(screen.getByRole('button', { name: 'Choose another owned issue' }))
    const picker = await screen.findByTestId('direct-read-issue-picker')
    fireEvent.click(await within(picker).findByRole('button', { name: 'Load more issues' }))
    const loading = await within(picker).findByRole('button', { name: 'Loading…' })
    expect(loading).toBeDisabled()
    await act(async () => {
      releaseNextPage({
        ...issueList(38),
        issues: [second],
        page_size: 50,
        next_page_token: null,
      })
    })
    expect(await within(picker).findByRole('button', { name: 'Hellboy #10 (unread)' })).toBeVisible()
    expect(within(picker).queryByRole('button', { name: 'Load more issues' })).not.toBeInTheDocument()
  })

  it('keeps a previously read rating editor closed until its saved rating is loaded', async () => {
    const saved = { ...issueList(37).issues[0]!, status: 'read' as const }
    get.mockResolvedValue(saved)
    let publishCards: (cards: IssueCard[]) => void = () => {
      throw new Error('Card request not initialized')
    }
    fetchCards.mockImplementation(() => new Promise<IssueCard[]>((resolve) => {
      publishCards = resolve
    }))
    setup(37)
    expect(await screen.findByText(/Loading the saved rating before editing/)).toBeVisible()
    expect(screen.queryByTestId('shared-queue-card')).not.toBeInTheDocument()
    await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith([37]))
    await act(async () => publishCards([{ ...card, status: 'read', rating: 4.5 }]))
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
  })

  it('never opens Edit rating with a guessed value when saved details fail', async () => {
    get.mockResolvedValue({ ...issueList(37).issues[0]!, status: 'read' })
    fetchCards.mockRejectedValueOnce(new Error('details offline'))
    setup(37)
    expect(await screen.findByRole('alert')).toHaveTextContent('details offline')
    expect(screen.queryByTestId('shared-queue-card')).not.toBeInTheDocument()
    expect(screen.getByText(/Retry details before editing/)).toBeVisible()
  })

  it('offers counter-only series with unread comics an explicit migration action', async () => {
    list.mockResolvedValue(issueList(null))
    const onMigrate = vi.fn()
    setup(undefined, 3, onMigrate)
    expect(await screen.findByText(/This series has 3 unread comics/)).toBeVisible()
    expect(screen.queryByText(/No unread tracked issue remains/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Set up issue tracking' }))
    expect(onMigrate).toHaveBeenCalledExactlyOnceWith()
    expect(fetchCards).not.toHaveBeenCalled()
  })

  it('offers manual tracking when a Roll series has no issue rows and no known count', async () => {
    list.mockResolvedValue(issueList(null))
    const onMigrate = vi.fn()
    setup(undefined, undefined, onMigrate)
    expect(await screen.findByText(/No unread issue is individually tracked for this series/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Set up issue tracking' }))
    expect(onMigrate).toHaveBeenCalledExactlyOnceWith()
    expect(fetchCards).not.toHaveBeenCalled()
  })

  it('describes one remaining untracked comic accurately before migration', async () => {
    list.mockResolvedValue(issueList(null))
    setup(undefined, 1, vi.fn())
    expect(await screen.findByText(/This series has 1 unread comic but no individually tracked unread issue/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Set up issue tracking' })).toBeEnabled()
    expect(fetchCards).not.toHaveBeenCalled()
  })

  it('does not imply more unread comics for a completed counter-only series', async () => {
    list.mockResolvedValue(issueList(null))
    const onMigrate = vi.fn()
    setup(undefined, 0, onMigrate)
    expect(await screen.findByText(/No unread tracked issue remains/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Set up issue tracking' })).not.toBeInTheDocument()
    expect(onMigrate).not.toHaveBeenCalled()
  })

  it('recovers an exact offered-issue lookup failure without falling back to Queue eligibility', async () => {
    get.mockRejectedValueOnce(new Error('exact issue lookup unavailable'))
      .mockResolvedValueOnce(issueList(37).issues[0]!)
    setup(37)
    expect(await screen.findByRole('alert')).toHaveTextContent('exact issue lookup unavailable')
    expect(screen.queryByTestId('shared-queue-card')).not.toBeInTheDocument()
    expect(list).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry issue lookup' }))
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    expect(get).toHaveBeenCalledTimes(2)
    expect(list).not.toHaveBeenCalled()
  })

  it('recovers saved read-issue ratings after the cover and rating service returns', async () => {
    get.mockResolvedValue({ ...issueList(37).issues[0]!, status: 'read' })
    fetchCards.mockRejectedValueOnce(new Error('rating details unavailable'))
      .mockResolvedValueOnce([{ ...card, status: 'read', rating: 4.5 }])
    setup(37)
    expect(await screen.findByRole('alert')).toHaveTextContent('rating details unavailable')
    expect(screen.queryByTestId('shared-queue-card')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry details' }))
    expect(await screen.findByTestId('shared-queue-card')).toHaveAttribute('data-issue-id', '37')
    expect(fetchCards).toHaveBeenCalledTimes(2)
  })
})
