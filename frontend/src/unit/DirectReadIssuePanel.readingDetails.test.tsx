import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DirectReadIssuePanel } from '../components/DirectReadIssuePanel'
import { issuesApi } from '../services/api-issues'
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api-comicvine'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'
import { tagsApi, type EffectiveTagsResponse } from '../services/api-tags'
import type { Issue } from '../types'

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
} as Issue

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

const tag = {
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
  // SAFETY: an effective entry for the same direct tag; the chip component only
  // reads the tag identity, the direct flag and the inheritance sources.
  effective_tags: [{ tag, direct: true, sources: [] } as unknown as EffectiveTagsResponse['effective_tags'][number]],
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
    expect(await screen.findByText('No tags yet.')).toBeVisible()
    expect(screen.queryByText('Fiona Staples')).not.toBeInTheDocument()
    expect(intelligence).toHaveBeenCalledExactlyOnceWith(91)
  })
})
