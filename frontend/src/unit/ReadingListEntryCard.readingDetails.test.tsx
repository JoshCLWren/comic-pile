import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingListEntryCard from '../components/ReadingListEntryCard'
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api-comicvine'
import { tagsApi, type EffectiveTagsResponse, type Tag } from '../services/api-tags'

const intelligence = vi.spyOn(comicVineApi, 'getIssueIntelligence')
const effectiveTags = vi.spyOn(tagsApi, 'effectiveForIssue')

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
  creators: [{ creator_id: null, name: 'Fiona Staples', roles: ['artist', 'cover'] }],
  story_arcs: [],
  metadata_status: 'deep_fetched',
}

const tag: Tag = {
  id: 4,
  name: 'Physical',
  normalized_name: 'physical',
  scope: 'private',
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

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ul>
        <ReadingListEntryCard
          entry={{
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
          }}
          index={0}
          entryCount={1}
          isNextUnread={false}
          mode="strict"
          waitingOn={[]}
          nameOf={() => 'Saga #3'}
          expanded={false}
          moveDestination="1"
          moveTarget="1"
          disabled={false}
          insertActive={null}
          onCheckpoint={vi.fn()}
          onMoveEarlier={vi.fn()}
          onMoveLater={vi.fn()}
          onRemove={vi.fn()}
          onToggleOptions={vi.fn()}
          onGate={vi.fn()}
          onSkip={vi.fn()}
          onDestinationChange={vi.fn()}
          onMoveToPosition={vi.fn()}
          onMoveTargetChange={vi.fn()}
          onMoveBeforeIssue={vi.fn()}
          onMoveAfterIssue={vi.fn()}
          onInsertBefore={vi.fn()}
          onInsertAfter={vi.fn()}
        />
      </ul>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  intelligence.mockReset()
  effectiveTags.mockReset()
  intelligence.mockResolvedValue(metadata)
  effectiveTags.mockResolvedValue(tags)
})

describe('ReadingListEntryCard read-now details parity (#5751)', () => {
  it('shows creators and tags after clicking Read now', async () => {
    renderCard()

    expect(screen.queryByText('Fiona Staples')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))

    expect(await screen.findByText('Fiona Staples')).toBeVisible()
    expect(screen.getByText('artist, cover')).toBeVisible()
    expect(await screen.findByText('Physical')).toBeVisible()
    expect(intelligence).toHaveBeenCalledExactlyOnceWith(91)
    expect(effectiveTags).toHaveBeenCalledExactlyOnceWith(91)
  })
})
