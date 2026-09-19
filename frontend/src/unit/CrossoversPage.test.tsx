import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { threadsApi } from '../services/api'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    delete: vi.fn(),
    addMember: vi.fn(),
    addIssueRange: vi.fn(),
    removeMember: vi.fn(),
    listForThread: vi.fn(),
    listForThreads: vi.fn(),
    plansForGroup: vi.fn(),
    getDetail: vi.fn(),
  },
}))

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  threadsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    reactivate: vi.fn(),
    listStale: vi.fn(),
    setPending: vi.fn(),
    setCurrentIssue: vi.fn(),
    listCompleted: vi.fn(),
  },
  issuesApi: {
    list: vi.fn(),
  },
}))

const groupsApi = vi.mocked(dependencyGroupsApi)
const mockedThreadsApi = vi.mocked(threadsApi)

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <CrossoversPage />
    </MemoryRouter>,
    { wrapper: createWrapper() },
  )
}

const annihilation = {
  id: 7,
  name: 'Annihilation',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [
    { id: 1, issue_id: 11, thread_id: null, series_title: 'Nova', issue_number: '4' },
    { id: 2, issue_id: null, thread_id: 22, series_title: 'Nova', issue_number: null },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  groupsApi.list.mockResolvedValue([])
  groupsApi.get.mockResolvedValue({ id: 7, name: 'Annihilation', created_at: '2026-08-06T00:00:00Z', memberships: [] })
  groupsApi.addMember.mockResolvedValue({ id: 99, thread_id: null, issue_id: null })
  groupsApi.addIssueRange.mockResolvedValue({ thread_id: 1, start_position: 1, end_position: 5, added_issue_ids: [], already_present_issue_ids: [] })
  mockedThreadsApi.list.mockResolvedValue({ threads: [], next_page_token: null })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

describe('CrossoversPage', () => {
  it('shows loading and then the empty state', async () => {
    let resolveList: ((groups: []) => void) | undefined
    groupsApi.list.mockImplementation(() => new Promise((resolve) => { resolveList = resolve }))

    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent('Loading crossovers')

    resolveList?.([])
    expect(await screen.findByText(/No crossovers yet/)).toBeInTheDocument()
  })

  it('blocks creation until the current list request settles', async () => {
    let resolveList: ((groups: []) => void) | undefined
    groupsApi.list.mockImplementation(() => new Promise((resolve) => { resolveList = resolve }))
    groupsApi.create.mockResolvedValue(annihilation)

    renderPage()
    const nameInput = screen.getByLabelText('New crossover')
    const createButton = screen.getByRole('button', { name: 'Create crossover' })
    expect(nameInput).toBeDisabled()
    expect(createButton).toBeDisabled()

    resolveList?.([])
    await screen.findByText(/No crossovers yet/)
    expect(nameInput).toBeEnabled()
    expect(createButton).toBeEnabled()

    fireEvent.change(nameInput, { target: { value: 'Annihilation' } })
    groupsApi.list.mockResolvedValue([annihilation])
    fireEvent.click(createButton)
    expect(await screen.findByText('Annihilation')).toBeInTheDocument()
    expect(groupsApi.create).toHaveBeenCalledWith('Annihilation')
  })

  it('creates a trimmed crossover and displays it', async () => {
    groupsApi.create.mockResolvedValue(annihilation)
    renderPage()
    await screen.findByText(/No crossovers yet/)

    fireEvent.change(screen.getByLabelText('New crossover'), { target: { value: '  Annihilation  ' } })
    groupsApi.list.mockResolvedValue([annihilation])
    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))

    expect(await screen.findByText('Annihilation')).toBeInTheDocument()
    expect(groupsApi.create).toHaveBeenCalledWith('Annihilation')
    expect(screen.getByText('2 members')).toBeInTheDocument()
  })

  it('renames and deletes an existing crossover', async () => {
    groupsApi.list.mockResolvedValue([annihilation])
    groupsApi.rename.mockResolvedValue({ ...annihilation, name: 'Annihilation Conquest' })
    groupsApi.delete.mockResolvedValue(undefined)

    renderPage()

    await screen.findByText('Annihilation')
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    fireEvent.change(screen.getByLabelText('Rename Annihilation'), { target: { value: 'Annihilation Conquest' } })
    groupsApi.list.mockResolvedValue([{ ...annihilation, name: 'Annihilation Conquest' }])
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Annihilation Conquest')).toBeInTheDocument()
    expect(groupsApi.rename).toHaveBeenCalledWith(7, 'Annihilation Conquest')

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    groupsApi.list.mockResolvedValue([])
    await waitFor(() => expect(screen.queryByText('Annihilation Conquest')).not.toBeInTheDocument())
    expect(window.confirm).toHaveBeenCalled()
    expect(groupsApi.delete).toHaveBeenCalledWith(7)
  })

  it('blocks competing mutations while a rename is pending', async () => {
    const secretWars = { ...annihilation, id: 8, name: 'Secret Wars' }
    let resolveRename: ((group: typeof annihilation) => void) | undefined
    groupsApi.list.mockResolvedValue([annihilation, secretWars])
    groupsApi.rename.mockImplementation(() => new Promise((resolve) => { resolveRename = resolve }))
    renderPage()

    await screen.findByText('Annihilation')
    await screen.findByText('Secret Wars')

    fireEvent.click(screen.getAllByRole('button', { name: 'Rename' })[0])
    fireEvent.change(screen.getByLabelText('Rename Annihilation'), { target: { value: 'Annihilation Conquest' } })
    groupsApi.list.mockResolvedValue([{ ...annihilation, name: 'Annihilation Conquest' }, secretWars])
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.getAllByRole('button', { name: 'Rename' })[0]).toBeDisabled()

    await waitFor(() => expect(groupsApi.rename).toHaveBeenCalledTimes(1))
    resolveRename?.({ ...annihilation, name: 'Annihilation Conquest' })
    expect(await screen.findByText('Annihilation Conquest')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Rename' })[1]).toBeEnabled())
  })

  it('opens crossover detail with member count', async () => {
    groupsApi.list.mockResolvedValue([annihilation])
    renderPage()

    const groupButton = await screen.findByRole('button', { name: /Annihilation.*2 members/ })
    fireEvent.click(groupButton)

    expect(groupButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Nova #4')).toBeInTheDocument()
    expect(screen.getByText('Nova (whole series)')).toBeInTheDocument()
  })

  it('shows singular and empty membership states and collapses details', async () => {
    groupsApi.list.mockResolvedValue([
      { ...annihilation, id: 8, name: 'Secret Wars', memberships: [{ id: 3, issue_id: 12, thread_id: null, series_title: 'Mighty Avengers', issue_number: '12' }] },
      { ...annihilation, id: 9, name: 'House of M', memberships: [] },
    ])
    renderPage()

    const secretWars = await screen.findByRole('button', { name: /Secret Wars.*1 member/ })
    fireEvent.click(secretWars)
    expect(screen.getByText('Mighty Avengers #12')).toBeInTheDocument()
    fireEvent.click(secretWars)
    expect(screen.queryByText('Mighty Avengers #12')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /House of M.*0 members/ }))
    expect(screen.getByText('This crossover has no comics yet.')).toBeInTheDocument()
  })

  it('validates rename, cancels editing, and reports rename failures', async () => {
    groupsApi.list.mockResolvedValue([annihilation])
    groupsApi.rename.mockRejectedValue(new Error('Rename unavailable'))
    renderPage()

    await screen.findByText('Annihilation')
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    fireEvent.change(screen.getByLabelText('Rename Annihilation'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a crossover name.')
    expect(groupsApi.rename).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('Rename Annihilation'), { target: { value: 'Annihilation Wave' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Rename unavailable')

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByLabelText('Rename Annihilation')).not.toBeInTheDocument()
  })

  it('keeps a crossover when deletion is cancelled and reports delete failures', async () => {
    groupsApi.list.mockResolvedValue([annihilation])
    vi.mocked(window.confirm).mockReturnValueOnce(false).mockReturnValueOnce(true)
    groupsApi.delete.mockRejectedValue(new Error('Delete unavailable'))
    renderPage()

    await screen.findByText('Annihilation')
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(groupsApi.delete).not.toHaveBeenCalled()
    expect(screen.getByText('Annihilation')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Delete unavailable')
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
  })

  it('presents validation and server failures clearly', async () => {
    groupsApi.create.mockRejectedValue(new Error('Duplicate crossover name'))
    renderPage()
    await screen.findByText(/No crossovers yet/)

    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a crossover name.')

    fireEvent.change(screen.getByLabelText('New crossover'), { target: { value: 'Annihilation' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Duplicate crossover name')
  })

  it('uses API detail messages and safe fallbacks for non-Error failures', async () => {
    const axiosFailure = (detail: string) => {
      const error = new Error() as Error & { isAxiosError?: boolean; response?: { data: { detail: string } } }
      error.isAxiosError = true
      error.response = { data: { detail } }
      return error
    }
    groupsApi.list
      .mockRejectedValueOnce(axiosFailure('Crossover service unavailable'))
      .mockRejectedValueOnce(axiosFailure('   '))
      .mockRejectedValueOnce('offline')

    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('Crossover service unavailable')

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Unable to load crossovers.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Unable to load crossovers.')).toBeInTheDocument()
  })

  it('allows a failed initial load to be retried', async () => {
    groupsApi.list.mockRejectedValueOnce(new Error('Network unavailable')).mockResolvedValueOnce([annihilation])
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Annihilation')).toBeInTheDocument()
    expect(groupsApi.list).toHaveBeenCalledTimes(2)
  })
})
