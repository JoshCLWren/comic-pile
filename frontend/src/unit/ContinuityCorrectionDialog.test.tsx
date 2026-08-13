import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ContinuityCorrectionDialog, {
  type ContinuityCorrectionDialogProps,
} from '../components/ContinuityCorrectionDialog'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { threadsApi } from '../services/api'
import type { ConnectedThreadInfo } from '../types'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    addMember: vi.fn(),
  },
}))

vi.mock('../services/api', () => ({
  threadsApi: {
    get: vi.fn(),
    list: vi.fn(),
  },
}))

const listGroups = vi.mocked(dependencyGroupsApi.list)
const createGroup = vi.mocked(dependencyGroupsApi.create)
const addMember = vi.mocked(dependencyGroupsApi.addMember)
const getThread = vi.mocked(threadsApi.get)

const existingGroup = {
  id: 7,
  name: 'Mutant Massacre',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [],
}

const connectedThread = (overrides: Partial<ConnectedThreadInfo>): ConnectedThreadInfo => ({
  thread_id: 99,
  title: 'Ultimate Wolverine',
  connection_type: 'blocks & blocked_by',
  dependency_id: 12,
  ...overrides,
})

const baseProps: ContinuityCorrectionDialogProps = {
  isOpen: true,
  threadId: 1,
  issueId: 42,
  issueNumber: '10',
  threadTitle: 'The Ultimates',
  connectedThreads: [] as ConnectedThreadInfo[],
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

const renderDialog = (props: Partial<ContinuityCorrectionDialogProps> = {}) => {
  const merged = { ...baseProps, ...props, onClose: props.onClose ?? vi.fn(), onSuccess: props.onSuccess ?? vi.fn() }
  const user = userEvent.setup()
  render(<ContinuityCorrectionDialog {...merged} />)
  return { user, onClose: merged.onClose, onSuccess: merged.onSuccess }
}

describe('ContinuityCorrectionDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listGroups.mockResolvedValue([existingGroup])
    createGroup.mockResolvedValue({ ...existingGroup, id: 8, name: 'Inferno' })
    addMember.mockResolvedValue({ id: 1, thread_id: null, issue_id: 42 })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('does not render when closed', () => {
    render(<ContinuityCorrectionDialog {...baseProps} isOpen={false} />)
    expect(screen.queryByTestId('continuity-correction-dialog')).not.toBeInTheDocument()
  })

  it('loads existing crossover groups when opened', async () => {
    renderDialog()
    await waitFor(() => expect(listGroups).toHaveBeenCalledTimes(1))
  })

  it('requires selecting an existing crossover before saving', async () => {
    const { user, onSuccess, onClose } = renderDialog()

    await waitFor(() => expect(listGroups).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: 'Existing' }))
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    expect(screen.getByText(/select an existing crossover/i)).toBeInTheDocument()
    expect(createGroup).not.toHaveBeenCalled()
    expect(addMember).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('creates a new crossover and adds the current issue to it', async () => {
    const { user, onSuccess, onClose } = renderDialog({ onSuccess: vi.fn(), onClose: vi.fn() })

    await waitFor(() => expect(listGroups).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: 'Create New' }))
    await user.type(screen.getByPlaceholderText(/ultimate universe/i), 'Inferno')

    const saveButton = screen.getByRole('button', { name: 'Save Changes' })
    expect(saveButton).toBeEnabled()
    await user.click(saveButton)

    await waitFor(() => expect(createGroup).toHaveBeenCalledWith('Inferno'))
    await waitFor(() => expect(addMember).toHaveBeenCalledWith(8, { issue_id: 42 }))
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
    expect(await screen.findByText(/added to inferno/i)).toBeInTheDocument()
  })

  it('rejects an empty crossover name when creating new', async () => {
    const { user } = renderDialog()
    await waitFor(() => expect(listGroups).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'Create New' }))
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(screen.getByText(/enter a crossover name/i)).toBeInTheDocument()
    expect(createGroup).not.toHaveBeenCalled()
  })

  it('adds the current issue to an existing crossover', async () => {
    const { user } = renderDialog()
    await waitFor(() => expect(listGroups).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: 'Existing' }))
    await user.selectOptions(screen.getByRole('combobox', { name: /existing crossover/i }), '7')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(addMember).toHaveBeenCalledWith(7, { issue_id: 42 }))
    expect(createGroup).not.toHaveBeenCalled()
  })

  it('rejects existing selection when no group is chosen', async () => {
    const { user } = renderDialog()
    await waitFor(() => expect(listGroups).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'Existing' }))
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(screen.getByText(/select an existing crossover/i)).toBeInTheDocument()
    expect(addMember).not.toHaveBeenCalled()
  })

  it('adds verified connected threads to the chosen crossover', async () => {
    const connected: ConnectedThreadInfo[] = [
      connectedThread({ thread_id: 200, title: 'Ultimate Wolverine' }),
      connectedThread({ thread_id: 201, title: 'Ultimate Comics' }),
    ]
    getThread.mockImplementation(async (id: number) => ({
      id,
      title: connected.find((entry) => entry.thread_id === id)?.title ?? 'Unknown',
      format: 'issue',
      issues_remaining: 1,
      total_issues: 1,
      queue_position: 1,
      status: 'active',
      is_blocked: false,
      blocking_reasons: [],
      created_at: '2026-08-06T00:00:00Z',
    }))

    const { user } = renderDialog({
      connectedThreads: connected,
      issueId: null,
    })

    await waitFor(() => expect(listGroups).toHaveBeenCalled())
    await screen.findByText('Ultimate Wolverine')
    await screen.findByText('Ultimate Comics')

    await user.click(screen.getByRole('button', { name: 'Existing' }))
    await user.selectOptions(screen.getByRole('combobox', { name: /existing crossover/i }), '7')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(addMember).toHaveBeenCalledWith(7, { thread_id: 200 }))
    await waitFor(() => expect(addMember).toHaveBeenCalledWith(7, { thread_id: 201 }))
  })

  it('falls back to known title when thread lookup fails', async () => {
    const connected: ConnectedThreadInfo[] = [
      connectedThread({ thread_id: 404, title: 'Fallback Title' }),
    ]
    getThread.mockRejectedValue(new Error('lookup failed'))

    renderDialog({ connectedThreads: connected, issueId: null })

    await waitFor(() => expect(listGroups).toHaveBeenCalled())
    expect(await screen.findByText('Fallback Title')).toBeInTheDocument()
  })

  it('reports a save failure without crashing', async () => {
    addMember.mockRejectedValueOnce(new Error('membership refused'))

    const { user } = renderDialog()
    await waitFor(() => expect(listGroups).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: 'Existing' }))
    await user.selectOptions(screen.getByRole('combobox', { name: /existing crossover/i }), '7')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    expect(await screen.findByText(/membership refused/i)).toBeInTheDocument()
  })

  it('reports a load failure', async () => {
    listGroups.mockRejectedValueOnce(new Error('groups unavailable'))
    renderDialog()
    expect(await screen.findByText(/groups unavailable/i)).toBeInTheDocument()
  })

  it('disables saving when nothing is available to add', async () => {
    const user = userEvent.setup()
    renderDialog({ issueId: null, connectedThreads: [] })
    await waitFor(() => expect(listGroups).toHaveBeenCalled())

    const createButton = screen.getByRole('button', { name: 'Create New' })
    expect(createButton).toBeEnabled()
    await user.click(createButton)
    await user.type(screen.getByPlaceholderText(/ultimate universe/i), 'Solo')

    const saveButton = screen.getByRole('button', { name: 'Save Changes' })
    expect(saveButton).toBeDisabled()
  })

  it('rejects an issue with a null id even when mode is selected', async () => {
    const user = userEvent.setup()
    renderDialog({ issueId: null, connectedThreads: [] })
    await waitFor(() => expect(listGroups).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'Existing' }))
    const saveButton = screen.getByRole('button', { name: 'Save Changes' })
    expect(saveButton).toBeDisabled()
  })

  it('closes the dialog when cancel is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderDialog({ onClose })
    await waitFor(() => expect(listGroups).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('reports the saved groups error when create succeeds but add fails', async () => {
    addMember.mockRejectedValueOnce(new Error('add failed'))
    createGroup.mockResolvedValueOnce({ ...existingGroup, id: 99, name: 'Newly Made' })
    const user = userEvent.setup()
    renderDialog()

    await waitFor(() => expect(listGroups).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'Create New' }))
    await user.type(screen.getByPlaceholderText(/ultimate universe/i), 'Newly Made')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    expect(await screen.findByText(/created newly made, but membership failed/i)).toBeInTheDocument()
  })
})
