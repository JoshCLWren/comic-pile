import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { existingList } from './fixtures/customCblFixture'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
  searchIssues: vi.fn(),
  apply: vi.fn(),
  exportXml: vi.fn(),
}))

vi.mock('../services/api-custom-cbl', async () => {
  const actual = await vi.importActual<typeof import('../services/api-custom-cbl')>(
    '../services/api-custom-cbl',
  )
  return { ...actual, customCBLApi: mocks }
})

const cblMocks = vi.hoisted(() => ({ discover: vi.fn(), preview: vi.fn() }))

vi.mock('../services/api-cbl-sources', async () => {
  const actual = await vi.importActual<typeof import('../services/api-cbl-sources')>(
    '../services/api-cbl-sources',
  )
  return { ...actual, cblSourcesApi: cblMocks }
})

function renderBuilder() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, gcTime: 5 * 60_000, refetchOnWindowFocus: false, retry: false },
      mutations: { retry: false },
    },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CustomCBLBuilder planId={18} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Two Starman issues plus one All-Star issue so mixed series state is observable. */
const threeIssueList = {
  ...existingList,
  issue_count: 3,
  entries: [
    { ...existingList.entries[0]!, id: 91, position: 0, issue_id: 26360, issue_number: '55' },
    { ...existingList.entries[0]!, id: 93, position: 1, issue_id: 26361, issue_number: '56' },
    { ...existingList.entries[1]!, id: 92, position: 2 },
  ],
}

describe('saved-list editor series skip controls', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mocks.list.mockResolvedValue([
      {
        id: 9,
        name: existingList.name,
        description: existingList.description,
        mode: existingList.mode,
        issue_count: 3,
        updated_at: existingList.updated_at,
      },
    ])
    mocks.get.mockResolvedValue(threeIssueList)
    mocks.update.mockResolvedValue(threeIssueList)
    cblMocks.discover.mockResolvedValue([])
    cblMocks.preview.mockResolvedValue(null)
  })

  it('shows one tri-state control per series and saves whole-series skip intents', async () => {
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Starman #56')

    const starmanSeries = screen.getByLabelText('Skip Starman series in this list')
    expect(starmanSeries).not.toBeChecked()
    expect(screen.getByText('0 of 2 skipped in this list')).toBeInTheDocument()
    // Every volume gets a control, including a one-issue series.
    expect(screen.getByLabelText('Skip All-Star Comics series in this list')).not.toBeChecked()
    expect(screen.getByText('0 of 1 skipped in this list')).toBeInTheDocument()

    // Skipping one issue leaves the series control mixed, like the creation flow.
    fireEvent.click(screen.getByLabelText('Skip Starman #56 in this list'))
    expect(starmanSeries).toHaveProperty('indeterminate', true)
    expect(screen.getByText('1 of 2 skipped in this list')).toBeInTheDocument()

    // Clicking the mixed series control skips the rest of that volume only.
    fireEvent.click(starmanSeries)
    expect(screen.getByLabelText('Skip Starman #55 in this list')).toBeChecked()
    expect(screen.getByLabelText('Skip Starman #56 in this list')).toBeChecked()
    expect(starmanSeries).toBeChecked()
    expect(starmanSeries).toHaveProperty('indeterminate', false)
    expect(screen.getByText('2 of 2 skipped in this list')).toBeInTheDocument()
    expect(screen.getByLabelText('Skip All-Star Comics series in this list')).not.toBeChecked()

    // Clearing the series control restores every issue in that volume.
    fireEvent.click(starmanSeries)
    expect(screen.getByLabelText('Skip Starman #55 in this list')).not.toBeChecked()
    expect(screen.getByLabelText('Skip Starman #56 in this list')).not.toBeChecked()
    expect(screen.getByText('0 of 2 skipped in this list')).toBeInTheDocument()

    // Skip the volume again and save: the existing per-issue intents carry it.
    fireEvent.click(starmanSeries)
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 26361, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: true },
          26361: { gate: 'none', skipped: true },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      })
    })
  })
})
