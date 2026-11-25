import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { issueCardsApi } from '../services/issueCardsApi'
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

vi.mock('../services/api-cbl-sources', async () => {
  const actual = await vi.importActual<typeof import('../services/api-cbl-sources')>(
    '../services/api-cbl-sources',
  )
  return {
    ...actual,
    cblSourcesApi: { discover: vi.fn(), preview: vi.fn() },
  }
})

function renderBuilder() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: false,
      },
      mutations: { retry: false },
    },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CustomCBLBuilder planId={18} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

async function openExistingList() {
  fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
  fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
  await screen.findByText('Starman #55')
}

function isAxiosError(status: number, detail: Record<string, unknown>) {
  return { isAxiosError: true, response: { status, data: { detail } } }
}

describe('CustomCBLBuilder issue 4233 new branches', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(issueCardsApi, 'fetchCards').mockResolvedValue([])
    mocks.list.mockResolvedValue([{
      id: 9,
      name: existingList.name,
      description: existingList.description,
      mode: existingList.mode,
      issue_count: existingList.issue_count,
      updated_at: existingList.updated_at,
    }])
    mocks.get.mockResolvedValue(existingList)
    mocks.searchIssues.mockResolvedValue([])
  })

  it('surfaces a stale-write conflict with an actionable refresh affordance', async () => {
    const user = userEvent.setup()
    mocks.update.mockRejectedValueOnce(isAxiosError(409, {
      code: 'reading_list_stale_write',
      message: 'List changed. Refresh to review the latest saved order.',
      updated_at: '2026-11-25T00:00:00Z',
    }))
    renderBuilder()
    await openExistingList()

    await user.click(screen.getByRole('button', { name: 'Show settings for Starman #55' }))
    fireEvent.click(screen.getByLabelText('Skip Starman #55 in this list'))
    await user.click(screen.getByRole('button', { name: 'Save custom CBL' }))

    const staleText = await screen.findByText('List changed. Refresh to review the latest saved order.')
    expect(staleText.closest('[role="alert"]')).toHaveTextContent('Refresh latest list')

    mocks.get.mockResolvedValueOnce(existingList)
    await user.click(screen.getByRole('button', { name: 'Refresh latest list' }))
    await waitFor(() => {
      expect(mocks.get).toHaveBeenCalledWith(9)
      expect(screen.getByText('Starman #55')).toBeInTheDocument()
    })
  })

  it('previews the semantic position change and first-unread context before saving', async () => {
    const user = userEvent.setup()
    mocks.update.mockResolvedValue(existingList)
    renderBuilder()
    await openExistingList()

    expect(screen.getByText(/Current position: next unread is #1/)).toBeInTheDocument()
    expect(screen.queryByText('Pending change preview')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Show settings for Starman #55' }))
    fireEvent.click(screen.getByLabelText('Skip Starman #55 in this list'))

    const preview = await screen.findByText('Pending change preview')
    const panel = preview.closest('div')!
    expect(within(panel).getByText(/Starman #55 \(updated\)/)).toBeInTheDocument()
    expect(within(panel).getByText(/Position: #1 → #1/)).toBeInTheDocument()
    expect(within(panel).getByText(/Former immediate predecessor: None\. New immediate predecessor: Starman #55\./)).toBeInTheDocument()
    expect(within(panel).getByText(/First unread before save: Starman #55\. After save: All-Star Comics #1\./)).toBeInTheDocument()
    expect(within(panel).getByText(/Cross-list cycle: checked on save/)).toBeInTheDocument()
  })

  it('filters by position in the list search and reports an all-read current position', async () => {
    const allRead = {
      ...existingList,
      entries: existingList.entries.map((entry) => ({ ...entry, status: 'read' as const })),
    }
    mocks.get.mockResolvedValue(allRead)
    renderBuilder()
    await openExistingList()

    expect(screen.getByText('Current position: all issues in this list are read or skipped.')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Find an issue in this reading list'), { target: { value: '2' } })
    await waitFor(() => {
      expect(screen.queryByTestId('reading-list-entry')).toHaveLength(1)
    })
    expect(screen.getAllByText('All-Star Comics #1').length).toBeGreaterThan(0)
    expect(screen.queryByText('Starman #55')).not.toBeInTheDocument()
  })

  it('cancels pending edits and ignores invalid move-before/after targets', async () => {
    renderBuilder()
    await openExistingList()

    await userEvent.setup().click(screen.getByRole('button', { name: 'Show settings for Starman #55' }))
    const relative = screen.getByLabelText('Move Starman #55 relative to issue position')
    fireEvent.change(relative, { target: { value: '99' } })
    expect(screen.getByRole('button', { name: 'Move before issue' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move after issue' })).toBeDisabled()

    fireEvent.click(screen.getByLabelText('Skip Starman #55 in this list'))
    expect(screen.getByText('Pending change preview')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => {
      expect(screen.queryByText('Pending change preview')).not.toBeInTheDocument()
    })
    expect(mocks.update).not.toHaveBeenCalled()
  })
})
