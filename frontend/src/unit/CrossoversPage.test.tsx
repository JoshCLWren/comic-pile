import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import { dependencyGroupsApi } from '../services/api-dependency-groups'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    delete: vi.fn(),
  },
}))

const api = vi.mocked(dependencyGroupsApi)

const annihilation = {
  id: 7,
  name: 'Annihilation',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [
    { id: 1, issue_id: 11, thread_id: null },
    { id: 2, issue_id: null, thread_id: 22 },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue([])
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

describe('CrossoversPage', () => {
  it('shows loading and then the empty state', async () => {
    let resolveList: ((groups: []) => void) | undefined
    api.list.mockImplementation(() => new Promise((resolve) => { resolveList = resolve }))

    render(<CrossoversPage />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading crossovers')

    resolveList?.([])
    expect(await screen.findByText('No crossovers yet')).toBeInTheDocument()
  })

  it('blocks creation until the current list request settles', async () => {
    let resolveList: ((groups: []) => void) | undefined
    api.list.mockImplementation(() => new Promise((resolve) => { resolveList = resolve }))
    api.create.mockResolvedValue(annihilation)

    render(<CrossoversPage />)
    const nameInput = screen.getByLabelText('New crossover')
    const createButton = screen.getByRole('button', { name: 'Create crossover' })
    expect(nameInput).toBeDisabled()
    expect(createButton).toBeDisabled()

    resolveList?.([])
    await screen.findByText('No crossovers yet')
    expect(nameInput).toBeEnabled()
    expect(createButton).toBeEnabled()

    fireEvent.change(nameInput, { target: { value: 'Annihilation' } })
    fireEvent.click(createButton)
    expect(await screen.findByText('Annihilation')).toBeInTheDocument()
    expect(api.create).toHaveBeenCalledWith('Annihilation')
  })

  it('creates a trimmed crossover and displays it', async () => {
    api.create.mockResolvedValue(annihilation)
    render(<CrossoversPage />)
    await screen.findByText('No crossovers yet')

    fireEvent.change(screen.getByLabelText('New crossover'), { target: { value: '  Annihilation  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))

    expect(await screen.findByText('Annihilation')).toBeInTheDocument()
    expect(api.create).toHaveBeenCalledWith('Annihilation')
    expect(screen.getByText('2 members')).toBeInTheDocument()
  })

  it('renames and deletes an existing crossover', async () => {
    api.list.mockResolvedValue([annihilation])
    api.rename.mockResolvedValue({ ...annihilation, name: 'Annihilation Conquest' })
    api.delete.mockResolvedValue()
    render(<CrossoversPage />)

    await screen.findByText('Annihilation')
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    fireEvent.change(screen.getByLabelText('Rename Annihilation'), { target: { value: 'Annihilation Conquest' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Annihilation Conquest')).toBeInTheDocument()
    expect(api.rename).toHaveBeenCalledWith(7, 'Annihilation Conquest')

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(screen.queryByText('Annihilation Conquest')).not.toBeInTheDocument())
    expect(window.confirm).toHaveBeenCalled()
    expect(api.delete).toHaveBeenCalledWith(7)
  })

  it('blocks competing mutations while a rename is pending', async () => {
    const secretWars = { ...annihilation, id: 8, name: 'Secret Wars' }
    let resolveRename: ((group: typeof annihilation) => void) | undefined
    api.list.mockResolvedValue([annihilation, secretWars])
    api.rename.mockImplementation(() => new Promise((resolve) => { resolveRename = resolve }))
    render(<CrossoversPage />)

    await screen.findByText('Annihilation')
    const renameButtons = screen.getAllByRole('button', { name: 'Rename' })
    fireEvent.click(renameButtons[0])
    fireEvent.change(screen.getByLabelText('Rename Annihilation'), { target: { value: 'Annihilation Conquest' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(screen.getByRole('button', { name: 'Rename' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    expect(screen.queryByLabelText('Rename Secret Wars')).not.toBeInTheDocument()

    resolveRename?.({ ...annihilation, name: 'Annihilation Conquest' })
    expect(await screen.findByText('Annihilation Conquest')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Rename' })[1]).toBeEnabled()
  })

  it('opens crossover detail with member count', async () => {
    api.list.mockResolvedValue([annihilation])
    render(<CrossoversPage />)

    const groupButton = await screen.findByRole('button', { name: /Annihilation.*2 members/ })
    fireEvent.click(groupButton)

    expect(groupButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Issue 11')).toBeInTheDocument()
    expect(screen.getByText('Thread 22')).toBeInTheDocument()
  })

  it('shows singular and empty membership states and collapses details', async () => {
    api.list.mockResolvedValue([
      { ...annihilation, id: 8, name: 'Secret Wars', memberships: [{ id: 3, issue_id: 12, thread_id: null }] },
      { ...annihilation, id: 9, name: 'House of M', memberships: [] },
    ])
    render(<CrossoversPage />)

    const secretWars = await screen.findByRole('button', { name: /Secret Wars.*1 member/ })
    fireEvent.click(secretWars)
    expect(screen.getByText('Issue 12')).toBeInTheDocument()
    fireEvent.click(secretWars)
    expect(screen.queryByText('Issue 12')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /House of M.*0 members/ }))
    expect(screen.getByText('This crossover has no comics yet.')).toBeInTheDocument()
  })

  it('validates rename, cancels editing, and reports rename failures', async () => {
    api.list.mockResolvedValue([annihilation])
    api.rename.mockRejectedValue(new Error('Rename unavailable'))
    render(<CrossoversPage />)

    await screen.findByText('Annihilation')
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    fireEvent.change(screen.getByLabelText('Rename Annihilation'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a crossover name.')
    expect(api.rename).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('Rename Annihilation'), { target: { value: 'Annihilation Wave' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Rename unavailable')

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByLabelText('Rename Annihilation')).not.toBeInTheDocument()
  })

  it('keeps a crossover when deletion is cancelled and reports delete failures', async () => {
    api.list.mockResolvedValue([annihilation])
    vi.mocked(window.confirm).mockReturnValueOnce(false).mockReturnValueOnce(true)
    api.delete.mockRejectedValue(new Error('Delete unavailable'))
    render(<CrossoversPage />)

    await screen.findByText('Annihilation')
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(api.delete).not.toHaveBeenCalled()
    expect(screen.getByText('Annihilation')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Delete unavailable')
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
  })

  it('presents validation and server failures clearly', async () => {
    api.create.mockRejectedValue(new Error('Duplicate crossover name'))
    render(<CrossoversPage />)
    await screen.findByText('No crossovers yet')

    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a crossover name.')

    fireEvent.change(screen.getByLabelText('New crossover'), { target: { value: 'Annihilation' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Duplicate crossover name')
  })

  it('uses API detail messages and safe fallbacks for non-Error failures', async () => {
    api.list
      .mockRejectedValueOnce({ isAxiosError: true, response: { data: { detail: 'Crossover service unavailable' } } })
      .mockRejectedValueOnce({ isAxiosError: true, response: { data: { detail: '   ' } } })
      .mockRejectedValueOnce('offline')

    render(<CrossoversPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Crossover service unavailable')

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load crossovers.')

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load crossovers.')
  })

  it('allows a failed initial load to be retried', async () => {
    api.list.mockRejectedValueOnce(new Error('Network unavailable')).mockResolvedValueOnce([annihilation])
    render(<CrossoversPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Annihilation')).toBeInTheDocument()
    expect(api.list).toHaveBeenCalledTimes(2)
  })
})