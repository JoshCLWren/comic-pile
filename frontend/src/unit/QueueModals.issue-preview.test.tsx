import { useEffect } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { useQueueModals } from '../pages/QueuePage/useQueueModals'
import { DEFAULT_CREATE_STATE } from '../pages/QueuePage/types'
vi.mock('../components/Modal', () => ({
  default: ({
    isOpen,
    title,
    children,
  }: {
    isOpen: boolean
    title: string
    children: React.ReactNode
  }) => (isOpen ? <section aria-label={title}>{children}</section> : null),
}))

vi.mock('../components/PositionSlider', () => ({
  default: () => null,
}))

vi.mock('../components/DependencyBuilder', () => ({
  default: () => null,
}))

vi.mock('../components/MigrationDialog', () => ({
  default: () => null,
}))

vi.mock('../pages/QueuePage/IssueToggleList', () => ({
  IssueToggleList: () => null,
}))

// Stable references: the hook memoizes callbacks on these, so re-creating them
// per render would retrigger the preview effect forever.
const restoreActionMocks = vi.hoisted(() => ({
  setRestoreAction: vi.fn(),
  clearRestoreAction: vi.fn(),
}))

vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => restoreActionMocks,
}))

vi.mock('../pages/QueuePage/FormatSelect', () => ({
  FormatSelect: ({
    id,
    value,
    onChange,
  }: {
    id: string
    value: string
    onChange: (value: string) => void
  }) => (
    <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="Comic">Comic</option>
    </select>
  ),
}))

// The real preview hook reports create failures through the toast context;
// the stub keeps the harness renderable without a ToastProvider.
const createFailureToastDeps = {
  toastHook: () => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] }),
}

/**
 * Render the create modal from the production `useQueueModals` hook. The
 * preview count, warnings, and parse error all come from the hook itself, so
 * these tests fail if the real preview effect breaks (#4161 review feedback).
 */
function PreviewHarness({ issues }: { issues: string }) {
  const modals = useQueueModals({
    threads: [],
    onCreated: async () => undefined,
    onUpdated: async () => undefined,
    onReactivated: async () => undefined,
    refetchSession: async () => undefined,
    submitCreate: async () => ({}),
    submitEdit: vi.fn(),
    submitReactivate: vi.fn(),
    isPendingCreate: false,
    isPendingEdit: false,
    showRollNudge: false,
    onDismissRollNudge: vi.fn(),
    onRollNudgeNavigate: vi.fn(),
  }, createFailureToastDeps)
  const { showCreateModal, setCreateForm } = modals

  useEffect(() => {
    showCreateModal()
    // A title is required for the submit button to be enabled, so seed one to
    // isolate the issue-preview behavior under test.
    setCreateForm({ ...DEFAULT_CREATE_STATE, title: 'Preview series', issues })
  }, [issues, setCreateForm, showCreateModal])

  return (
    <QueueModals
      openModal={modals.openModal}
      createForm={modals.createForm}
      editForm={modals.editForm}
      setCreateForm={modals.setCreateForm}
      setEditForm={modals.setEditForm}
      issuePreview={modals.issuePreview}
      issueParseError={modals.issueParseError}
      issueParseWarnings={modals.issueParseWarnings}
      issueParseBreakdown={modals.issueParseBreakdown}
      editingThread={modals.editingThread}
      repositioningThread={modals.repositioningThread}
      dependencyThread={modals.dependencyThread}
      threadToMigrate={modals.threadToMigrate}
      showMigrationDialog={modals.showMigrationDialog}
      reactivateThreadId={modals.reactivateThreadId}
      setReactivateThreadId={modals.setReactivateThreadId}
      issuesToAdd={modals.issuesToAdd}
      setIssuesToAdd={modals.setIssuesToAdd}
      activeThreads={[]}
      completedThreads={[]}
      queueSize={0}
      onCreateSubmit={modals.handleCreateSubmit}
      onEditSubmit={modals.handleEditSubmit}
      onReactivateSubmit={modals.handleReactivateSubmit}
      onRepositionConfirm={vi.fn()}
      onDependencyChanged={async () => undefined}
      onCloseCreate={modals.closeCreateModal}
      onCloseEdit={modals.closeEditModal}
      onCloseReactivate={modals.closeReactivateModal}
      onCloseReposition={modals.closeRepositionModal}
      onCloseDependency={modals.closeDependenciesModal}
      onMigrationComplete={modals.handleMigrationComplete}
      onMigrationSkip={modals.handleMigrationSkip}
      onCloseMigration={modals.closeMigrationDialog}
      onOpenMigrationDialog={modals.openMigrationDialog}
      onCloseAddSeriesComicVine={modals.closeAddSeriesComicVineModal}
      isPendingCreate={modals.isPendingCreate}
      isPendingEdit={modals.isPendingEdit}
      isPendingReactivate={false}
      showRollNudge={modals.showRollNudge}
      onDismissRollNudge={modals.dismissRollNudge}
      onRollNudgeNavigate={modals.rollNudgeNavigate}
    />
  )
}

function Harness({ issues }: { issues: string }) {
  return (
    <MemoryRouter>
      <PreviewHarness issues={issues} />
    </MemoryRouter>
  )
}

describe('Add Series issue input preview', () => {
  it('previews numbered labels such as "2b" without a parse warning (#4161)', async () => {
    render(<Harness issues="2b" />)

    expect(await screen.findByText('Will create 1 issue')).toBeInTheDocument()
    expect(screen.queryByTestId('issue-parse-warnings')).not.toBeInTheDocument()
    expect(screen.queryByText(/Couldn't parse/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create series/i })).toBeEnabled()
  })

  it.each(['abc', '1-3, abc', '-3', '19-'])(
    'does not promise creation or count invalid tokens toward the preview (%s) (#4161)',
    async (issues) => {
      render(<Harness issues={issues} />)

      expect(await screen.findByText(/is not a valid issue number/)).toBeInTheDocument()
      expect(screen.queryByText(/Will create/)).not.toBeInTheDocument()
      expect(screen.queryByText(/will be created as a literal issue/)).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: /create series/i })).toBeDisabled()
    },
  )

  it('surfaces the staging error instead of promising literal issue creation (#3262/#4161)', async () => {
    render(<Harness issues="xyz" />)

    expect(await screen.findByText(/is not a valid issue number/)).toBeInTheDocument()
    expect(screen.queryByText(/Will create/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Couldn't parse/)).not.toBeInTheDocument()
  })

  it('does not warn for recognized numbers, ranges, or named issues (#3262)', async () => {
    render(<Harness issues="1-3, Annual 1, ½" />)

    expect(await screen.findByText('Will create 5 issues')).toBeInTheDocument()
    expect(screen.queryByTestId('issue-parse-warnings')).not.toBeInTheDocument()
  })

  it('exposes a breakdown of every parsed token so labeled issues are visible (#3262)', async () => {
    const user = userEvent.setup()
    render(<Harness issues="1-3, Annual 1" />)

    const breakdown = await screen.findByTestId('issue-parse-breakdown')
    expect(breakdown).toBeInTheDocument()
    expect(screen.getByText('1-3:')).toBeInTheDocument()
    expect(screen.getByText('Annual 1:')).toBeInTheDocument()

    await user.click(screen.getByText('Show issue breakdown'))
    await waitFor(() => expect(screen.getByText('3')).toBeInTheDocument())
  })
})
