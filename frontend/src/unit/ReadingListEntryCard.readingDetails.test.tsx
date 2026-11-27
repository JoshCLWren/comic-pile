import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingListEntryCard from '../components/ReadingListEntryCard'
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api-comicvine'
import type { CustomCBLEntry } from '../services/api-custom-cbl'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'
import { tagsApi, type EffectiveTagsResponse, type Tag } from '../services/api-tags'

vi.mock('../components/ComicIssueMappingAction', () => ({
  default: ({ issueId }: { issueId: number | null }) => <span data-testid="shared-map-action">{issueId}</span>,
}))

const patchIssue = vi.spyOn(issueCardsApi, 'patchIssue')
const intelligence = vi.spyOn(comicVineApi, 'getIssueIntelligence')
const effectiveTags = vi.spyOn(tagsApi, 'effectiveForIssue')

const entry: CustomCBLEntry = {
  id: 1,
  position: 1,
  issue_id: 91,
  thread_id: 7,
  series_name: 'Saga',
  issue_number: '3',
  status: 'unread',
  gate: 'none',
  skipped: false,
  is_checkpoint: false,
  availability: 'available',
  checkpoint_target_issue_ids: [],
}

const card: IssueCard = {
  issue_id: 91,
  thread_id: 7,
  thread_title: 'Saga',
  issue_number: '3',
  status: 'unread',
  rating: null,
  mapping_state: 'unmapped',
  has_confirmed_identity: false,
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
  creators: [{ creator_id: null, name: 'Fiona Staples', roles: ['artist'] }],
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

const noop = vi.fn()

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return render(
    <ul>
      <ReadingListEntryCard
        entry={entry}
        index={0}
        entryCount={1}
        isNextUnread
        mode="strict"
        waitingOn={[]}
        nameOf={() => 'Saga #3'}
        expanded={false}
        moveDestination="1"
        moveTarget="1"
        disabled={false}
        insertActive={null}
        onCheckpoint={noop}
        onMoveEarlier={noop}
        onMoveLater={noop}
        onRemove={noop}
        onToggleOptions={noop}
        onGate={noop}
        onSkip={noop}
        onDestinationChange={noop}
        onMoveToPosition={noop}
        onMoveTargetChange={noop}
        onMoveBeforeIssue={noop}
        onMoveAfterIssue={noop}
        onInsertBefore={noop}
        onInsertAfter={noop}
        card={card}
        onIssueMutated={noop}
      />
    </ul>,
    { wrapper },
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  patchIssue.mockResolvedValue({
    issue: { ...card, status: 'read' },
    thread: { thread_id: 7, status: 'active', issues_remaining: 1 },
    read_event_created: true,
    rating_event_created: false,
    replayed: false,
  })
  intelligence.mockResolvedValue(metadata)
  effectiveTags.mockResolvedValue(tags)
})

describe('Reading List entry direct read', () => {
  it('keeps staged editor rows free of provider and tag requests', () => {
    mount()

    expect(screen.getByTestId('comic-issue-card')).toBeVisible()
    expect(screen.queryByTestId('comic-issue-reading-details')).not.toBeInTheDocument()
    expect(intelligence).not.toHaveBeenCalled()
    expect(effectiveTags).not.toHaveBeenCalled()
  })

  it('shows the rolled-comic creator and tag details for the exact entry on Read now', async () => {
    mount()

    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))

    expect(await screen.findByText('Fiona Staples')).toBeVisible()
    expect(await screen.findByText('Physical')).toBeVisible()
    expect(intelligence).toHaveBeenCalledExactlyOnceWith(91)
    expect(effectiveTags).toHaveBeenCalledExactlyOnceWith(91)
    expect(noop).not.toHaveBeenCalledWith(expect.objectContaining({ issue: expect.anything() }))
  })
})
