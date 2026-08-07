import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import { dependencyGroupsApi } from '../services/api-dependency-groups'

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
  },
}))

const api = vi.mocked(dependencyGroupsApi)

const crossover = {
  id: 7,
  name: 'Annihilation',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [
    { id: 1, issue_id: 31, thread_id: null },
    { id: 2, issue_id: null, thread_id: 22 },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue([crossover])
})

describe('CrossoversPage membership editing', () => {
  it('shows individual issue and thread memberships', async () => {
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    expect(screen.getByText('Issue 31')).toBeInTheDocument()
    expect(screen.getByText('Thread 22')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Annihilation members' })).toBeInTheDocument()
  })

  it('adds a whole thread membership and updates the visible group', async () => {
    api.addMember.mockResolvedValue({ id: 3, issue_id: null, thread_id: 44 })
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.change(screen.getByLabelText('Whole thread ID'), { target: { value: '44' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))

    expect(await screen.findByText('Thread 44')).toBeInTheDocument()
    expect(api.addMember).toHaveBeenCalledWith(7, { thread_id: 44 })
    expect(screen.getByRole('status')).toHaveTextContent('Thread added to crossover.')
    expect(screen.getByLabelText('Whole thread ID')).toHaveValue('')
  })

  it('rejects an invalid whole-thread ID before calling the API', async () => {
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.change(screen.getByLabelText('Whole thread ID'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Enter a valid thread ID.')
    expect(api.addMember).not.toHaveBeenCalled()
  })

  it('removes a membership without changing the crossover itself', async () => {
    api.removeMember.mockResolvedValue(undefined)
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Remove issue 31 from Annihilation' }))

    await waitFor(() => expect(screen.queryByText('Issue 31')).not.toBeInTheDocument())
    expect(api.removeMember).toHaveBeenCalledWith(7, 1)
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Comic removed from crossover.')
  })

  it('keeps membership visible when removal fails', async () => {
    api.removeMember.mockRejectedValue(new Error('Removal unavailable'))
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Remove issue 31 from Annihilation' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Removal unavailable')
    expect(screen.getByText('Issue 31')).toBeInTheDocument()
  })
})
