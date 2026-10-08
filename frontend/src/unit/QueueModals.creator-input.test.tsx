import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import {
  DEFAULT_CREATE_STATE,
  type QueueFormState,
} from '../pages/QueuePage/types'

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

import type { ParsedTokenBreakdown } from '../../utils/issueParser'

function Harness() {
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
      issueParseBreakdown={[] as ParsedTokenBreakdown[]}
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

describe('QueueModals manual creator editor', () => {
  it('adds, edits, normalizes roles, cancels, saves, and removes creator credits', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.click(screen.getByRole('button', { name: '+ Add Creator' }))
    expect(screen.getByText('Unnamed creator')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.type(screen.getByPlaceholderText('Creator name'), 'Alan Moore')
    await user.click(screen.getByRole('button', { name: 'Writer' }))
    await user.click(screen.getByRole('button', { name: 'Writer' }))
    await user.click(screen.getByRole('button', { name: 'Artist' }))

    const customRole = screen.getByPlaceholderText('Custom role...')
    await user.type(customRole, 'Layouts{Enter}')
    expect(customRole).toHaveValue('')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByText('Unnamed creator')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const creatorName = screen.getByPlaceholderText('Creator name')
    await user.type(creatorName, 'Alan Moore')
    await user.click(screen.getByRole('button', { name: 'Writer' }))
    await user.type(creatorName, '{Enter}')

    expect(screen.getByText('Alan Moore')).toBeInTheDocument()
    expect(screen.getByText('Writer')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove' }))
    expect(screen.getByText('No creators added yet.')).toBeInTheDocument()
  })
})
