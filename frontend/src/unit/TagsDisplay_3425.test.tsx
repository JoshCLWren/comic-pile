import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import QueueThreadCard from '../pages/QueuePage/QueueThreadCard'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { BlockingDependency, ThreadListItem } from '../types'
import type { RollBootstrapThread, ThreadExclusionReason } from '../types/rollBootstrap'
import type { Tag } from '../services/api-tags'

const tag: Tag = {
  id: 7,
  name: 'Physical',
  normalized_name: 'physical',
  scope: 'global',
  owner_user_id: null,
  color: '#ff0000',
  created_at: '2024-01-01T00:00:00.000Z',
  updated_at: '2024-01-01T00:00:00.000Z',
}

function queueThread(): ThreadListItem {
  return {
    id: 1,
    title: 'Spider-Man',
    format: 'Comic',
    issues_remaining: 5,
    total_issues: 10,
    next_unread_issue_number: null,
    queue_position: 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    notes: null,
    last_activity_at: null,
    created_at: '2024-01-01T00:00:00.000Z',
    comicvine_mapping: null,
    tags: [tag],
  }
}

function poolThread(id: number, title: string): RollBootstrapThread {
  return { id, title, format: 'Comic', issue_number: '1', route_labels: [], tags: [tag] }
}

function exclusionThread(): ThreadExclusionReason {
  return { thread_id: 9, title: 'Excluded Saga', format: 'Comic', reason: 'blocked', tags: [tag] }
}

describe('issue #3425 tag display', () => {
  it('shows tags on queue rows', () => {
    render(
      <MemoryRouter>
        <QueueThreadCard
          thread={queueThread()}
          index={0}
          isBlocked={false}
          blockingDependencies={[] as BlockingDependency[]}
          crossoverGroups={[]}
          crossoverGroupsLoading={false}
          crossoverGroupsError={false}
          isDragOver={false}
          snoozeIcon=""
          snoozeLabel=""
          snoozeDisabled={false}
          onCardClick={vi.fn()}
          onDragStart={vi.fn()}
          onDragEnd={vi.fn()}
          onDragOver={vi.fn()}
          onDrop={vi.fn()}
          onRead={vi.fn()}
          onSnooze={vi.fn()}
          onMoveToFront={vi.fn()}
          onMoveToBack={vi.fn()}
          onReposition={vi.fn()}
          onEdit={vi.fn()}
          onDependencies={vi.fn()}
          onDelete={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect(screen.getByLabelText('Tags for Spider-Man')).toHaveTextContent('Physical')
  })

  it('shows tags on roll die faces and every pool section', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          pool={[poolThread(1, 'Spider-Man')]}
          blockedThreads={[poolThread(2, 'Blocked Saga')]}
          blockingDependencyMap={{}}
          dieSize={6}
          isRatingView={false}
          selectedThreadId={null}
          staleThread={{ ...poolThread(3, 'Stale Saga'), days: 30 }}
          staleThreadCount={1}
          snoozedThreads={[poolThread(4, 'Snoozed Saga')]}
          snoozedExpanded
          skippedThreads={[poolThread(5, 'Skipped Saga')]}
          skippedExpanded
          blockedExpanded
          staleExpanded
          inactiveExpanded
          inactiveThreads={[exclusionThread()]}
          onToggleInactive={vi.fn()}
          onThreadClick={vi.fn()}
          onUnsnooze={vi.fn()}
          onUnskip={vi.fn()}
          onReadStale={vi.fn()}
          onToggleSnoozed={vi.fn()}
          onToggleSkipped={vi.fn()}
          onToggleStale={vi.fn()}
          onToggleBlocked={vi.fn()}
          onShuffle={vi.fn()}
          unsnoozeIsPending={false}
          unskipIsPending={false}
          shuffleIsPending={false}
        />
      </MemoryRouter>,
    )
    expect(screen.getByLabelText('Tags for Spider-Man')).toHaveTextContent('Physical')
    expect(screen.getByLabelText('Tags for Blocked Saga')).toHaveTextContent('Physical')
    expect(screen.getByLabelText('Tags for Stale Saga')).toHaveTextContent('Physical')
    expect(screen.getByLabelText('Tags for Snoozed Saga')).toHaveTextContent('Physical')
    expect(screen.getByLabelText('Tags for Skipped Saga')).toHaveTextContent('Physical')
    expect(screen.getByLabelText('Tags for Excluded Saga')).toHaveTextContent('Physical')
  })
})
