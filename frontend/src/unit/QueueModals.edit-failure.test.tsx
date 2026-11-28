import { createElement, type ReactNode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { useQueueModals } from '../pages/QueuePage/useQueueModals'
import { DEFAULT_CREATE_STATE, type EditThreadData } from '../pages/QueuePage/types'
import type { Thread, ThreadListItem } from '../types'
import { BugReportRestoreContext } from '../contexts/BugReportRestoreContextValue'

/**
 * #5951 regression: a rejected Queue Edit Series save must surface the server
 * detail inside the still-open dialog and keep the unsaved draft for retry.
 */

vi.mock('../components/PositionSlider', () => ({ default: () => null }))
vi.mock('../components/DependencyBuilder', () => ({ default: () => null }))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))

// SAFETY: fixture supplies only the fields QueueModals and useQueueModals read
// for the edit form. total_issues is null so no issue-toggle list is mounted.
const EDITING_THREAD = {
  id: 99,
  title: 'Test Series',
  format: 'Comic',
  notes: null,
  issues_remaining: 4,
  total_issues: null,
  queue_position: 1,
  blocking_reasons: [],
  created_at: '2026-03-08T00:00:00Z',
  is_blocked: false,
  last_activity_at: null,
  status: 'active',
} as ThreadListItem

const deps = {
  toastHook: () => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] }),
}

function wrapper({ children }: { children: ReactNode }) {
  return createElement(
    MemoryRouter,
    null,
    createElement(
      BugReportRestoreContext.Provider,
      {
        value: {
          setRestoreAction: vi.fn(),
          clearRestoreAction: vi.fn(),
          restoreLastView: vi.fn(),
        },
      },
      children,
    ),
  )
}

function Harness({ submitEdit }: {
  submitEdit: (input: { id: number; data: EditThreadData }) => Promise<Thread>
}) {
  const modals = useQueueModals(
    {
      threads: [],
      onCreated: vi.fn(async () => undefined),
      onUpdated: vi.fn(async () => undefined),
      onReactivated: vi.fn(async () => undefined),
      refetchRollState: vi.fn(async () => undefined),
      submitCreate: vi.fn(async () => ({ id: 1 })),
      submitEdit,
      submitReactivate: vi.fn(async () => undefined as never),
      isPendingCreate: false,
      isPendingEdit: false,
      showRollNudge: false,
      onDismissRollNudge: vi.fn(),
      onRollNudgeNavigate: vi.fn(),
    },
    deps,
  )

  return (
    <div>
      <button type="button" onClick={() => modals.showEditModal(EDITING_THREAD)}>Open edit</button>
      <button
        type="button"
        data-testid="save-edit"
        onClick={() => { void modals.handleEditSubmit({ preventDefault: vi.fn() } as never) }}
      >
        Save edit
      </button>
      <output data-testid="modal-state">{modals.openModal}</output>
      <QueueModals
        openModal={modals.openModal}
        createForm={DEFAULT_CREATE_STATE}
        editForm={modals.editForm}
        createError={null}
        editError={modals.editError}
        setCreateForm={vi.fn()}
        setEditForm={modals.setEditForm}
        issuePreview={null}
        issueParseError={null}
        issueParseWarnings={[]}
        issueParseBreakdown={[]}
        editingThread={modals.editingThread}
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
        onEditSubmit={modals.handleEditSubmit}
        onReactivateSubmit={vi.fn(async () => undefined)}
        onRepositionConfirm={vi.fn()}
        onDependencyChanged={vi.fn(async () => undefined)}
        onCloseCreate={vi.fn()}
        onCloseEdit={modals.closeEditModal}
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
        isIssuesLoading={modals.isIssuesLoading}
        showRollNudge={false}
        onDismissRollNudge={vi.fn()}
        onRollNudgeNavigate={vi.fn()}
      />
    </div>
  )
}

describe('Queue Edit Series failed save (#5951)', () => {
  it('shows the server detail, keeps the dialog open, and retains the draft', async () => {
    const submitEdit = vi.fn().mockRejectedValue({
      response: { status: 409, data: { detail: 'Thread snapshot is stale; reload and retry' } },
    })
    const user = userEvent.setup()
    render(<Harness submitEdit={submitEdit} />, { wrapper })

    await user.click(screen.getByRole('button', { name: 'Open edit' }))
    const title = screen.getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Renamed Series')
    await user.click(screen.getByTestId('save-edit'))

    await waitFor(() =>
      expect(screen.getByTestId('edit-thread-error')).toHaveTextContent(
        'Failed to save series: Thread snapshot is stale; reload and retry',
      ),
    )
    expect(screen.getByTestId('modal-state')).toHaveTextContent('edit')
    expect(screen.getByLabelText('Title')).toHaveValue('Renamed Series')
    expect(submitEdit).toHaveBeenCalledTimes(1)
  })
})
