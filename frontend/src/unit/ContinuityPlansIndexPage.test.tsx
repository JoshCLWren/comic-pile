import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ContinuityPlansIndexPage from '../pages/ContinuityPlansIndexPage'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { cast } from '../utils/cast'

vi.mock('../services/api-continuity-plans', () => ({
  continuityPlansApi: {
    list: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockList = cast<ReturnType<typeof vi.fn>>(continuityPlansApi.list)
const mockDelete = cast<ReturnType<typeof vi.fn>>(continuityPlansApi.delete)
const plan = {
  id: 1,
  name: 'My Plan',
  ordering_mode: 'informational',
  lane_count: 1,
  step_count: 3,
  source_paths: [] as string[],
  updated_at: '2026-08-28T00:00:00Z',
}

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
    expect(screen.getByText(/saved arrangement of issues, series, and crossovers/)).toBeInTheDocument()
    const glossaryLink = screen.getByRole('link', { name: 'What is a continuity plan?' })
    expect(glossaryLink).toHaveAttribute('href', '/glossary#continuity-plan')
    expect(screen.getByRole('button', { name: 'New Reading Plan' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add from CBL' })).toBeInTheDocument()
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
      { ...plan, lane_count: 2, step_count: 5 },
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
    expect(screen.getByRole('button', { name: 'New Reading Plan' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add from CBL' })).toBeInTheDocument()
  })

  it('identifies CBL-backed plans and their source', async () => {
    mockList.mockResolvedValue([
      { ...plan, source_paths: ['Dark Horse/BPRD/Plague of Frogs.cbl'] },
    ])
    render(
      <MemoryRouter>
        <ContinuityPlansIndexPage />
      </MemoryRouter>
    )
    expect(await screen.findByText('CBL-backed')).toBeInTheDocument()
    expect(screen.getByText('Source: Dark Horse/BPRD/Plague of Frogs.cbl')).toBeInTheDocument()
  })

  it('shows delete confirmation when delete is clicked', async () => {
    mockList.mockResolvedValue([
      plan,
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
      plan,
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
      plan,
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
      expect(mockDelete).toHaveBeenCalledWith(1, expect.anything())
    })
  })

  it('shows error when delete fails', async () => {
    mockList.mockResolvedValue([
      plan,
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
