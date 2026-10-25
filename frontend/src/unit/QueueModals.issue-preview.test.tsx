import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import {
  DEFAULT_CREATE_STATE,
  type QueueFormState,
} from '../pages/QueuePage/types'
import { parseIssueRangeDetailed, validateIssueRangeForStaging } from '../utils/issueParser'
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

function Harness({ issues }: { issues: string }) {
  const [createForm, setCreateForm] = useState<QueueFormState>({
    ...DEFAULT_CREATE_STATE,
    issues,
  })
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)

  // Mirror the production preview gate in useQueueModals (#4161): the preview
  // only renders for staging-valid input and surfaces the validation error for
  // anything the Save path would block.
  const validation = validateIssueRangeForStaging(issues)
  const hasPreview = issues.trim().length > 0 && validation.valid
  const parsed = hasPreview ? parseIssueRangeDetailed(issues) : null

  return (
    <QueueModals
      openModal="create"
      createForm={createForm}
      editForm={editForm}
      setCreateForm={setCreateForm}
      setEditForm={setEditForm}
      issuePreview={hasPreview && parsed ? parsed.total : null}
      issueParseError={hasPreview && parsed ? null : validation.error}
      issueParseWarnings={hasPreview && parsed ? parsed.warnings : []}
      issueParseBreakdown={hasPreview && parsed ? parsed.breakdown : []}
      editingThread={null}
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
      queueSize={0}
      onCreateSubmit={vi.fn(async (event) => event.preventDefault())}
      onEditSubmit={vi.fn(async (event) => event.preventDefault())}
      onReactivateSubmit={vi.fn(async (event) => event.preventDefault())}
      onRepositionConfirm={vi.fn()}
      onDependencyChanged={vi.fn(async () => undefined)}
      onCloseCreate={vi.fn()}
      onCloseEdit={vi.fn()}
      onCloseReactivate={vi.fn()}
      onCloseReposition={vi.fn()}
      onCloseDependency={vi.fn()}
      onMigrationComplete={vi.fn(async () => undefined)}
      onMigrationSkip={vi.fn()}
      onCloseMigration={vi.fn()}
      onOpenMigrationDialog={vi.fn()}
      onCloseAddSeriesComicVine={vi.fn()}
      isPendingCreate={false}
      isPendingEdit={false}
      isPendingReactivate={false}
      showRollNudge={false}
      onDismissRollNudge={vi.fn()}
      onRollNudgeNavigate={vi.fn()}
    />
  )
}

describe('Add Series issue input preview', () => {
  it('previews numbered labels such as "2b" without a parse warning (#4161)', () => {
    render(<Harness issues="2b" />)

    expect(screen.getByText('Will create 1 issue')).toBeInTheDocument()
    expect(screen.queryByTestId('issue-parse-warnings')).not.toBeInTheDocument()
    expect(screen.queryByText(/Couldn't parse/)).not.toBeInTheDocument()
  })

  it('does not promise creation or count invalid tokens toward the preview (#4161)', () => {
    render(<Harness issues="abc" />)

    expect(screen.queryByText(/Will create/)).not.toBeInTheDocument()
    expect(screen.getByText(/is not a valid issue number/)).toBeInTheDocument()
    expect(screen.queryByText(/will be created as a literal issue/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create series/i })).toBeDisabled()
  })

  it('surfaces the staging error instead of promising literal issue creation (#3262/#4161)', () => {
    render(<Harness issues="xyz" />)

    expect(screen.getByText(/is not a valid issue number/)).toBeInTheDocument()
    expect(screen.queryByText(/Will create/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Couldn't parse/)).not.toBeInTheDocument()
  })

  it('does not warn for recognized numbers, ranges, or named issues (#3262)', () => {
    render(<Harness issues="1-3, Annual 1, ½" />)

    expect(screen.getByText('Will create 5 issues')).toBeInTheDocument()
    expect(screen.queryByTestId('issue-parse-warnings')).not.toBeInTheDocument()
  })

  it('exposes a breakdown of every parsed token so labeled issues are visible (#3262)', async () => {
    const user = userEvent.setup()
    render(<Harness issues="1-3, Annual 1" />)

    const breakdown = screen.getByTestId('issue-parse-breakdown')
    expect(breakdown).toBeInTheDocument()
    expect(screen.getByText('1-3:')).toBeInTheDocument()
    expect(screen.getByText('Annual 1:')).toBeInTheDocument()

    await user.click(screen.getByText('Show issue breakdown'))
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })
})
