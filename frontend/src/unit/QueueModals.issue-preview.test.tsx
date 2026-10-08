import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import {
  DEFAULT_CREATE_STATE,
  type QueueFormState,
} from '../pages/QueuePage/types'
import { parseIssueRangeDetailed } from '../utils/issueParser'
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

  const parsed = parseIssueRangeDetailed(issues)
  const hasPreview = issues.trim().length > 0

  return (
    <QueueModals
      openModal="create"
      createForm={createForm}
      editForm={editForm}
      setCreateForm={setCreateForm}
      setEditForm={setEditForm}
      issuePreview={hasPreview ? parsed.total : null}
      issueParseError={null}
      issueParseWarnings={hasPreview ? parsed.warnings : []}
      issueParseBreakdown={hasPreview ? parsed.breakdown : []}
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
  it('warns that garbage input becomes a literal issue name instead of accepting it silently (#3262)', async () => {
    render(<Harness issues="xyz" />)

    expect(screen.getByText('Will create 1 issue')).toBeInTheDocument()
    expect(
      screen.getByText("Couldn't parse 'xyz' — it will be created as a literal issue name"),
    ).toBeInTheDocument()
    expect(screen.getByTestId('issue-parse-warnings')).toBeInTheDocument()
  })

  it('warns about decimal input the user reported as a literal issue (#3262)', () => {
    render(<Harness issues="1.5" />)

    expect(
      screen.getByText("Couldn't parse '1.5' — it will be created as a literal issue name"),
    ).toBeInTheDocument()
  })

  it('does not warn for recognized numbers, ranges, or named issues (#3262)', () => {
    render(<Harness issues="1-3, Annual 1, ½" />)

    expect(screen.getByText('Will create 5 issues')).toBeInTheDocument()
    expect(screen.queryByTestId('issue-parse-warnings')).not.toBeInTheDocument()
  })

  it('exposes a breakdown of every parsed token so typos are visible (#3262)', async () => {
    const user = userEvent.setup()
    render(<Harness issues="oops, 1-2" />)

    const breakdown = screen.getByTestId('issue-parse-breakdown')
    expect(breakdown).toBeInTheDocument()
    expect(screen.getByText('oops:')).toBeInTheDocument()
    expect(screen.getByText('1-2:')).toBeInTheDocument()

    await user.click(screen.getByText('Show issue breakdown'))
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })
})
