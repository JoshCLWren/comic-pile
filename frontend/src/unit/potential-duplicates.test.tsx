import { useState } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { DEFAULT_CREATE_STATE, type QueueFormState } from '../pages/QueuePage/types'
import { threadsApi } from '../services/api-threads'
import type { PotentialDuplicateMatch, Thread } from '../types'

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
vi.mock('../services/api-threads', () => ({
  threadsApi: { checkPotentialDuplicates: vi.fn() },
}))

const CHECK = vi.mocked(threadsApi.checkPotentialDuplicates)

const CONFIRMED_MATCH: PotentialDuplicateMatch = {
  thread_id: 42,
  title: 'Spider-Man (2018)',
  format: 'Comic',
  status: 'active',
  issues_remaining: 2,
  total_issues: null,
  comicvine_volume_id: 12345,
  start_year: 2018,
  match_type: 'same_comicvine_volume',
}

const UNCERTAIN_MATCH: PotentialDuplicateMatch = {
  thread_id: 9,
  title: 'Saga',
  format: 'Comic',
  status: 'active',
  issues_remaining: 0,
  total_issues: null,
  comicvine_volume_id: null,
  start_year: null,
  match_type: 'similar_title',
}

const EDITING_THREAD = {
  id: 7,
  title: 'Saga',
  format: 'Comic',
  status: 'active',
  queue_position: 1,
  issues_remaining: 4,
  total_issues: null,
  notes: null,
  created_at: '2026-01-01T00:00:00Z',
  last_activity_at: null,
  last_rating: null,
  is_blocked: false,
  is_test: false,
  blocking_reasons: [],
} as unknown as Thread

function harnessProps(
  overrides: Partial<Parameters<typeof QueueModals>[0]> = {},
): Parameters<typeof QueueModals>[0] {
  return {
    openModal: 'create',
    createForm: DEFAULT_CREATE_STATE,
    editForm: DEFAULT_CREATE_STATE,
    setCreateForm: vi.fn(),
    setEditForm: vi.fn(),
    issuePreview: 1,
    issueParseError: null,
    issueParseWarnings: [],
    issueParseBreakdown: [],
    editingThread: null,
    repositioningThread: null,
    dependencyThread: null,
    threadToMigrate: null,
    showMigrationDialog: false,
    reactivateThreadId: '',
    setReactivateThreadId: vi.fn(),
    issuesToAdd: 1,
    setIssuesToAdd: vi.fn(),
    activeThreads: [],
    completedThreads: [],
    queueSize: 0,
    onCreateSubmit: vi.fn(async (event) => event.preventDefault()),
    onEditSubmit: vi.fn(async (event) => event.preventDefault()),
    onReactivateSubmit: vi.fn(async (event) => event.preventDefault()),
    onRepositionConfirm: vi.fn(),
    onDependencyChanged: vi.fn(async () => undefined),
    onCloseCreate: vi.fn(),
    onCloseEdit: vi.fn(),
    onCloseReactivate: vi.fn(),
    onCloseReposition: vi.fn(),
    onCloseDependency: vi.fn(),
    onMigrationComplete: vi.fn(async () => undefined),
    onMigrationSkip: vi.fn(),
    onCloseMigration: vi.fn(),
    onOpenMigrationDialog: vi.fn(),
    onCloseAddSeriesComicVine: vi.fn(),
    isPendingCreate: false,
    isPendingEdit: false,
    isPendingReactivate: false,
    showRollNudge: false,
    onDismissRollNudge: vi.fn(),
    onRollNudgeNavigate: vi.fn(),
    ...overrides,
  }
}

function CreateHarness({ onSubmit }: { onSubmit: (event: React.FormEvent) => Promise<void> }) {
  const [createForm, setCreateForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  return (
    <QueueModals
      {...harnessProps({
        openModal: 'create',
        createForm,
        setCreateForm,
        editForm,
        setEditForm,
        onCreateSubmit: onSubmit,
      })}
    />
  )
}

function EditHarness() {
  const [createForm, setCreateForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editForm, setEditForm] = useState<QueueFormState>({
    ...DEFAULT_CREATE_STATE,
    title: 'Saga',
    issuesRemaining: 4,
  })
  return (
    <QueueModals
      {...harnessProps({
        openModal: 'edit',
        createForm,
        setCreateForm,
        editForm,
        setEditForm,
        editingThread: EDITING_THREAD,
      })}
    />
  )
}

function renderInRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

beforeEach(() => {
  CHECK.mockReset()
})

describe('Add Series duplicate advisory (#3612)', () => {
  it('identifies an owned confirmed volume, links its thread, and keeps Create available', async () => {
    const user = userEvent.setup()
    CHECK.mockResolvedValue({ matches: [CONFIRMED_MATCH] })
    const onSubmit = vi.fn(async (event: React.FormEvent) => event.preventDefault())
    renderInRouter(<CreateHarness onSubmit={onSubmit} />)

    await user.type(screen.getByLabelText('Title'), 'Spider-Man (2018)')

    const advisory = await screen.findByTestId('potential-duplicate-advisory')
    expect(within(advisory).getByText('Spider-Man (2018)')).toBeInTheDocument()
    expect(within(advisory).getByText('Confirmed volume')).toBeInTheDocument()
    expect(within(advisory).getByText(/ComicVine volume 12345/)).toBeInTheDocument()
    expect(within(advisory).getByText(/started 2018/)).toBeInTheDocument()
    expect(
      within(advisory).getByRole('link', { name: 'Open existing series Spider-Man (2018)' }),
    ).toHaveAttribute('href', '/thread/42')

    await waitFor(() =>
      expect(CHECK).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Spider-Man (2018)', format: 'Comic' }),
      ),
    )

    const create = screen.getByRole('button', { name: 'Create Series' })
    expect(create).toBeEnabled()
    await user.type(screen.getByLabelText('Issues'), '1')
    await user.click(create)
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('labels a title-only match as uncertain instead of asserting identity', async () => {
    const user = userEvent.setup()
    CHECK.mockResolvedValue({ matches: [UNCERTAIN_MATCH] })
    renderInRouter(<CreateHarness onSubmit={vi.fn(async () => undefined)} />)

    await user.type(screen.getByLabelText('Title'), 'Saga')

    const advisory = await screen.findByTestId('potential-duplicate-advisory')
    expect(within(advisory).getByText('Uncertain title match')).toBeInTheDocument()
    expect(within(advisory).queryByText('Confirmed volume')).not.toBeInTheDocument()
    expect(within(advisory).queryByText(/ComicVine volume/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Series' })).toBeEnabled()
  })

  it('dismisses the warning and re-arms it when the candidate title changes', async () => {
    const user = userEvent.setup()
    CHECK.mockResolvedValue({ matches: [UNCERTAIN_MATCH] })
    renderInRouter(<CreateHarness onSubmit={vi.fn(async () => undefined)} />)

    const input = screen.getByLabelText('Title')
    await user.type(input, 'Saga')
    expect(await screen.findByTestId('potential-duplicate-advisory')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Dismiss possible existing series warning' }))
    expect(screen.queryByTestId('potential-duplicate-advisory')).not.toBeInTheDocument()

    await user.type(input, ' 2')
    expect(await screen.findByTestId('potential-duplicate-advisory')).toBeInTheDocument()
    await waitFor(() =>
      expect(CHECK).toHaveBeenLastCalledWith(expect.objectContaining({ title: 'Saga 2' })),
    )
  })

  it('clears the warning when the check no longer reports a match', async () => {
    const user = userEvent.setup()
    CHECK.mockResolvedValueOnce({ matches: [UNCERTAIN_MATCH] })
    CHECK.mockResolvedValue({ matches: [] })
    renderInRouter(<CreateHarness onSubmit={vi.fn(async () => undefined)} />)

    const input = screen.getByLabelText('Title')
    await user.type(input, 'Saga')
    expect(await screen.findByTestId('potential-duplicate-advisory')).toBeInTheDocument()

    await user.type(input, 'x')
    await waitFor(() =>
      expect(screen.queryByTestId('potential-duplicate-advisory')).not.toBeInTheDocument(),
    )
  })

  it('never blocks the form when the advisory lookup fails', async () => {
    const user = userEvent.setup()
    CHECK.mockRejectedValue(new Error('advisory unavailable'))
    renderInRouter(<CreateHarness onSubmit={vi.fn(async () => undefined)} />)

    await user.type(screen.getByLabelText('Title'), 'Saga')

    await waitFor(() => expect(CHECK).toHaveBeenCalled())
    expect(screen.queryByTestId('potential-duplicate-advisory')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Series' })).toBeEnabled()
  })
})

describe('Edit/Rename duplicate advisory (#3612)', () => {
  it('excludes the edited series and links another existing volume', async () => {
    const user = userEvent.setup()
    CHECK.mockResolvedValue({ matches: [UNCERTAIN_MATCH] })
    renderInRouter(<EditHarness />)

    const advisory = await screen.findByTestId('potential-duplicate-advisory')
    expect(within(advisory).getByRole('link', { name: 'Open existing series Saga' })).toHaveAttribute(
      'href',
      '/thread/9',
    )
    expect(CHECK).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Saga', format: 'Comic', exclude_thread_id: 7 }),
    )
    expect(screen.getByRole('button', { name: 'Save Changes' })).toBeEnabled()

    await user.type(screen.getByLabelText('Title'), ' Redux')
    await waitFor(() =>
      expect(CHECK).toHaveBeenLastCalledWith(
        expect.objectContaining({ title: 'Saga Redux', exclude_thread_id: 7 }),
      ),
    )
  })

  it('does not check while the dialog is closed', () => {
    renderInRouter(
      <QueueModals {...harnessProps({ openModal: null, editingThread: EDITING_THREAD })} />,
    )

    expect(CHECK).not.toHaveBeenCalled()
  })
})
