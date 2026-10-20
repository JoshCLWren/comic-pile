import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { DEFAULT_CREATE_STATE, type QueueFormState } from '../pages/QueuePage/types'

vi.mock('../components/Modal', () => ({
  default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: React.ReactNode }) =>
    isOpen ? <section aria-label={title}>{children}</section> : null,
}))
vi.mock('../components/PositionSlider', () => ({ default: () => null }))
vi.mock('../components/DependencyBuilder', () => ({ default: () => null }))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))
vi.mock('../components/AddSeriesFromComicVineDialog', () => ({ default: () => null }))
vi.mock('../pages/QueuePage/IssueToggleList', () => ({ IssueToggleList: () => null }))
vi.mock('../pages/QueuePage/FormatSelect', () => ({
  FormatSelect: ({ id, value, onChange }: { id: string; value: string; onChange: (value: string) => void }) => (
    <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="Comic">Comic</option>
    </select>
  ),
}))

const ERROR_TEXT = 'Title cannot be empty or whitespace only'

function CreateHarness() {
  const [createForm, setCreateForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  return (
    <QueueModals
      openModal="create"
      createForm={createForm}
      editForm={editForm}
      setCreateForm={setCreateForm}
      setEditForm={setEditForm}
      issuePreview={1}
      issueParseError={null}
      issueParseWarnings={[]}
      issueParseBreakdown={[]}
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

function EditHarness() {
  const [createForm, setCreateForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  return (
    <QueueModals
      openModal="edit"
      createForm={createForm}
      editForm={editForm}
      setCreateForm={setCreateForm}
      setEditForm={setEditForm}
      issuePreview={null}
      issueParseError={null}
      issueParseWarnings={[]}
      issueParseBreakdown={[]}
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

describe('QueueModals title validation (create dialog)', () => {
  it('blocks empty titles, shows the linked error, and disables submit', () => {
    render(<CreateHarness />)
    const input = screen.getByLabelText('Title') as HTMLInputElement
    const submit = screen.getByRole('button', { name: 'Create Series' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText(ERROR_TEXT)).toBeInTheDocument()
    expect(submit).toBeDisabled()
  })

  it('recovers after a valid title is entered', async () => {
    const user = userEvent.setup()
    render(<CreateHarness />)
    const input = screen.getByLabelText('Title') as HTMLInputElement
    const submit = screen.getByRole('button', { name: 'Create Series' })
    await user.type(input, 'Valid Title')
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(screen.queryByText(ERROR_TEXT)).not.toBeInTheDocument()
    expect(submit).not.toBeDisabled()
  })

  it('blocks whitespace-only input typed into the field', async () => {
    const user = userEvent.setup()
    render(<CreateHarness />)
    const input = screen.getByLabelText('Title') as HTMLInputElement
    const submit = screen.getByRole('button', { name: 'Create Series' })
    await user.type(input, '   ')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText(ERROR_TEXT)).toBeInTheDocument()
    expect(submit).toBeDisabled()
  })
})

describe('QueueModals title validation (edit dialog)', () => {
  it('blocks empty titles, shows the linked error, and disables submit', () => {
    render(<EditHarness />)
    const input = screen.getByLabelText('Title') as HTMLInputElement
    const submit = screen.getByRole('button', { name: 'Save Changes' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText(ERROR_TEXT)).toBeInTheDocument()
    expect(submit).toBeDisabled()
  })

  it('recovers after a valid title is entered', async () => {
    const user = userEvent.setup()
    render(<EditHarness />)
    const input = screen.getByLabelText('Title') as HTMLInputElement
    const submit = screen.getByRole('button', { name: 'Save Changes' })
    await user.type(input, 'Valid Title')
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(screen.queryByText(ERROR_TEXT)).not.toBeInTheDocument()
    expect(submit).not.toBeDisabled()
  })

  it('blocks whitespace-only input typed into the field', async () => {
    const user = userEvent.setup()
    render(<EditHarness />)
    const input = screen.getByLabelText('Title') as HTMLInputElement
    const submit = screen.getByRole('button', { name: 'Save Changes' })
    await user.type(input, '   ')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText(ERROR_TEXT)).toBeInTheDocument()
    expect(submit).toBeDisabled()
  })
})
