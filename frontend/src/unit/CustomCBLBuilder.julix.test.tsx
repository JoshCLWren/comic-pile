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

function julixEntries(count = 466) {
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
  entries: julixEntries(),
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

    const entry84 = screen.getAllByTestId('reading-list-entry').find((el) => within(el).getByTestId('reading-list-entry-title').textContent?.includes('#84'))
    if (!entry84) throw new Error('Expected to find Julix entry #84 after jumping to position 84')
    await user.click(within(entry84).getByRole('button', { name: /Show settings for/ }))
    await user.click(within(entry84).getByRole('button', { name: 'Insert before' }))

    await user.type(screen.getByLabelText('Search issues for custom CBL'), 'JLA Classified')
    await user.click(screen.getByRole('button', { name: 'Find issues' }))
    await user.click(await screen.findByRole('button', { name: /JLA Classified #1/ }))

    // Move tail (position 467 now, original 466) to position 83
    fireEvent.change(screen.getByLabelText('Jump to reading list position'), { target: { value: '467' } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to position' }))
    const tailEntry = screen.getAllByTestId('reading-list-entry').find((el) => within(el).getByTestId('reading-list-entry-title').textContent?.includes('#466'))
    if (!tailEntry) throw new Error('Expected to find the original tail entry #466 after insertion')
    await user.click(within(tailEntry).getByRole('button', { name: /Show settings for/ }))
    const moveInput = within(tailEntry).getByLabelText(/Move .* to position/)
    fireEvent.change(moveInput, { target: { value: '83' } })
    await user.click(within(tailEntry).getByRole('button', { name: 'Move here' }))

    await user.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    const payload = mocks.update.mock.calls[0][1]
    expect(payload.issue_ids).toHaveLength(467)
    expect(payload.issue_ids).toContain(999001)
    expect(payload.issue_ids).toContain(50000 + 465)
    const insertedIndex = payload.issue_ids.indexOf(999001)
    const tailIndex = payload.issue_ids.indexOf(50000 + 465)
    expect(insertedIndex).toBeGreaterThanOrEqual(0)
    expect(tailIndex).toBeGreaterThanOrEqual(0)
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

  it('moves an entry before/after another issue position and supports insert-after', async () => {
    const user = userEvent.setup()
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '2')
    await screen.findAllByTestId('reading-list-entry')

    const firstEntry = screen.getAllByTestId('reading-list-entry')[0]
    await user.click(within(firstEntry).getByRole('button', { name: /Show settings for/ }))
    await user.click(within(firstEntry).getByRole('button', { name: 'Insert after' }))
    expect(screen.getByText(/Next added issue will be inserted after position 1/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel insert point' }))
    expect(screen.queryByText(/Next added issue will be inserted after position 1/)).not.toBeInTheDocument()

    // Move entry 1 to after issue position 3
    const getFirst = () => screen.getAllByTestId('reading-list-entry')[0]
    const relativeInput = within(getFirst()).getByLabelText(/Move .* relative to issue position/)
    fireEvent.change(relativeInput, { target: { value: '3' } })
    await waitFor(() => {
      expect(within(getFirst()).getByRole('button', { name: 'Move after issue' })).toBeEnabled()
    })
    await user.click(within(getFirst()).getByRole('button', { name: 'Move after issue' }))

    await waitFor(() => {
      const titles = screen.getAllByTestId('reading-list-entry-title').map((el) => el.textContent)
      expect(titles[2]).toContain('#1')
    })

    // Move that entry back before issue position 1
    const movedEntry = screen.getAllByTestId('reading-list-entry').find((el) => within(el).getByTestId('reading-list-entry-title').textContent?.includes('#1'))
    if (!movedEntry) throw new Error('moved entry not found')
    if (within(movedEntry).queryByRole('button', { name: /Show settings for/ })) {
      await user.click(within(movedEntry).getByRole('button', { name: /Show settings for/ }))
    }
    const relativeInput2 = within(movedEntry).getByLabelText(/Move .* relative to issue position/)
    fireEvent.change(relativeInput2, { target: { value: '1' } })
    await waitFor(() => {
      expect(within(movedEntry).getByRole('button', { name: 'Move before issue' })).toBeEnabled()
    })
    await user.click(within(movedEntry).getByRole('button', { name: 'Move before issue' }))

    await waitFor(() => {
      const titles = screen.getAllByTestId('reading-list-entry-title').map((el) => el.textContent)
      expect(titles[0]).toContain('#1')
    })
  })
})
