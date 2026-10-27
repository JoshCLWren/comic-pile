import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { queryKeys } from '../query/queryKeys'

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
  return {
    ...actual,
    customCBLApi: mocks,
  }
})

const cblMocks = vi.hoisted(() => ({
  discover: vi.fn(),
  preview: vi.fn(),
}))

vi.mock('../services/api-cbl-sources', async () => {
  const actual = await vi.importActual<typeof import('../services/api-cbl-sources')>(
    '../services/api-cbl-sources',
  )
  return {
    ...actual,
    cblSourcesApi: cblMocks,
  }
})

function renderBuilder(onApplied = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        // Mirror the production client so background refetches never race the
        // imperative edits these tests make between renders.
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
      <MemoryRouter><CustomCBLBuilder planId={18} onApplied={onApplied} /></MemoryRouter>
    </QueryClientProvider>,
  )
  return { client, onApplied }
}

const existingList = {
  id: 9,
  user_id: 1,
  name: 'Starman into JSA',
  description: 'The bridge I actually want',
  mode: 'loose',
  issue_count: 2,
  created_at: '2026-09-14T03:00:00Z',
  updated_at: '2026-09-14T03:00:00Z',
  entries: [
    {
      id: 91,
      position: 0,
      issue_id: 26360,
      thread_id: 180,
      series_name: 'Starman',
      issue_number: '55',
      status: 'unread',
      is_checkpoint: false,
      gate: 'none',
      skipped: false,
    },
    {
      id: 92,
      position: 1,
      issue_id: 30001,
      thread_id: 9001,
      series_name: 'All-Star Comics',
      issue_number: '1',
      status: 'unread',
      is_checkpoint: false,
      gate: 'none',
      skipped: false,
    },
  ],
}

const globalSource = {
  id: 9001,
  name: 'Global Starman CBL',
  source_path: 'starman.cbl',
  source_repository: 'shared/cbls',
  declared_issue_count: 2,
  content_hash: 'review-hash',
  revision_sha: 'review-revision',
}

type PreviewRow = {
  cbl_position: number
  cbl_entry_id: number
  series_name: string
  issue_number: string
  series_group_id: string
  adoption_class: string
  adoption_decision: string
  adopted: boolean
  resolved_issue_id: number | null
  resolution_status: string
  collection_excluded?: boolean
}

function previewResponse(entries: PreviewRow[]) {
  return {
    source: {
      source_list_id: globalSource.id,
      source_repository: globalSource.source_repository,
      source_path: globalSource.source_path,
      content_hash: globalSource.content_hash,
      revision_sha: globalSource.revision_sha,
    },
    total_positions: entries.length,
    entries,
    summary: {
      reused_existing_count: 0,
      missing_would_create_count: 0,
      excluded_count: 0,
      unresolved_count: 0,
      awaiting_opt_in_count: 0,
      final_adopted_count: entries.length,
      final_adopted_order: entries.map((entry) => entry.cbl_position),
      reused_existing_positions: [],
      missing_would_create_positions: [],
      excluded_positions: [],
      unresolved_positions: [],
      awaiting_opt_in_positions: [],
    },
  }
}

async function openReplacementReview(repeatSourceEntry = false) {
  cblMocks.discover.mockResolvedValue([globalSource])
  const rows = existingList.entries.map((entry) => ({
    cbl_position: entry.position,
    cbl_entry_id: entry.id,
    series_name: entry.series_name,
    issue_number: entry.issue_number,
    series_group_id: String(entry.thread_id),
    adoption_class: 'existing',
    adoption_decision: 'included_existing',
    adopted: true,
    resolved_issue_id: entry.issue_id,
    resolution_status: 'resolved_exact',
  }))
  if (repeatSourceEntry) rows.push({ ...rows[0]! })
  cblMocks.preview.mockResolvedValue(previewResponse(rows))
  renderBuilder()
  fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
  fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
  await screen.findByText('Starman #55')
  fireEvent.click(screen.getByRole('button', { name: 'Replace using CBL' }))
  fireEvent.change(screen.getByLabelText('Search global CBL sources'), { target: { value: 'Starman' } })
  fireEvent.click(screen.getByRole('button', { name: 'Find CBLs' }))
  fireEvent.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
  await screen.findByTestId('confirm-replace')
}

const waitingChange = {
  issue_id: 30001,
  issue_name: 'All-Star Comics #1',
  before_issue_ids: [],
  before_issue_names: [],
  after_issue_ids: [26360],
  after_issue_names: ['Starman #55'],
}

const waitingConfirmationError = {
  isAxiosError: true,
  response: {
    status: 409,
    data: { detail: {
      code: 'reading_list_predecessor_confirmation_required',
      predecessor_changes: [waitingChange],
    } },
  },
}

describe('CustomCBLBuilder', () => {
  it('explains a Create cycle with named comics and an owned prerequisite editor link', async () => {
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 422, data: { detail: {
        code: 'reading_list_cycle',
        message: 'Reading constraint cycle: Issue 1002365 -> Issue 1000768',
        path: [{
          source_issue_id: 1002365, source_issue_name: 'X-Force/Champions Annual 1998', source_thread_id: 12,
          target_issue_id: 1000768, target_issue_name: 'X-Force #85', target_thread_id: 12,
          origin: 'prerequisite 1001867 (converted)', prerequisite_origin: 'converted', provenance: [],
        }],
      } } },
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(screen.getByLabelText('New custom CBL name'), { target: { value: 'My new list' } })
    fireEvent.click(screen.getByRole('button', { name: /^Create$/ }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('An existing reading cycle prevents creating this list')
    expect(alert).toHaveTextContent('X-Force/Champions Annual 1998 → X-Force #85')
    expect(alert).toHaveTextContent('No new list was saved')
    expect(alert).not.toHaveTextContent('1002365')
    expect(screen.getByLabelText('New custom CBL name')).toHaveValue('My new list')
    expect(screen.getByRole('link', { name: 'Review prerequisites for X-Force #85' })).toHaveAttribute('href', '/thread/12?prerequisites=1')
    fireEvent.change(screen.getByLabelText('Custom CBL'), { target: { value: '9' } })
    await waitFor(() => expect(screen.queryByText(/An existing reading cycle/)).not.toBeInTheDocument())
  })
  beforeEach(() => {
    vi.resetAllMocks()
    mocks.list.mockResolvedValue([
      {
        id: 9,
        name: existingList.name,
        description: existingList.description,
        mode: existingList.mode,
        issue_count: 2,
        updated_at: existingList.updated_at,
      },
    ])
    mocks.get.mockResolvedValue(existingList)
    mocks.searchIssues.mockResolvedValue([
      {
        issue_id: 30002,
        thread_id: 9002,
        series_name: 'JSA',
        issue_number: '1',
        status: 'unread',
      },
    ])
  })

  it('keeps long issue names readable with phone-sized actions and optional settings', async () => {
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Starman #55')
    const card = screen.getAllByTestId('reading-list-entry')[0]
    const title = within(card).getByTestId('reading-list-entry-title')
    expect(title).toHaveTextContent('Starman #55')
    expect(title).toHaveClass('break-words')
    expect(title).not.toHaveClass('truncate')
    expect(within(card).getByRole('button', { name: 'Move Starman #55 earlier' })).toHaveClass('min-h-11')
    expect(within(card).getByRole('button', { name: 'Remove Starman #55' })).toHaveClass('min-h-11')
    const options = within(card).getByRole('button', { name: 'Show settings for Starman #55' })
    expect(options).toHaveAttribute('aria-expanded', 'false')
    const settings = within(card).getByLabelText('Wait behavior for Starman #55').closest('div')
    expect(settings).toHaveClass('hidden')
    fireEvent.click(options)
    expect(within(card).getByRole('button', { name: 'Hide settings for Starman #55' })).toHaveAttribute('aria-expanded', 'true')
    expect(settings).toHaveClass('flex')
  })

  it('navigates 65 strict-list issues in pages, jumps and moves an issue without discarding the others', async () => {
    const entries = Array.from({ length: 65 }, (_, index) => ({
      ...existingList.entries[0],
      id: 1000 + index,
      issue_id: 80000 + index,
      position: index,
      series_name: 'Hellboy and the B.P.R.D.: The Long Night',
      issue_number: String(index + 1),
    }))
    const longList = { ...existingList, mode: 'strict', issue_count: entries.length, entries }
    mocks.get.mockResolvedValue(longList)
    mocks.update.mockResolvedValue(longList)
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })

    await screen.findByText('Hellboy and the B.P.R.D.: The Long Night #1')
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(30)
    expect(screen.getByText('Hellboy and the B.P.R.D.: The Long Night #1')).toBeInTheDocument()
    expect(screen.queryByText('Hellboy and the B.P.R.D.: The Long Night #31')).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Next 30' })[0])
    expect(screen.getByText('Hellboy and the B.P.R.D.: The Long Night #31')).toBeInTheDocument()
    expect(screen.queryByText('Hellboy and the B.P.R.D.: The Long Night #1')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Jump to reading list position'), { target: { value: '65' } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to position' }))
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(5)
    const last = screen.getAllByTestId('reading-list-entry').at(-1)!
    const label = 'Hellboy and the B.P.R.D.: The Long Night #65'
    expect(within(last).getByTestId('reading-list-entry-title')).toHaveTextContent(label)
    fireEvent.click(within(last).getByRole('button', { name: `Show settings for ${label}` }))
    fireEvent.change(within(last).getByLabelText(`Move ${label} to position`), { target: { value: '2' } })
    fireEvent.click(within(last).getByRole('button', { name: 'Move here' }))
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(30)
    expect(screen.getAllByTestId('reading-list-entry')[1]).toHaveTextContent(label)
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({
        issue_ids: expect.arrayContaining([80000, 80064, 80063]),
      }))
      const payload = mocks.update.mock.calls[0][1]
      expect(payload.issue_ids).toHaveLength(65)
      expect(payload.issue_ids.slice(0, 3)).toEqual([80000, 80064, 80001])
    })

    fireEvent.change(screen.getByLabelText('Find an issue in this reading list'), { target: { value: '#49' } })
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(1)
    expect(screen.getByText('Hellboy and the B.P.R.D.: The Long Night #49')).toBeInTheDocument()
  })

  it('goes to the correct previous page after removing the final issue on the last page', async () => {
    const entries = Array.from({ length: 61 }, (_, index) => ({
      ...existingList.entries[0],
      id: 500 + index,
      issue_id: 70000 + index,
      position: index,
      series_name: 'Mobile Reading Series',
      issue_number: String(index + 1),
    }))
    mocks.get.mockResolvedValue({ ...existingList, issue_count: entries.length, entries })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Mobile Reading Series #1')
    fireEvent.click(screen.getAllByRole('button', { name: 'Next 30' })[0])
    fireEvent.click(screen.getAllByRole('button', { name: 'Next 30' })[0])
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Remove Mobile Reading Series #61' }))
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(30)
    fireEvent.click(screen.getAllByRole('button', { name: 'Previous 30' })[0])
    expect(screen.getByText('Mobile Reading Series #1')).toBeInTheDocument()
    expect(screen.queryByText('Mobile Reading Series #31')).not.toBeInTheDocument()
  })

  it('navigates issue results with arrows and adds only the focused canonical issue with Enter', async () => {
    const user = userEvent.setup()
    mocks.searchIssues.mockResolvedValue([
      { issue_id: 30002, thread_id: 9002, series_name: 'Fantastic Four', issue_number: '1', status: 'unread' },
      { issue_id: 30003, thread_id: 9002, series_name: 'Fantastic Four', issue_number: '2', status: 'unread' },
    ])
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    const input = await screen.findByLabelText('Search issues for custom CBL')
    await user.type(input, 'Fantastic Four{Enter}')
    await waitFor(() => expect(mocks.searchIssues).toHaveBeenCalledWith('Fantastic Four'))
    const first = await screen.findByRole('button', { name: /Fantastic Four #1/ })
    const second = screen.getByRole('button', { name: /Fantastic Four #2/ })
    await user.keyboard('{ArrowDown}')
    expect(first).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(second).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(first).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(second).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(input).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(first).toHaveFocus()
    expect(mocks.searchIssues).toHaveBeenCalledTimes(1)
    expect(mocks.update).not.toHaveBeenCalled()
    await user.keyboard('{Enter}')
    expect(input).toHaveFocus()
    expect(screen.getByRole('status')).toHaveTextContent('Added Fantastic Four #1 to this list.')
    const ordered = screen.getByRole('list', { name: 'Custom CBL ordered issues' })
    expect(ordered).toHaveTextContent('Fantastic Four #1')
    expect(ordered).not.toHaveTextContent('Fantastic Four #2')
    expect(first).not.toBeInTheDocument()
  })

  it('hides results from the previous query while a different search is being typed', async () => {
    const user = userEvent.setup()
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    const input = await screen.findByLabelText('Search issues for custom CBL')
    await user.type(input, 'JSA{Enter}')
    await waitFor(() => expect(mocks.searchIssues).toHaveBeenCalledWith('JSA'))
    expect(await screen.findByRole('button', { name: /JSA #1/ })).toBeVisible()
    await user.clear(input)
    await user.type(input, 'Batman')
    expect(screen.queryByRole('button', { name: /JSA #1/ })).not.toBeInTheDocument()
    await user.keyboard('{ArrowDown}')
    expect(input).toHaveFocus()
  })

  it('edits a custom CBL using real issues, saves exact order, and applies it to the Reading Plan', async () => {
    const saved = {
      ...existingList,
      issue_count: 3,
      entries: [
        ...existingList.entries,
        {
          id: 93,
          position: 2,
          issue_id: 30002,
          thread_id: 9002,
          series_name: 'JSA',
          issue_number: '1',
          status: 'unread',
          is_checkpoint: false,
          gate: 'none',
          skipped: false,
        },
      ],
    }
    mocks.update.mockResolvedValue(saved)
    mocks.apply.mockResolvedValue({
      id: 18,
      user_id: 1,
      name: 'Starman Compendiums + JSA',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Main', order: 0 }],
      nodes: [
        { id: 'starman-55', node_type: 'issue', ref_id: 26360, lane_id: 'main', position: 0 },
        { id: 'all-star-1', node_type: 'issue', ref_id: 30001, lane_id: 'main', position: 1 },
        { id: 'jsa-1', node_type: 'issue', ref_id: 30002, lane_id: 'main', position: 2 },
      ],
      created_at: '2026-09-14T03:00:00Z',
      updated_at: '2026-09-14T03:05:00Z',
      added_issue_ids: [30001, 30002],
      skipped_existing_issue_ids: [26360],
    })
    const { onApplied } = renderBuilder()

    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    const select = await screen.findByLabelText('Custom CBL')
    fireEvent.change(select, { target: { value: '9' } })

    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    expect(screen.getByText('All-Star Comics #1')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search issues for custom CBL'), {
      target: { value: 'JSA' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Find issues' }))
    fireEvent.click(await screen.findByRole('button', { name: /JSA #1/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001, 30002],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
          30002: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      })
    })

    const applyButton = await screen.findByRole('button', { name: 'Apply to this Reading Plan' })
    await waitFor(() => expect(applyButton).not.toBeDisabled())
    fireEvent.click(applyButton)

    await waitFor(() => expect(mocks.apply).toHaveBeenCalledWith(9, 18))
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1))
  })

  it('creates an empty custom CBL and exposes it for editing', async () => {
    const created = {
      id: 10,
      user_id: 1,
      name: 'Cosmic detour',
      description: null,
      mode: 'loose',
      issue_count: 0,
      created_at: '2026-09-14T03:10:00Z',
      updated_at: '2026-09-14T03:10:00Z',
      entries: [],
    }
    mocks.create.mockResolvedValue(created)
    mocks.get.mockResolvedValue(created)
    renderBuilder()

    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(screen.getByLabelText('New custom CBL name'), {
      target: { value: '  Cosmic detour  ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith({ name: 'Cosmic detour', issue_ids: [] })
    })
    expect(await screen.findByText('This custom CBL is empty. Search for issues above to build it.')).toBeInTheDocument()
  })

  it('reorders, removes, saves, exports, and deletes an existing custom CBL', async () => {
    const onlyAllStar = {
      ...existingList,
      description: null,
      issue_count: 1,
      entries: [
        {
          ...existingList.entries[1],
          position: 0,
        },
      ],
    }
    mocks.update.mockResolvedValue(onlyAllStar)
    mocks.exportXml.mockResolvedValue('<ReadingList><Name>Starman into JSA</Name></ReadingList>')
    mocks.delete.mockResolvedValue(undefined)
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:custom-cbl'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })

    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Move All-Star Comics #1 earlier' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Starman #55' }))
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: '   ' } })

    expect(screen.getByText('Save this custom CBL before applying or exporting it.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))

    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        name: 'Starman into JSA',
        description: null,
        mode: 'loose',
        issue_ids: [30001],
        entry_intents: {
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      })
    })

    const exportButton = await screen.findByRole('button', { name: 'Export .cbl' })
    await waitFor(() => expect(exportButton).not.toBeDisabled())
    fireEvent.click(exportButton)
    await waitFor(() => expect(mocks.exportXml).toHaveBeenCalledWith(9))
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:custom-cbl')
    expect(anchorClick).toHaveBeenCalled()

    // Delete confirms through an in-page dialog QA automation can operate,
    // not a native window.confirm the harness auto-dismisses.
    const deleteButton = screen.getByRole('button', { name: 'Delete' })
    fireEvent.click(deleteButton)
    expect(screen.getByRole('dialog', { name: 'Delete custom CBL' })).toBeInTheDocument()
    expect(mocks.delete).not.toHaveBeenCalled()

    // Cancelling keeps the saved list exactly as it is.
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Delete custom CBL' })).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Delete custom CBL' })).not.toBeInTheDocument())
    expect(mocks.delete).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Custom CBL')).toHaveValue('9')

    fireEvent.click(deleteButton)
    fireEvent.click(screen.getByRole('button', { name: 'Delete custom CBL' }))
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith(9))
    expect(await screen.findByRole('status')).toHaveTextContent('Custom CBL deleted.')

    anchorClick.mockRestore()
  })

  it('keeps the delete confirmation open with a visible error when deletion fails', async () => {
    mocks.delete.mockRejectedValue(new Error('Deletion unavailable'))
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete custom CBL' }))

    const dialog = screen.getByRole('dialog', { name: 'Delete custom CBL' })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Deletion unavailable')
    // The list survives the failed deletion and stays loaded for a retry.
    expect(screen.getByText('Starman #55')).toBeInTheDocument()

    // Reopening must not resurrect the previous failure as if it just happened.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const reopened = screen.getByRole('dialog', { name: 'Delete custom CBL' })
    expect(within(reopened).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('flags a custom CBL checkpoint and includes it on save', async () => {
    mocks.update.mockResolvedValue({
      ...existingList,
      entries: [
        { ...existingList.entries[0], is_checkpoint: true },
        existingList.entries[1],
      ],
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Mark Starman #55 as crossover checkpoint' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))

    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [26360],
      })
    })
  })

  it('saves strict mode with positional gates and list-local skips', async () => {
    mocks.update.mockResolvedValue({
      ...existingList,
      mode: 'strict',
      entries: [
        { ...existingList.entries[0], skipped: true },
        { ...existingList.entries[1], gate: 'after_previous' },
      ],
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('All-Star Comics #1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: /^Strict/ }))
    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    fireEvent.click(screen.getByLabelText('Skip Starman #55 in this list'))

    expect(await screen.findByText('Skipped in this list')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))

    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'strict',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: true },
          30001: { gate: 'after_previous', skipped: false },
        },
        checkpoint_issue_ids: [],
      })
    })
  })

  it('requires explicit confirmation before persisting changed waits', async () => {
    const predecessorChange = {
      issue_id: 30001,
      issue_name: 'All-Star Comics #1',
      before_issue_ids: [],
      before_issue_names: [],
      after_issue_ids: [26360],
      after_issue_names: ['Starman #55'],
    }
    mocks.update
      .mockRejectedValueOnce({
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            detail: {
              code: 'reading_list_predecessor_confirmation_required',
              predecessor_changes: [predecessorChange],
            },
          },
        },
      })
      .mockResolvedValueOnce({
        ...existingList,
        entries: [
          existingList.entries[0],
          { ...existingList.entries[1], gate: 'after_previous' },
        ],
      })

    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))

    const dialog = await screen.findByRole('dialog', { name: 'Confirm waiting changes' })
    expect(dialog).toHaveTextContent('All-Star Comics #1 now waits on Starman #55.')

    fireEvent.click(screen.getByRole('button', { name: 'Confirm and save' }))

    await waitFor(() => {
      expect(mocks.update).toHaveBeenNthCalledWith(2, 9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'after_previous', skipped: false },
        },
        checkpoint_issue_ids: [],
        confirmed_predecessor_changes: [predecessorChange],
      })
    })
  })

  it('leaves persisted content untouched when a predecessor confirmation is cancelled', async () => {
    mocks.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          detail: {
            code: 'reading_list_predecessor_confirmation_required',
            predecessor_changes: [
              {
                issue_id: 30001,
                issue_name: 'All-Star Comics #1',
                before_issue_ids: [],
                before_issue_names: [],
                after_issue_ids: [26360],
                after_issue_names: ['Starman #55'],
              },
            ],
          },
        },
      },
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))

    await screen.findByRole('dialog', { name: 'Confirm waiting changes' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Confirm waiting changes' })).not.toBeInTheDocument()
    })
    expect(mocks.update).toHaveBeenCalledTimes(1)
    // The unsaved edit remains in the editor; nothing was persisted.
    expect(screen.getByLabelText('Wait behavior for All-Star Comics #1')).toHaveValue('after_previous')
  })

  it('shows actionable feedback when a save would create a reading cycle', async () => {
    mocks.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 422,
        data: {
          detail: {
            code: 'reading_list_cycle',
            message: 'Cycle detected',
            path: [
              {
                source_issue_id: 26360,
                source_issue_name: 'Starman #55',
                target_issue_id: 99001,
                target_issue_name: 'JSA #1',
                origin: 'list Other',
                prerequisite_origin: null,
                provenance: [],
              },
              {
                source_issue_id: 99001,
                source_issue_name: 'JSA #1',
                target_issue_id: 26360,
                target_issue_name: 'Starman #55',
                origin: 'list Other',
                prerequisite_origin: null,
                provenance: [],
              },
            ],
          },
        },
      },
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    const saveButton = screen.getByRole('button', { name: 'Save custom CBL' })
    expect(saveButton).toBeEnabled()
    fireEvent.click(saveButton)
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(
      'This order would create a reading cycle: Starman #55 → JSA #1 → Starman #55.',
    )
    // The conflicting Issue is not a member of this list; the server names it.
    expect(alert).not.toHaveTextContent('Issue #99001')
  })

  it('preserves unsaved gate and skip edits when the selected list refreshes', async () => {
    const { client } = renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Starman #55')
    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    fireEvent.click(screen.getByLabelText('Skip Starman #55 in this list'))

    // Force a changed query result for the same identity, as a background refresh
    // can do while the reader has an unsaved draft.
    mocks.get.mockResolvedValueOnce({ ...existingList, updated_at: '2026-09-14T05:00:00Z' })
    await act(async () => {
      await client.refetchQueries({ queryKey: queryKeys.customCBLs.detail(9) })
    })
    expect(mocks.get).toHaveBeenCalledTimes(2)
    expect(screen.getByLabelText('Wait behavior for All-Star Comics #1')).toHaveValue('after_previous')
    expect(screen.getByLabelText('Skip Starman #55 in this list')).toBeChecked()
    expect(screen.getByRole('button', { name: 'Save custom CBL' })).toBeEnabled()
  })

  it('clears a stale cycle error when switching to another custom CBL', async () => {
    const otherList = {
      id: 10,
      user_id: 1,
      name: 'Other List',
      description: null,
      mode: 'loose',
      issue_count: 1,
      created_at: '2026-09-14T04:00:00Z',
      updated_at: '2026-09-14T04:00:00Z',
      entries: [
        {
          id: 101,
          position: 0,
          issue_id: 50001,
          thread_id: 7001,
          series_name: 'JSA',
          issue_number: '1',
          status: 'unread',
          is_checkpoint: false,
          gate: 'none',
          skipped: false,
        },
      ],
    }
    mocks.list.mockResolvedValue([
      {
        id: 9,
        name: existingList.name,
        description: existingList.description,
        mode: existingList.mode,
        issue_count: 2,
        updated_at: existingList.updated_at,
      },
      {
        id: 10,
        name: otherList.name,
        description: otherList.description,
        mode: otherList.mode,
        issue_count: 1,
        updated_at: otherList.updated_at,
      },
    ])
    mocks.get.mockImplementation((id: number) =>
      Promise.resolve(id === 10 ? otherList : existingList),
    )
    mocks.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 422,
        data: {
          detail: {
            code: 'reading_list_cycle',
            message: 'Cycle detected',
            path: [
              {
                source_issue_id: 26360,
                source_issue_name: 'Starman #55',
                target_issue_id: 30001,
                target_issue_name: 'All-Star Comics #1',
                origin: 'list',
                prerequisite_origin: null,
                provenance: [],
              },
            ],
          },
        },
      },
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    const select = await screen.findByLabelText('Custom CBL')
    fireEvent.change(select, { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    expect(screen.getByLabelText('Wait behavior for All-Star Comics #1')).toHaveValue('after_previous')
    const saveButton = screen.getByRole('button', { name: 'Save custom CBL' })
    expect(saveButton).toBeEnabled()
    fireEvent.click(saveButton)
    expect(await screen.findByRole('alert')).toHaveTextContent('create a reading cycle')

    fireEvent.change(select, { target: { value: '10' } })
    expect(await screen.findByText('JSA #1')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByText(/create a reading cycle/)).not.toBeInTheDocument()
    })
  })

  it('surfaces strict-mode coverage warnings returned by a successful save', async () => {
    mocks.update.mockResolvedValue({
      ...existingList,
      mode: 'strict',
      warnings: ['Strict list omits 2 unread Issues from Golden Path Series: #2, #3'],
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: /^Strict/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))

    expect(await screen.findByText('Coverage warnings')).toBeInTheDocument()
    expect(
      screen.getByText('Strict list omits 2 unread Issues from Golden Path Series: #2, #3'),
    ).toBeInTheDocument()
  })

  it('replaces only the selected Reading List from a global CBL and undoes list membership only', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([
      {
        id: 101,
        name: 'Global Starman CBL',
        source_path: 'starman.cbl',
        source_repository: 'shared/cbls',
        declared_issue_count: 3,
        content_hash: 'hash-101',
        revision_sha: 'revision-101',
      },
    ])
    cblMocks.preview.mockResolvedValue({
      source: {
        source_list_id: 101,
        source_repository: 'shared/cbls',
        source_path: 'starman.cbl',
        content_hash: 'hash-101',
        revision_sha: 'revision-101',
      },
      total_positions: 3,
      summary: {
        reused_existing_count: 2,
        missing_would_create_count: 1,
        excluded_count: 0,
        unresolved_count: 1,
        awaiting_opt_in_count: 0,
        final_adopted_count: 2,
        final_adopted_order: [0, 1],
        reused_existing_positions: [0, 1],
        missing_would_create_positions: [2],
        excluded_positions: [],
        unresolved_positions: [],
        awaiting_opt_in_positions: [],
      },
      entries: [
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
        {
          cbl_position: 1,
          cbl_entry_id: 2,
          series_name: 'JSA',
          issue_number: '1',
          series_group_id: 'jsa',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 30002,
          resolution_status: 'resolved_exact',
        },
        {
          cbl_position: 2,
          cbl_entry_id: 3,
          series_name: 'JSA',
          issue_number: '2',
          series_group_id: 'jsa',
          adoption_class: 'missing_importable',
          adoption_decision: 'awaiting_opt_in',
          adopted: false,
          resolved_issue_id: null,
          resolution_status: 'missing',
        },
      ],
    })
    mocks.update.mockResolvedValue({
      ...existingList,
      updated_at: '2026-09-14T03:10:00Z',
      issue_count: 3,
      entries: [
        { ...existingList.entries[0], position: 0 },
        {
          id: 94,
          position: 1,
          issue_id: 30002,
          thread_id: 9002,
          series_name: 'JSA',
          issue_number: '1',
          status: 'unread',
          is_checkpoint: false,
          gate: 'none',
          skipped: false,
        },
        { ...existingList.entries[1], position: 2 },
      ],
    })
    const replacedList = {
      ...existingList,
      updated_at: '2026-09-14T03:10:00Z',
      issue_count: 3,
      entries: [
        { ...existingList.entries[0], position: 0 },
        {
          id: 94,
          position: 1,
          issue_id: 30002,
          thread_id: 9002,
          series_name: 'JSA',
          issue_number: '1',
          status: 'unread',
          is_checkpoint: false,
          gate: 'none',
          skipped: false,
        },
        { ...existingList.entries[1], position: 2 },
      ],
    }
    // Detail load, then the replacement's stale-review check read the original
    // version; Undo must see the version the replacement wrote.
    mocks.get
      .mockResolvedValueOnce(existingList)
      .mockResolvedValueOnce(existingList)
      .mockResolvedValue(replacedList)

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))

    expect(await screen.findByTestId('cbl-replace-review')).toBeInTheDocument()
    expect(screen.getByTestId('cbl-replace-graph-impact')).toHaveTextContent('Waits-on links')
    expect(screen.getByTestId('default-30002')).toHaveTextContent('default')
    expect(screen.getByTestId('manual-30001')).toHaveTextContent('(manual)')
    expect(screen.getByText(/1 source entry is not in your library yet/)).toBeInTheDocument()

    await user.click(screen.getByTestId('confirm-replace'))

    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith(9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30002, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30002: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Replaced this Reading List')

    await user.click(screen.getByRole('button', { name: 'Undo last replacement' }))

    await waitFor(() =>
      expect(mocks.update).toHaveBeenLastCalledWith(9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Read history and ratings were not changed')
  })

  it('rejects a replacement review whose Reading List changed before confirmation', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([
      {
        id: 101,
        name: 'Global Starman CBL',
        source_path: 'starman.cbl',
        source_repository: 'shared/cbls',
        declared_issue_count: 1,
        content_hash: 'hash-101',
        revision_sha: 'revision-101',
      },
    ])
    cblMocks.preview.mockResolvedValue({
      source: {
        source_list_id: 101,
        source_repository: 'shared/cbls',
        source_path: 'starman.cbl',
        content_hash: 'hash-101',
        revision_sha: 'revision-101',
      },
      total_positions: 1,
      summary: {
        reused_existing_count: 1,
        missing_would_create_count: 0,
        excluded_count: 0,
        unresolved_count: 0,
        awaiting_opt_in_count: 0,
        final_adopted_count: 1,
        final_adopted_order: [0],
        reused_existing_positions: [0],
        missing_would_create_positions: [],
        excluded_positions: [],
        unresolved_positions: [],
        awaiting_opt_in_positions: [],
      },
      entries: [
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ],
    })

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    expect(await screen.findByTestId('cbl-replace-review')).toBeInTheDocument()

    mocks.get.mockResolvedValue({
      ...existingList,
      updated_at: '2026-09-14T04:00:00Z',
    })
    await user.click(screen.getByTestId('confirm-replace'))

    expect(await screen.findByRole('alert')).toHaveTextContent('changed after you reviewed it')
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it('asks for changed-wait confirmation before persisting a replacement', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'All-Star Comics',
          issue_number: '1',
          series_group_id: 'all-star',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 30001,
          resolution_status: 'resolved_exact',
        },
        {
          cbl_position: 1,
          cbl_entry_id: 2,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ]),
    )
    const predecessorChange = {
      issue_id: 30001,
      issue_name: 'All-Star Comics #1',
      before_issue_ids: [],
      before_issue_names: [],
      after_issue_ids: [26360],
      after_issue_names: ['Starman #55'],
    }
    mocks.update
      .mockRejectedValueOnce({
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            detail: {
              code: 'reading_list_predecessor_confirmation_required',
              predecessor_changes: [predecessorChange],
            },
          },
        },
      })
      .mockResolvedValueOnce({
        ...existingList,
        updated_at: '2026-09-14T03:20:00Z',
        entries: [
          { ...existingList.entries[1], position: 0 },
          { ...existingList.entries[0], position: 1 },
        ],
      })
    mocks.get.mockResolvedValue(existingList)

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    await user.click(await screen.findByTestId('confirm-replace'))

    const dialog = await screen.findByRole('dialog', {
      name: 'Confirm replacement waiting changes',
    })
    expect(dialog).toHaveTextContent('All-Star Comics #1 now waits on Starman #55.')
    expect(mocks.update).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Confirm and replace' }))

    await waitFor(() => {
      expect(mocks.update).toHaveBeenNthCalledWith(2, 9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [30001, 26360],
        entry_intents: {
          30001: { gate: 'none', skipped: false },
          26360: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
        confirmed_predecessor_changes: [predecessorChange],
      })
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Replaced this Reading List')
  })

  it('clears Undo after another save and rejects a stale Undo snapshot', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ]),
    )
    const replacedList = {
      ...existingList,
      updated_at: '2026-09-14T03:10:00Z',
      entries: existingList.entries,
    }
    const savedAfterMove = {
      ...existingList,
      updated_at: '2026-09-14T03:20:00Z',
      entries: [
        { ...existingList.entries[1], position: 0 },
        { ...existingList.entries[0], position: 1 },
      ],
    }
    mocks.update.mockResolvedValueOnce(replacedList).mockResolvedValueOnce(savedAfterMove)
    mocks.get.mockResolvedValue(existingList)

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    await user.click(await screen.findByTestId('confirm-replace'))
    expect(await screen.findByRole('button', { name: 'Undo last replacement' })).toBeInTheDocument()

    // A later save invalidates the replacement snapshot instead of letting
    // Undo silently erase it.
    await user.click(screen.getByRole('button', { name: 'Move All-Star Comics #1 earlier' }))
    await user.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Undo last replacement' })).not.toBeInTheDocument()
    })
  })

  it('refuses a stale Undo snapshot without writing the old membership', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ]),
    )
    mocks.update.mockResolvedValue({
      ...existingList,
      updated_at: '2026-09-14T03:10:00Z',
      issue_count: 1,
      entries: [existingList.entries[0]],
    })
    mocks.get
      .mockResolvedValueOnce(existingList)
      .mockResolvedValueOnce(existingList)
      .mockResolvedValue({ ...existingList, updated_at: '2026-09-14T04:00:00Z' })

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    await user.click(await screen.findByTestId('confirm-replace'))
    await user.click(await screen.findByRole('button', { name: 'Undo last replacement' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Undo is no longer available')
    expect(mocks.update).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Undo last replacement' })).not.toBeInTheDocument()
    })
  })

  it('restores original checkpoint targets in the Undo payload', async () => {
    const user = userEvent.setup()
    const checkpointList = {
      ...existingList,
      entries: [
        {
          ...existingList.entries[0],
          is_checkpoint: true,
          checkpoint_target_issue_ids: [30001],
        },
        existingList.entries[1],
      ],
    }
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ]),
    )
    const replacedList = {
      ...checkpointList,
      updated_at: '2026-09-14T03:10:00Z',
      issue_count: 1,
      entries: [{ ...checkpointList.entries[0], position: 0 }],
    }
    mocks.update.mockResolvedValue(replacedList)
    mocks.get
      .mockResolvedValueOnce(checkpointList)
      .mockResolvedValueOnce(checkpointList)
      .mockResolvedValue(replacedList)

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    await user.click(await screen.findByTestId('confirm-replace'))
    await user.click(await screen.findByRole('button', { name: 'Undo last replacement' }))

    await waitFor(() => {
      expect(mocks.update).toHaveBeenLastCalledWith(9, {
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [26360],
        checkpoint_targets: { 26360: [30001] },
      })
    })
  })

  it('leaves collection-excluded source rows unchecked unless they were already saved', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
        {
          cbl_position: 1,
          cbl_entry_id: 2,
          series_name: 'All-Star Comics',
          issue_number: '1',
          series_group_id: 'all-star',
          adoption_class: 'existing',
          adoption_decision: 'excluded',
          adopted: false,
          resolved_issue_id: 30001,
          resolution_status: 'resolved_exact',
          collection_excluded: true,
        },
        {
          cbl_position: 2,
          cbl_entry_id: 3,
          series_name: 'JSA',
          issue_number: '1',
          series_group_id: 'jsa',
          adoption_class: 'existing',
          adoption_decision: 'excluded',
          adopted: false,
          resolved_issue_id: 30002,
          resolution_status: 'resolved_exact',
          collection_excluded: true,
        },
      ]),
    )

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))

    // An excluded row that was already saved stays visible as a saved selection;
    // a never-saved excluded row does not become a checked default.
    expect(await screen.findByTestId('toggle-30001')).toBeChecked()
    expect(screen.getByTestId('saved-30001')).toBeInTheDocument()
    expect(screen.queryByTestId('default-30001')).not.toBeInTheDocument()
    expect(screen.queryByTestId('after-30002')).not.toBeInTheDocument()
  })

  it('shows a source search failure with a retry action instead of an empty result', async () => {
    const user = userEvent.setup()
    cblMocks.discover
      .mockRejectedValueOnce(new Error('Source registry unavailable'))
      .mockResolvedValueOnce([globalSource])

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Source registry unavailable')
    await user.click(screen.getByRole('button', { name: 'Retry source search' }))
    expect(await screen.findByRole('button', { name: /Global Starman CBL/ })).toBeInTheDocument()
  })

  it('shows a preview failure with a retry action instead of a silent source', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview
      .mockRejectedValueOnce(new Error('Preview unavailable'))
      .mockResolvedValueOnce(
        previewResponse([
          {
            cbl_position: 0,
            cbl_entry_id: 1,
            series_name: 'Starman',
            issue_number: '55',
            series_group_id: 'starman',
            adoption_class: 'existing',
            adoption_decision: 'included_existing',
            adopted: true,
            resolved_issue_id: 26360,
            resolution_status: 'resolved_exact',
          },
        ]),
      )

    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Preview unavailable')
    await user.click(screen.getByRole('button', { name: 'Retry preview' }))
    expect(await screen.findByTestId('cbl-replace-review')).toBeInTheDocument()
  })

  it('shows export failures and revokes a created object URL', async () => {
    mocks.exportXml.mockResolvedValue('<ReadingList />')
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
      throw new Error('Download blocked')
    })
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:failed-custom-cbl'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })

    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Export .cbl' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Download blocked')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:failed-custom-cbl')
    expect(document.querySelector('a[download]')).not.toBeInTheDocument()

    anchorClick.mockRestore()
  })
  it('confirms restored waits before Undo and sends only the reviewed confirmation', async () => {
    const replaced = { ...existingList, updated_at: '2026-09-14T03:10:00Z' }
    mocks.update.mockResolvedValueOnce(replaced)
      .mockRejectedValueOnce(waitingConfirmationError).mockResolvedValueOnce(existingList)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    mocks.get.mockResolvedValue(replaced)
    fireEvent.click(screen.getByRole('button', { name: 'Undo last replacement' }))
    const dialog = await screen.findByRole('dialog', { name: 'Confirm undo waiting changes' })
    expect(dialog).toHaveTextContent('All-Star Comics #1 now waits on Starman #55.')
    expect(mocks.update).toHaveBeenCalledTimes(2)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and restore' }))
    await screen.findByText(/Restored the previous list membership/)
    expect(mocks.update).toHaveBeenLastCalledWith(9, expect.objectContaining({
      issue_ids: [26360, 30001], confirmed_predecessor_changes: [waitingChange],
    }))
    expect(screen.queryByRole('button', { name: 'Undo last replacement' })).not.toBeInTheDocument()
  })

  it('cancels an Undo confirmation without discarding its retryable snapshot', async () => {
    const replaced = { ...existingList, updated_at: '2026-09-14T03:10:00Z' }
    mocks.update.mockResolvedValueOnce(replaced).mockRejectedValueOnce(waitingConfirmationError)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    mocks.get.mockResolvedValue(replaced)
    fireEvent.click(screen.getByRole('button', { name: 'Undo last replacement' }))
    await screen.findByRole('dialog', { name: 'Confirm undo waiting changes' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mocks.update).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Undo last replacement' })).toBeEnabled()
  })

  it('retains Undo after a transient write failure so the reader can retry', async () => {
    const replaced = { ...existingList, updated_at: '2026-09-14T03:10:00Z' }
    mocks.update.mockResolvedValueOnce(replaced).mockRejectedValueOnce(new Error('Connection lost'))
      .mockResolvedValueOnce(existingList)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    mocks.get.mockResolvedValue(replaced)
    fireEvent.click(screen.getByRole('button', { name: 'Undo last replacement' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost')
    fireEvent.click(screen.getByRole('button', { name: 'Undo last replacement' }))
    await screen.findByText(/Restored the previous list membership/)
    expect(mocks.update).toHaveBeenCalledTimes(3)
  })

  it('cancels replacement waiting changes without sending a second write', async () => {
    mocks.update.mockRejectedValueOnce(waitingConfirmationError)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByRole('dialog', { name: 'Confirm replacement waiting changes' })
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mocks.update).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('confirm-replace')).toBeEnabled()
  })

  it('shows a replacement write failure and lets the reader dismiss the review', async () => {
    mocks.update.mockRejectedValueOnce(new Error('Replacement unavailable'))
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Replacement unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByTestId('cbl-replace-review')).not.toBeInTheDocument()
    expect(mocks.update).toHaveBeenCalledTimes(1)
  })

  it('deduplicates repeated source occurrences and can reload the selected source', async () => {
    mocks.update.mockResolvedValue(existingList)
    await openReplacementReview(true)
    fireEvent.click(screen.getByRole('button', { name: /Global Starman CBL/ }))
    await waitFor(() => expect(cblMocks.preview).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({ issue_ids: [26360, 30001] }))
  })

  it('reports an unstructured creation failure and keeps the draft name for retry', async () => {
    mocks.create.mockRejectedValue({ unavailable: true })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(screen.getByLabelText('New custom CBL name'), { target: { value: 'Retry me' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Custom CBL operation failed.')
    expect(screen.getByLabelText('New custom CBL name')).toHaveValue('Retry me')
  })

  it('keeps a list editable after apply and delete requests fail', async () => {
    mocks.apply.mockRejectedValue(new Error('Apply unavailable'))
    mocks.delete.mockRejectedValue(new Error('Delete unavailable'))
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Starman #55')
    fireEvent.click(screen.getByRole('button', { name: 'Apply to this Reading Plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Apply unavailable')

    // The delete failure keeps the in-page confirmation open with the error
    // visible, so the list stays editable and retryable without a reload.
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete custom CBL' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete custom CBL' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Delete unavailable')
    expect(screen.getByLabelText('Custom CBL')).toHaveValue('9')
    expect(screen.getByRole('list', { name: 'Custom CBL ordered issues' })).toHaveTextContent('Starman #55')
  })

  it('accepts older lists without optional mode, description, or gate fields', async () => {
    mocks.get.mockResolvedValue({ ...existingList, mode: undefined, description: null, entries: existingList.entries.map(
      (entry) => ({ ...entry, gate: undefined }),
    ) })
    mocks.update.mockResolvedValue(existingList)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({
      description: null, mode: 'loose', entry_intents: {
        26360: { gate: 'none', skipped: false }, 30001: { gate: 'none', skipped: false },
      },
    }))
  })

})

