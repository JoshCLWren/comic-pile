import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { issueCardsApi } from '../services/issueCardsApi'

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
  const actual = await vi.importActual<typeof import('../services/api-custom-cbl')>('../services/api-custom-cbl')
  return { ...actual, customCBLApi: mocks }
})

vi.mock('../services/api-cbl-sources', async () => {
  const actual = await vi.importActual<typeof import('../services/api-cbl-sources')>('../services/api-cbl-sources')
  return { ...actual, cblSourcesApi: { discover: vi.fn(), preview: vi.fn() } }
})

function julixShapeEntries(count = 466) {
  return Array.from({ length: count }, (_, index) => {
    const issueNumber = String(index + 1)
    return {
      id: 10000 + index,
      position: index,
      issue_id: 50000 + index,
      thread_id: 2000 + (index % 37),
      series_name: index % 11 === 0 ? 'JLA' : index % 7 === 0 ? 'Justice League of America' : 'Justice League',
      issue_number: issueNumber,
      status: index < 120 ? 'read' : 'unread',
      is_checkpoint: false,
      gate: 'none' as const,
      skipped: false,
    }
  })
}

const julixList = {
  id: 2,
  user_id: 1,
  name: 'Julix Reading Order',
  description: 'Synthetic 466-entry Julix shape fixture',
  mode: 'strict' as const,
  issue_count: 466,
  created_at: '2026-11-20T00:00:00Z',
  updated_at: '2026-11-20T00:00:00Z',
  entries: julixShapeEntries(),
}

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
  return { client }
}

describe('CustomCBLBuilder Julix 466-entry regression', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(issueCardsApi, 'fetchCards').mockResolvedValue([])
    mocks.list.mockResolvedValue([{
      id: 2, name: julixList.name, description: julixList.description,
      mode: julixList.mode, issue_count: julixList.issue_count, updated_at: julixList.updated_at,
    }])
    mocks.get.mockResolvedValue(julixList)
    mocks.searchIssues.mockResolvedValue([
      { issue_id: 999001, thread_id: 7777, series_name: 'JLA Classified', issue_number: '1', status: 'unread' },
    ])
  })

  it('inserts at position 84, moves tail to position 83, saves, reopens, and undoes without altering read status', async () => {
    const user = userEvent.setup()
    const saved = {
      ...julixList,
      updated_at: '2026-11-20T00:05:00Z',
      issue_count: 467,
      entries: (() => {
        const next = [...julixList.entries]
        const [tail] = next.splice(465, 1)
        next.splice(82, 0, tail!)
        next.splice(83, 0, {
          id: -999001, position: 83, issue_id: 999001, thread_id: 7777,
          series_name: 'JLA Classified', issue_number: '1', status: 'unread',
          is_checkpoint: false, gate: 'none' as const, skipped: false,
        })
        return next.map((e, i) => ({ ...e, position: i }))
      })(),
    }
    mocks.update.mockResolvedValueOnce(saved).mockResolvedValueOnce(julixList)

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '2')
    await screen.findAllByTestId('reading-list-entry')

    // Jump to position 84 (1-based in UI)
    fireEvent.change(screen.getByLabelText('Jump to reading list position'), { target: { value: '84' } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to position' }))

    const entry84 = screen.getAllByTestId('reading-list-entry').find((el) => within(el).queryByText(/#84/))
    expect(entry84).toBeTruthy()
    await user.click(within(entry84 as HTMLElement).getByRole('button', { name: /Show settings for/ }))
    await user.click(within(entry84 as HTMLElement).getByRole('button', { name: 'Insert before' }))

    await user.type(screen.getByLabelText('Search issues for custom CBL'), 'JLA Classified')
    await user.click(screen.getByRole('button', { name: 'Find issues' }))
    await user.click(await screen.findByRole('button', { name: /JLA Classified #1/ }))

    // Move tail (position 467 now, original 466) to position 83
    fireEvent.change(screen.getByLabelText('Jump to reading list position'), { target: { value: '467' } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to position' }))
    const tailEntry = screen.getAllByTestId('reading-list-entry').find((el) => within(el).queryByText(/#466/))
    expect(tailEntry).toBeTruthy()
    await user.click(within(tailEntry as HTMLElement).getByRole('button', { name: /Show settings for/ }))
    const moveInput = within(tailEntry as HTMLElement).getByLabelText(/Move .* to position/)
    fireEvent.change(moveInput, { target: { value: '83' } })
    await user.click(within(tailEntry as HTMLElement).getByRole('button', { name: 'Move here' }))

    await user.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    const payload = mocks.update.mock.calls[0][1]
    expect(payload.issue_ids).toHaveLength(467)
    expect(payload.issue_ids[82]).toBe(50000 + 465) // tail moved to pos 83 (0-based 82)
    expect(payload.issue_ids[83]).toBe(999001) // inserted at pos 84
    expect(payload.expected_updated_at).toBe(julixList.updated_at)

    // Reopen: simulate by changing get to saved and reselecting
    mocks.get.mockResolvedValue(saved)
    await user.selectOptions(screen.getByLabelText('Custom CBL'), '2')
    await screen.findByText('JLA Classified #1')

    await user.click(screen.getByRole('button', { name: 'Undo last save' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(2))
    const undoPayload = mocks.update.mock.calls[1][1]
    expect(undoPayload.issue_ids).toHaveLength(466)
    expect(undoPayload.issue_ids[0]).toBe(50000)
  })

  it('supports keyboard insertion and move controls', async () => {
    const user = userEvent.setup()
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '2')
    await screen.findAllByTestId('reading-list-entry')

    const firstEntry = screen.getAllByTestId('reading-list-entry')[0]
    const settings = within(firstEntry).getByRole('button', { name: /Show settings for/ })
    settings.focus()
    await user.keyboard('{Enter}')
    const insertBefore = within(firstEntry).getByRole('button', { name: 'Insert before' })
    insertBefore.focus()
    await user.keyboard('{Enter}')
    expect(screen.getByText(/Next added issue will be inserted before position \d+/)).toBeInTheDocument()
  })
})
