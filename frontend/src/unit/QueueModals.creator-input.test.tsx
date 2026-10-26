import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { PotentialDuplicateMatch } from '../types'
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

function Harness({ openModal = 'create', matches = [], checking = false }: {
  openModal?: 'create' | 'edit'; matches?: PotentialDuplicateMatch[]; checking?: boolean
} = {}) {
  const [createForm, setCreateForm] = useState<QueueFormState>({ ...DEFAULT_CREATE_STATE, title: 'Proposed series' })
  const [editForm, setEditForm] = useState<QueueFormState>({ ...DEFAULT_CREATE_STATE, title: 'Proposed series' })

  return (
    <QueueModals
      openModal={openModal}
      createPotentialDuplicates={matches}
      editPotentialDuplicates={matches}
      isCheckingDuplicates={checking}
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


describe('advisory duplicate warnings', () => {
  it.each(['create', 'edit'] as const)('shows both strong and weak matches in %s without merging', (openModal) => {
    const common = { format: 'Comic', issues_remaining: 3, total_issues: 5, status: 'active', comicvine_volume_id: null }
    render(<Harness openModal={openModal} matches={[
      { ...common, thread_id: 7, title: 'Verified volume', match_type: 'strong', comicvine_volume_id: 42 },
      { ...common, thread_id: 8, title: 'Possible edition', match_type: 'weak', total_issues: null },
    ]} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Same ComicVine volume already in your library')
    expect(screen.getByText('Verified volume')).toBeVisible()
    expect(screen.getByText('Possible edition')).toBeVisible()
    expect(screen.getByText('Same ComicVine Volume')).toBeVisible()
    expect(screen.getByText('Similar Title/Format')).toBeVisible()
  })
  it.each(['create', 'edit'] as const)('reports loading separately in the active %s form', (openModal) => {
    render(<Harness openModal={openModal} checking />)
    expect(screen.getByRole('alert')).toHaveTextContent('Checking for potential duplicates...')
    expect(screen.queryByText('Similar series found in your library')).not.toBeInTheDocument()
  })
  it.each(['create', 'edit'] as const)('keeps weak matches advisory in the %s form', (openModal) => {
    render(<Harness openModal={openModal} matches={[{ thread_id: 8, title: 'Other edition', format: 'Comic', issues_remaining: 1, total_issues: null, status: 'completed', match_type: 'weak', comicvine_volume_id: null }]} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Similar series found in your library')
    expect(screen.getByText('Other edition')).toBeVisible()
  })
})
