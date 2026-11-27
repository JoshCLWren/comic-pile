import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ComicIssueReadingCard } from '../components/ComicIssueReadingCard'
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api-comicvine'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'
import { tagsApi, type EffectiveTagsResponse, type Tag } from '../services/api-tags'

// This suite owns the roll-parity details that dense triggers open on demand.
// The mapping action has its own suite; only the request scope of the reading
// card and the exact issue rendered by its provider/tag details are asserted.
vi.mock('../components/ComicIssueMappingAction', () => ({
  default: ({ issueId }: { issueId: number | null }) => <span data-testid="shared-map-action">{issueId}</span>,
}))

const patchIssue = vi.spyOn(issueCardsApi, 'patchIssue')
const intelligence = vi.spyOn(comicVineApi, 'getIssueIntelligence')
const effectiveTags = vi.spyOn(tagsApi, 'effectiveForIssue')

const card: IssueCard = {
  issue_id: 37,
  thread_id: 10,
  thread_title: 'Hellboy',
  issue_number: '9',
  status: 'unread',
  rating: null,
  mapping_state: 'confirmed',
  has_confirmed_identity: true,
  comicvine_issue_id: '4000-9',
  cover_image_url: 'https://comicvine.gamespot.com/a/uploads/original/hellboy9.jpg',
}

const metadata: ComicVineIssueIntelligence = {
  comicvine_issue_id: '4000-9',
  comicvine_url: null,
  series_name: 'Hellboy',
  series_id: 12,
  issue_number: '9',
  name: 'The Corpse',
  description: null,
  image_url: 'https://comicvine.gamespot.com/a/uploads/original/hellboy9.jpg',
  cover_date: null,
  store_date: null,
  creators: [{ creator_id: null, name: 'Mike Mignola', roles: ['writer', 'artist'] }],
  story_arcs: [],
  metadata_status: 'deep_fetched',
}

const tag: Tag = {
  id: 4,
  name: 'Physical',
  normalized_name: 'physical',
  scope: 'private' as const,
  owner_user_id: 1,
  color: '#3B82F6',
  created_at: '',
  updated_at: '',
}

const tags: EffectiveTagsResponse = {
  target_type: 'Issue',
  target_id: 37,
  direct_tags: [tag],
  effective_tags: [{ tag, direct: true, sources: [] }],
}

function mount(overrides: { showReadingDetails?: boolean; isOwned?: boolean } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return render(
    <ComicIssueReadingCard
      issueId={37}
      card={card}
      threadTitle="Hellboy"
      issueNumber="9"
      status="unread"
      variant="compact"
      showReadingDetails={overrides.showReadingDetails}
      isOwned={overrides.isOwned}
      onMutated={vi.fn()}
    />,
    { wrapper },
  )
}

beforeEach(() => {
  patchIssue.mockReset()
  intelligence.mockReset()
  effectiveTags.mockReset()
  patchIssue.mockResolvedValue({
    issue: { ...card, status: 'read' },
    thread: { thread_id: 10, status: 'active', issues_remaining: 1 },
    read_event_created: true,
    rating_event_created: false,
    replayed: false,
  })
  intelligence.mockResolvedValue(metadata)
  effectiveTags.mockResolvedValue(tags)
})

describe('ComicIssueReadingCard roll parity', () => {
  it('does not request provider or tag details for an untouched dense row', () => {
    mount()

    expect(screen.getByTestId('comic-issue-reading-card')).toBeVisible()
    expect(screen.getByTestId('comic-issue-card')).toBeVisible()
    expect(screen.queryByTestId('comic-issue-reading-details')).not.toBeInTheDocument()
    expect(intelligence).not.toHaveBeenCalled()
    expect(effectiveTags).not.toHaveBeenCalled()
  })

  it('opens the exact issue provider credits and tags when Read now is used', async () => {
    mount()

    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))

    expect(await screen.findByText('Mike Mignola')).toBeVisible()
    expect(screen.getByText('writer, artist')).toBeVisible()
    expect(await screen.findByText('Physical')).toBeVisible()
    expect(intelligence).toHaveBeenCalledExactlyOnceWith(37)
    expect(effectiveTags).toHaveBeenCalledExactlyOnceWith(37)
    // The provider pillar already renders the cover for this exact issue.
    const localCover = screen.getByTestId('comic-issue-card').querySelector('[data-testid="comic-issue-cover"]')
    expect(localCover).toBeNull()
  })

  it('retains the owned cover when provider metadata has no image', async () => {
    intelligence.mockResolvedValue({ ...metadata, image_url: null })
    mount()

    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))

    expect(await screen.findByText('Mike Mignola')).toBeVisible()
    expect(screen.getByTestId('comic-issue-card').querySelector('[data-testid="comic-issue-cover"]')).not.toBeNull()
  })

  it('opens details on mount for a reader header that is already showing the issue', async () => {
    mount({ showReadingDetails: true })

    expect(await screen.findByText('Mike Mignola')).toBeVisible()
    expect(await screen.findByText('Physical')).toBeVisible()
    expect(intelligence).toHaveBeenCalledExactlyOnceWith(37)
    expect(effectiveTags).toHaveBeenCalledExactlyOnceWith(37)
  })

  it('keeps a retryable provider failure from hiding the issue tags or the local cover', async () => {
    intelligence
      .mockRejectedValueOnce(new Error('creators offline'))
      .mockResolvedValueOnce(metadata)
    mount()

    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load comic details: creators offline',
    )
    expect(await screen.findByText('Physical')).toBeVisible()
    expect(screen.getByTestId('comic-issue-card').querySelector('[data-testid="comic-issue-cover"]')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry comic details' }))
    expect(await screen.findByText('Mike Mignola')).toBeVisible()
    expect(intelligence).toHaveBeenCalledTimes(2)
  })

  it('never requests details for a provider-only entry that is not owned', async () => {
    mount({ isOwned: false })

    expect(screen.queryByRole('button', { name: 'Read now' })).not.toBeInTheDocument()
    expect(intelligence).not.toHaveBeenCalled()
    expect(effectiveTags).not.toHaveBeenCalled()
  })
})
