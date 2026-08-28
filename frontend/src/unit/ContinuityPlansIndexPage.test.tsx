import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ContinuityPlansIndexPage from '../pages/ContinuityPlansIndexPage'
import { continuityPlansApi } from '../services/api-continuity-plans'

vi.mock('../services/api-continuity-plans', () => ({
  continuityPlansApi: {
    list: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockList = continuityPlansApi.list as unknown as ReturnType<typeof vi.fn>
const mockDelete = continuityPlansApi.delete as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ContinuityPlansIndexPage', () => {
  it('renders loading state initially', () => {
    mockList.mockReturnValue(new Promise(() => {}))
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    expect(screen.getByRole('status')).toHaveTextContent('Loading plans')
  })

  it('renders empty state when no plans exist', async () => {
    mockList.mockResolvedValue([])
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('No reading plans yet')).toBeInTheDocument()
    })
    expect(screen.getByText('Create your first plan from the sequential planner.')).toBeInTheDocument()
  })

  it('renders error state when load fails', async () => {
    mockList.mockRejectedValue(new Error('Network error'))
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Network error')
    })
  })

  it('renders plan cards when plans exist', async () => {
    mockList.mockResolvedValue([
      {
        id: 1,
        name: 'My Plan',
        ordering_mode: 'informational',
        lane_count: 2,
        step_count: 5,
        updated_at: '2026-08-28T00:00:00Z',
      },
    ])
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('My Plan')).toBeInTheDocument()
    })
    expect(screen.getByText('2 lanes · 5 steps')).toBeInTheDocument()
  })

  it('shows delete confirmation when delete is clicked', async () => {
    mockList.mockResolvedValue([
      {
        id: 1,
        name: 'My Plan',
        ordering_mode: 'informational',
        lane_count: 1,
        step_count: 3,
        updated_at: '2026-08-28T00:00:00Z',
      },
    ])
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('My Plan')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))
    expect(screen.getByText('Delete this plan? Associated rules will also be removed.')).toBeInTheDocument()
    expect(screen.getByText('Keep')).toBeInTheDocument()
  })

  it('cancels delete when keep is clicked', async () => {
    mockList.mockResolvedValue([
      {
        id: 1,
        name: 'My Plan',
        ordering_mode: 'informational',
        lane_count: 1,
        step_count: 3,
        updated_at: '2026-08-28T00:00:00Z',
      },
    ])
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('My Plan')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))
    await userEvent.click(screen.getByText('Keep'))
    expect(screen.queryByText('Delete this plan?')).not.toBeInTheDocument()
  })

  it('deletes plan when confirm is clicked', async () => {
    mockList.mockResolvedValue([
      {
        id: 1,
        name: 'My Plan',
        ordering_mode: 'informational',
        lane_count: 1,
        step_count: 3,
        updated_at: '2026-08-28T00:00:00Z',
      },
    ])
    mockDelete.mockResolvedValue(undefined)
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('My Plan')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))
    await userEvent.click(screen.getByText('Delete', { selector: 'button:last-child' }))
    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith(1)
    })
  })

  it('shows error when delete fails', async () => {
    mockList.mockResolvedValue([
      {
        id: 1,
        name: 'My Plan',
        ordering_mode: 'informational',
        lane_count: 1,
        step_count: 3,
        updated_at: '2026-08-28T00:00:00Z',
      },
    ])
    mockDelete.mockRejectedValue(new Error('Delete failed'))
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('My Plan')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('Delete'))
    await userEvent.click(screen.getByText('Delete', { selector: 'button:last-child' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Delete failed')
    })
  })
})
