import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { DEFAULT_CREATE_STATE, type QueueFormState } from '../pages/QueuePage/types'

/**
 * Regression coverage for #5612 (MQA-QUEUE-008): closing a dirty Add Series
 * draft silently discarded it, while the Edit Series draft already asked first.
 */

vi.mock('../components/PositionSlider', () => ({ default: () => null }))
vi.mock('../components/DependencyBuilder', () => ({ default: () => null }))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))
vi.mock('../pages/QueuePage/IssueToggleList', () => ({ IssueToggleList: () => null }))

function Harness({ onCloseCreate }: { onCloseCreate: () => void }) {
  const [createForm, setCreateForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [isOpen, setIsOpen] = useState(true)

  return (
    <QueueModals
      openModal={isOpen ? 'create' : null}
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
      onCloseCreate={() => {
        onCloseCreate()
        setIsOpen(false)
      }}
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

describe('Add Series discard confirmation (#5612)', () => {
  it('closes an unchanged draft without prompting', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseCreate={close} />)

    await user.keyboard('{Escape}')

    expect(close).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
  })

  it.each([
    ['Title', 'Watchmen'],
    ['Issues', '1-12'],
    ['Notes', 'borrowed from a friend'],
    ['Issues already read (optional)', '2'],
  ])('asks before discarding a draft with a dirty %s field', async (label, value) => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseCreate={close} />)

    await user.type(screen.getByLabelText(label), value)
    await user.keyboard('{Escape}')

    expect(close).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Discard changes?' })).toBeInTheDocument()
  })

  it('asks before discarding a draft whose only edit is an invalid "Issues already read" entry', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseCreate={close} />)

    await user.type(screen.getByLabelText('Issues already read (optional)'), '-1')
    await user.keyboard('{Escape}')

    expect(close).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Discard changes?' })).toBeInTheDocument()
  })

  it('asks before discarding a draft whose only edit is a creator credit', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseCreate={close} />)

    await user.click(screen.getByRole('button', { name: '+ Add Creator' }))
    await user.keyboard('{Escape}')

    expect(close).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Discard changes?' })).toBeInTheDocument()
  })

  it('keeps the draft when the reader chooses to keep editing', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseCreate={close} />)

    await user.type(screen.getByLabelText('Title'), 'Watchmen')
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', { name: 'Keep editing' }))

    expect(close).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Title')).toHaveValue('Watchmen')
  })

  it('closes the Add Series dialog only after the reader confirms the discard', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onCloseCreate={close} />)

    await user.type(screen.getByLabelText('Title'), 'Watchmen')
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', { name: 'Discard changes' }))

    expect(close).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Add Series' })).not.toBeInTheDocument()
  })
})
