import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { DEFAULT_CREATE_STATE, type QueueFormState } from '../pages/QueuePage/types'
import type { ThreadListItem } from '../types'
import { issuesApi } from '../services/api-issues'

/**
 * Full-draft regression for #5864 / MQA-QUEUE-008: staging an issue removal in
 * the Queue page Edit Series dialog must make the close control ask before
 * discarding. The structure preview is deliberately left unresolved to cover
 * the window where the staged removal is not yet a queued mutation.
 */

vi.mock('../components/PositionSlider', () => ({ default: () => null }))
vi.mock('../components/DependencyBuilder', () => ({ default: () => null }))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))
vi.mock('../components/AddSeriesFromComicVineDialog', () => ({ default: () => null }))
vi.mock('../hooks/usePotentialDuplicates', () => ({
  usePotentialDuplicates: () => ({ matches: [], isChecking: false, isError: false }),
}))
vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(), create: vi.fn(), previewCreate: vi.fn(), previewDelete: vi.fn(),
    previewReorder: vi.fn(), markRead: vi.fn(), markUnread: vi.fn(), delete: vi.fn(), reorder: vi.fn(),
  },
}))
vi.mock('../services/api-dependencies', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-dependencies')>()
  return {
    ...actual,
    issueDependenciesApi: { listForThread: vi.fn().mockResolvedValue({ thread_id: 99, issues: [] }) },
    dependenciesApi: { getIssueDependencies: vi.fn(), getConnectedThreads: vi.fn() },
  }
})

const mockedIssuesApiList = vi.mocked(issuesApi.list)
const mockedPreviewDelete = vi.mocked(issuesApi.previewDelete)
const mockedDelete = vi.mocked(issuesApi.delete)

// SAFETY: test fixture supplies only the fields QueueModals and IssueToggleList read for this edit draft.
const EDITING_THREAD = {
  id: 99,
  title: 'Detective Comics',
  notes: null,
  issues_remaining: 1,
  total_issues: 4,
  queue_position: 1,
  blocking_reasons: [],
  created_at: '2026-03-08T00:00:00Z',
  is_blocked: false,
  last_activity_at: null,
  status: 'active',
} as ThreadListItem

function Harness({ onCloseEdit }: { onCloseEdit: () => void }) {
  const [editForm, setEditForm] = useState<QueueFormState>({ ...DEFAULT_CREATE_STATE, title: 'Detective Comics' })
  return (
    <QueueModals
      openModal="edit"
      createForm={DEFAULT_CREATE_STATE}
      editForm={editForm}
      setCreateForm={vi.fn()}
      setEditForm={setEditForm}
      issuePreview={null}
      issueParseError={null}
      issueParseWarnings={[]}
      issueParseBreakdown={[]}
      editingThread={EDITING_THREAD}
      repositioningThread={null}
      dependencyThread={null}
      threadToMigrate={null}
      showMigrationDialog={false}
      reactivateThreadId=""
      setReactivateThreadId={vi.fn()}
      issuesToAdd={1}
      setIssuesToAdd={vi.fn()}
      activeThreads={[]}
      completedThreads={[]}
      queueSize={1}
      onCreateSubmit={vi.fn(async () => undefined)}
      onEditSubmit={vi.fn(async () => undefined)}
      onReactivateSubmit={vi.fn(async () => undefined)}
      onRepositionConfirm={vi.fn()}
      onDependencyChanged={vi.fn(async () => undefined)}
      onCloseCreate={vi.fn()}
      onCloseEdit={onCloseEdit}
      onCloseReactivate={vi.fn()}
      onCloseReposition={vi.fn()}
      onCloseDependency={vi.fn()}
      onMigrationComplete={vi.fn(async () => undefined)}
      onMigrationSkip={vi.fn()}
      onCloseMigration={vi.fn()}
      onOpenMigrationDialog={vi.fn()}
      isPendingCreate={false}
      isPendingEdit={false}
      isPendingReactivate={false}
      showRollNudge={false}
      onDismissRollNudge={vi.fn()}
      onRollNudgeNavigate={vi.fn()}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedIssuesApiList.mockResolvedValue({
    issues: [{ id: 2, thread_id: 99, issue_number: '4', status: 'unread', read_at: null, created_at: 'now' }],
    total_count: 1, page_size: 100, next_page_token: null,
  })
  // Leave the preview in flight: the reader staged the removal but has not
  // confirmed the projected before/after rows yet.
  mockedPreviewDelete.mockImplementation(() => new Promise(() => undefined))
  mockedDelete.mockResolvedValue()
})

describe('Queue Edit Series staged removal discard (#5864)', () => {
  it('asks before discarding a draft whose only change is a staged issue removal', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseEdit={close} />)
    await waitFor(() => expect(screen.getByTestId('issue-delete-2')).toBeInTheDocument())

    await user.click(screen.getByTestId('issue-delete-2'))
    await screen.findByTestId('delete-issue-dialog')
    await user.click(screen.getByTestId('confirm-delete-issue'))

    await user.click(screen.getByRole('button', { name: 'Close modal' }))
    const prompt = await screen.findByRole('dialog', { name: 'Discard changes?' })
    expect(prompt).toBeInTheDocument()
    expect(close).not.toHaveBeenCalled()

    await user.click(within(prompt).getByRole('button', { name: 'Keep editing' }))
    expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Edit Series' })).toBeInTheDocument()
    expect(close).not.toHaveBeenCalled()
  })

  it('discards only after confirmation and never deletes the issue on close', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseEdit={close} />)
    await waitFor(() => expect(screen.getByTestId('issue-delete-2')).toBeInTheDocument())

    await user.click(screen.getByTestId('issue-delete-2'))
    await screen.findByTestId('delete-issue-dialog')
    await user.click(screen.getByTestId('confirm-delete-issue'))
    await user.click(screen.getByRole('button', { name: 'Close modal' }))

    const prompt = await screen.findByRole('dialog', { name: 'Discard changes?' })
    await user.click(within(prompt).getByRole('button', { name: 'Discard changes' }))
    expect(close).toHaveBeenCalledTimes(1)
    expect(mockedDelete).not.toHaveBeenCalled()
  })

  it('closes an unchanged draft without prompting', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseEdit={close} />)
    await waitFor(() => expect(screen.getByTestId('issue-delete-2')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Close modal' }))
    expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
    expect(close).toHaveBeenCalledTimes(1)
  })
})
