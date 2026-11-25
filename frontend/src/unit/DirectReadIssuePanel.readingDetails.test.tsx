import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DirectReadIssuePanel } from '../components/DirectReadIssuePanel'
import { issuesApi } from '../services/api-issues'
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api-comicvine'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'
import { tagsApi, type EffectiveTagsResponse, type Tag } from '../services/api-tags'
import type { Issue } from '../types'
import { injectModuleDoubles } from './injectModuleDoubles'

// The action card has its own suite; this suite proves the reading surface
// renders the post-roll provider detail and tags for the exact selected issue.
vi.mock('../components/ComicIssueCard', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../components/ComicIssueCard')>()
  return {
    // Only the action card is replaced: the provider cover the post-roll pillar
    // renders is the real shared component.
    ...actual,
    ComicIssueCard: ({ issueId, showCover }: { issueId: number; showCover?: boolean }) => (
      <article
        data-testid="direct-read-action-card"
        data-issue-id={issueId}
        data-show-cover={String(showCover)}
      />
    ),
  }
})

const getIssue = vi.spyOn(issuesApi, 'get')
const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')
const intelligence = vi.spyOn(comicVineApi, 'getIssueIntelligence')
const effectiveTags = vi.spyOn(tagsApi, 'effectiveForIssue')

const issue: Issue = {
  id: 91,
  thread_id: 7,
  issue_number: '3',
  status: 'unread',
  position: 3,
  created_at: '2026-11-24T00:00:00Z',
  read_at: null,
}

const card: IssueCard = {
  issue_id: 91,
  thread_id: 7,
  thread_title: 'Saga',
  issue_number: '3',
  status: 'unread',
  rating: null,
  mapping_state: 'confirmed',
  has_confirmed_identity: true,
  cover_image_url: null,
}

const metadata: ComicVineIssueIntelligence = {
  comicvine_issue_id: '555',
  comicvine_url: null,
  series_name: 'Saga',
  series_id: 12,
  issue_number: '3',
  name: 'Chapter Three',
  description: null,
  image_url: null,
  cover_date: null,
  store_date: null,
  // creator_id is null so the page makes no per-creator summary request; the
  // name and roles are still the credits the post-roll pillar renders.
  creators: [{ creator_id: null, name: 'Fiona Staples', roles: ['artist', 'cover'] }],
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
  target_id: 91,
  direct_tags: [tag],
  effective_tags: [{ tag, direct: true, sources: [] }],
}

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return render(
    <DirectReadIssuePanel threadId={7} threadTitle="Saga" preferredIssueId={91} />,
    { wrapper },
  )
}

beforeEach(() => {
  getIssue.mockReset()
  fetchCards.mockReset()
  intelligence.mockReset()
  effectiveTags.mockReset()
  getIssue.mockResolvedValue(issue)
  fetchCards.mockResolvedValue([card])
  intelligence.mockResolvedValue(metadata)
  effectiveTags.mockResolvedValue(tags)
})

describe('manual read surface roll parity', () => {
  it('shows the provider creators and the exact issue tags a roll would show', async () => {
    setup()

    expect(await screen.findByText('Fiona Staples')).toBeVisible()
    expect(screen.getByText('artist, cover')).toBeVisible()
    expect(await screen.findByText('Physical')).toBeVisible()

    // Both detail reads are scoped to the exact selected issue, once each.
    expect(intelligence).toHaveBeenCalledExactlyOnceWith(91)
    expect(effectiveTags).toHaveBeenCalledExactlyOnceWith(91)

    const actionCard = screen.getByTestId('direct-read-action-card')
    expect(actionCard).toHaveAttribute('data-issue-id', '91')
    // The provider cover is already rendered above, so the card drops its own.
    expect(actionCard).toHaveAttribute('data-show-cover', 'false')
  })

  it('shows a retryable provider error without hiding the issue tags', async () => {
    intelligence
      .mockRejectedValueOnce(new Error('creators offline'))
      .mockResolvedValueOnce(metadata)
    setup()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load comic details: creators offline',
    )
    expect(await screen.findByTestId('direct-read-action-card')).toHaveAttribute(
      'data-show-cover',
      'true',
    )
    expect(await screen.findByText('Physical')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Retry comic details' }))
    expect(await screen.findByText('Fiona Staples')).toBeVisible()
    expect(intelligence).toHaveBeenCalledTimes(2)
  })

  it('renders creators and tags while a read issue\'s saved rating is loading', async () => {
    getIssue.mockResolvedValue({ ...issue, status: 'read' })
    let resolveCards!: (cards: IssueCard[]) => void
    fetchCards.mockImplementation(() => new Promise<IssueCard[]>((resolve) => {
      resolveCards = resolve
    }))
    setup()

    expect(await screen.findByText('Fiona Staples')).toBeVisible()
    expect(await screen.findByText('Physical')).toBeVisible()
    expect(screen.getByText(/Loading the saved rating before editing/)).toBeVisible()
    expect(screen.queryByTestId('direct-read-action-card')).not.toBeInTheDocument()

    await act(async () => {
      resolveCards([{ ...card, status: 'read', rating: 4.5 }])
    })
    expect(await screen.findByTestId('direct-read-action-card')).toHaveAttribute(
      'data-issue-id',
      '91',
    )
  })

  it('keeps creators and tags visible when a read issue\'s saved rating fails', async () => {
    getIssue.mockResolvedValue({ ...issue, status: 'read' })
    fetchCards.mockRejectedValue(new Error('rating details offline'))
    setup()

    expect(await screen.findByText('Fiona Staples')).toBeVisible()
    expect(await screen.findByText('Physical')).toBeVisible()
    expect(await screen.findByRole('alert')).toHaveTextContent('rating details offline')
    expect(screen.getByText(/Retry details before editing/)).toBeVisible()
    expect(screen.queryByTestId('direct-read-action-card')).not.toBeInTheDocument()
    expect(intelligence).toHaveBeenCalledExactlyOnceWith(91)
    expect(effectiveTags).toHaveBeenCalledExactlyOnceWith(91)
  })

  it('keeps the read and rate actions for an unmapped issue without inventing credits', async () => {
    intelligence.mockResolvedValue(null)
    fetchCards.mockResolvedValue([
      { ...card, mapping_state: 'unmapped', has_confirmed_identity: false },
    ])
    effectiveTags.mockResolvedValue({ ...tags, direct_tags: [], effective_tags: [] })
    setup()

    expect(await screen.findByTestId('direct-read-action-card')).toHaveAttribute(
      'data-issue-id',
      '91',
    )
    expect(await screen.findByTestId('direct-read-action-card')).toHaveAttribute(
      'data-show-cover',
      'true',
    )
    expect(await screen.findByText('No tags yet.')).toBeVisible()
    expect(screen.queryByText('Fiona Staples')).not.toBeInTheDocument()
    expect(intelligence).toHaveBeenCalledExactlyOnceWith(91)
  })
})
